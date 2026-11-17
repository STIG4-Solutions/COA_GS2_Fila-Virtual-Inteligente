"""Regras do backend: valida cada mensagem MQTT, grava, mantém o estado atual e calcula as estimativas.

Não depende de MQTT nem de Flask, então é testado isoladamente.
O ESP32 é a fonte da verdade da fila (divisão A): o backend só espelha o estado que ele publica.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone

TIPOS = ("CHEGADA", "CONCLUSAO", "REJEITADA_VAZIA", "REJEITADA_CHEIA")
TIPOS_VALIDOS = ("CHEGADA", "CONCLUSAO")
MAX_PAYLOAD_BYTES = 1024
_RE_SESSAO = re.compile(r"^[0-9a-fA-F]{1,16}$")


class EventoInvalido(ValueError):
    pass


def _inteiro(ev, chave, minimo=0, maximo=2 ** 40):
    v = ev.get(chave)
    if isinstance(v, bool) or not isinstance(v, int) or not (minimo <= v <= maximo):
        raise EventoInvalido(f"campo '{chave}' inválido: {v!r}")
    return v


def _booleano(ev, chave):
    v = ev.get(chave)
    if not isinstance(v, bool):
        raise EventoInvalido(f"campo '{chave}' deve ser true/false: {v!r}")
    return v


def validar_evento(payload):
    """Valida o JSON publicado pelo firmware. O broker é público: nada que chegue é confiável."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise EventoInvalido("mensagem grande demais")
    try:
        ev = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise EventoInvalido(f"JSON inválido: {e}")
    if not isinstance(ev, dict):
        raise EventoInvalido("o JSON precisa ser um objeto")
    sessao = ev.get("sessao")
    if not isinstance(sessao, str) or not _RE_SESSAO.match(sessao):
        raise EventoInvalido(f"campo 'sessao' inválido: {sessao!r}")
    tipo = ev.get("tipo")
    if tipo not in TIPOS:
        raise EventoInvalido(f"campo 'tipo' inválido: {tipo!r}")
    ok = {
        "sessao": sessao.lower(),
        "seq": _inteiro(ev, "seq", 1),
        "tipo": tipo,
        "valido": _booleano(ev, "valido"),
        "fila": _inteiro(ev, "fila", 0, 1000),
        "atendidos": _inteiro(ev, "atendidos", 0, 10 ** 9),
        "hora_s": _inteiro(ev, "hora_s", 0),
        "hora_real": _booleano(ev, "hora_real"),
        "uptime_ms": _inteiro(ev, "uptime_ms", 0, 2 ** 32),
        "espera_ms": _inteiro(ev, "espera_ms", 0, 2 ** 32),
        "atendimento_ms": _inteiro(ev, "atendimento_ms", 0, 2 ** 32),
        "media_ms": _inteiro(ev, "media_ms", 0, 2 ** 32),
    }
    if ok["valido"] != (tipo in TIPOS_VALIDOS):
        raise EventoInvalido("'valido' não combina com 'tipo'")
    return ok


class ServicoFila:
    def __init__(self, banco, modelo, topico_base, relogio=time.time, fuso_s=-3 * 3600):
        self.banco = banco
        self.modelo = modelo
        self.topico_evento = f"{topico_base}/evento"
        self.topico_status = f"{topico_base}/status"
        self.relogio = relogio
        self.fuso_s = fuso_s
        self._lock = threading.RLock()
        self.mqtt_conectado = False
        self.dispositivo = "desconhecido"          # online | offline | desconhecido (tópico <base>/status)
        self.invalidas = 0
        self.duplicadas = 0
        self.estado = {"fila": 0, "atendidos": 0, "media_ms": 0, "sessao": None, "seq": 0, "recebido_em": None}
        ultimo = banco.ultimo_evento()               # reinício do servidor: retoma de onde parou
        if ultimo:
            self._aplicar(ultimo, ultimo["recebido_em"])

    # ------------------------------------------------------------------ entrada
    def processar_mensagem(self, topico, payload):
        """Devolve: 'evento', 'duplicado', 'invalida', 'status' ou 'ignorada'."""
        with self._lock:
            if topico == self.topico_status:
                texto = payload.decode("utf-8", "replace").strip().lower() if isinstance(payload, bytes) else str(payload).strip().lower()
                if texto in ("online", "offline"):
                    self.dispositivo = texto
                    return "status"
                self.invalidas += 1
                return "invalida"
            if topico != self.topico_evento:
                return "ignorada"
            try:
                ev = validar_evento(payload)
            except EventoInvalido:
                self.invalidas += 1
                return "invalida"
            agora = self.relogio()
            if not self.banco.inserir_evento(ev, agora):
                self.duplicadas += 1
                return "duplicado"
            self._aplicar(ev, agora)
            return "evento"

    def _aplicar(self, ev, recebido_em):
        e = self.estado
        mais_novo = ev["sessao"] != e["sessao"] or ev["seq"] > e["seq"]   # chegada atrasada não desfaz o estado
        if mais_novo:
            e.update(fila=ev["fila"], atendidos=ev["atendidos"], media_ms=ev["media_ms"],
                     sessao=ev["sessao"], seq=ev["seq"], recebido_em=recebido_em)
            if self.dispositivo == "desconhecido":
                self.dispositivo = "online"

    # ------------------------------------------------------------------ saída
    def hora_do_dia(self):
        local = datetime.fromtimestamp(self.relogio(), tz=timezone(timedelta(seconds=self.fuso_s)))
        return local.hour + local.minute / 60 + local.second / 3600

    def estimativa(self):
        fila = self.estado["fila"]
        media_s = self.estado["media_ms"] / 1000.0 if self.estado["media_ms"] > 0 else None
        est = self.modelo.estimar(fila, media_s, self.hora_do_dia())
        return {
            "pessoas_a_frente": fila,
            "ia_s": round(est["ia_s"], 1),
            "convencional_s": round(est["convencional_s"], 1),
            "ia_usou_fallback": bool(est["ia_usou_fallback"]),
            "media_atendimento_s": None if media_s is None else round(media_s, 1),
            "media_historica_s": round(self.modelo.media_historica_s, 1),
        }

    def status(self):
        with self._lock:
            c = self.banco.contagens()
            rec = self.estado["recebido_em"]
            agora = self.relogio()
            return {
                "fila": self.estado["fila"],
                "atendidos": self.estado["atendidos"],
                "rejeitadas": c["rejeitadas"],
                "espera_estimada": self.estimativa(),
                "dispositivo": {
                    "status": self.dispositivo,
                    "ultimo_evento_ha_s": None if rec is None else round(max(0.0, agora - rec), 1),
                },
                "mqtt_conectado": self.mqtt_conectado,
                "eventos_total": c["total"],
                "eventos_perdidos": c["lacunas"],
                "mensagens_invalidas": self.invalidas,
                "mensagens_duplicadas": self.duplicadas,
                "origem_do_modelo": self.modelo.info.get("origem_dos_dados", []),
                "gerado_em": datetime.fromtimestamp(agora, tz=timezone(timedelta(seconds=self.fuso_s))).isoformat(timespec="seconds"),
            }

    def eventos(self, limite=20):
        return self.banco.eventos_recentes(limite)
