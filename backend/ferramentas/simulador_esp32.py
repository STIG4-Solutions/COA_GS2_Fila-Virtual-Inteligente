"""Simulador do ESP32 — NÃO é o firmware.

Publica no broker MQTT eventos no MESMO formato do sketch.ino, para ensaiar o backend e o painel
sem precisar do Wokwi (ou para gravar o vídeo com um roteiro previsível).

  python ferramentas/simulador_esp32.py                      # roteiro de demonstração
  python ferramentas/simulador_esp32.py --cenario aleatorio --eventos 40 --ritmo 1

Os tempos de atendimento são simulados (1 a 4 minutos "virtuais" por passo); a hora do evento é a real.
Use o mesmo broker e tópico base do backend (variáveis FILA_MQTT_BROKER e FILA_TOPICO_BASE).
"""
import argparse
import json
import os
import random
import secrets
import sys
import time
from collections import deque

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

CAP_FILA = 100
JANELA = 10


class FilaSimulada:
    """Mesmas regras do fila_core.h (FIFO, um atendente, recusa com fila vazia/cheia, média móvel de 10)."""

    def __init__(self, sessao=None):
        self.sessao = sessao or secrets.token_hex(4)
        self.seq = 0
        self.chegadas = deque()
        self.atendidos = 0
        self.ultima_conclusao = None
        self.janela = deque(maxlen=JANELA)

    def _media_ms(self):
        return int(sum(self.janela) / len(self.janela)) if self.janela else 0

    def evento(self, acao, t_ms, hora_s):
        """acao: 'c' (chegada) ou 's' (conclusão). Devolve o dict do evento (mesmos campos do firmware)."""
        self.seq += 1
        espera = atend = 0
        if acao == "c":
            if len(self.chegadas) >= CAP_FILA:
                tipo = "REJEITADA_CHEIA"
            else:
                tipo = "CHEGADA"
                self.chegadas.append(t_ms)
        else:
            if not self.chegadas:
                tipo = "REJEITADA_VAZIA"
            else:
                tipo = "CONCLUSAO"
                chegou = self.chegadas.popleft()
                inicio = chegou if (self.ultima_conclusao is None or self.ultima_conclusao <= chegou) else self.ultima_conclusao
                espera, atend = inicio - chegou, t_ms - inicio
                self.ultima_conclusao = t_ms
                self.atendidos += 1
                self.janela.append(atend)
        return {"sessao": self.sessao, "seq": self.seq, "tipo": tipo, "valido": tipo in ("CHEGADA", "CONCLUSAO"),
                "fila": len(self.chegadas), "atendidos": self.atendidos, "hora_s": int(hora_s), "hora_real": True,
                "uptime_ms": int(t_ms), "espera_ms": int(espera), "atendimento_ms": int(atend),
                "media_ms": self._media_ms()}


ROTEIRO_DEMO = list("cccc" "ss" "cc" "ssss" "ss" "c" "s")   # termina esvaziando a fila e tentando concluir com ela vazia


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default=config.MQTT_BROKER)
    ap.add_argument("--porta", type=int, default=config.MQTT_PORTA)
    ap.add_argument("--topico-base", default=config.TOPICO_BASE)
    ap.add_argument("--cenario", choices=["demo", "aleatorio"], default="demo")
    ap.add_argument("--eventos", type=int, default=30, help="quantos eventos no cenário aleatório")
    ap.add_argument("--ritmo", type=float, default=1.5, help="segundos reais entre eventos")
    ap.add_argument("--semente", type=int, default=None)
    args = ap.parse_args()

    rng = random.Random(args.semente)
    t_evento, t_status = f"{args.topico_base}/evento", f"{args.topico_base}/status"
    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fila-esp32-sim-{secrets.token_hex(3)}")
    cli.will_set(t_status, "offline", qos=1, retain=True)
    cli.connect(args.broker, args.porta, 30)
    cli.loop_start()
    cli.publish(t_status, "online", qos=1, retain=True).wait_for_publish()

    fila = FilaSimulada()
    if args.cenario == "demo":
        passos = ROTEIRO_DEMO
    else:
        passos, tam = [], 0
        for _ in range(args.eventos):
            if tam == 0:
                a = "c" if rng.random() < 0.85 else "s"      # de vez em quando tenta concluir com a fila vazia
            else:
                a = "c" if rng.random() < 0.5 else "s"
            tam += 1 if a == "c" else (-1 if tam else 0)
            passos.append(a)

    t_ms = 0
    print(f"Simulando {len(passos)} eventos em {args.broker}:{args.porta} · tópico {t_evento} · sessão {fila.sessao}")
    for a in passos:
        t_ms += int(rng.uniform(60, 240) * 1000)                # passa 1 a 4 minutos "virtuais"
        ev = fila.evento(a, t_ms, time.time())
        cli.publish(t_evento, json.dumps(ev), qos=0, retain=True).wait_for_publish()
        print(f"  seq={ev['seq']:<3} {ev['tipo']:<16} fila={ev['fila']:<3} atendidos={ev['atendidos']:<3} media={ev['media_ms']/1000:.0f}s")
        time.sleep(args.ritmo)

    cli.publish(t_status, "offline", qos=1, retain=True).wait_for_publish()
    cli.loop_stop()
    cli.disconnect()


if __name__ == "__main__":
    main()
