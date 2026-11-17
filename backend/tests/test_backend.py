"""Testes do backend (Etapa 4). Rodar, dentro de backend/:   python -m unittest discover -s tests -v"""
import json
import os
import sys
import unittest
from datetime import datetime, timezone

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(QUI))

import config  # noqa: E402
from app import criar_app  # noqa: E402
from banco import Banco  # noqa: E402
from estimador import carregar_modelo  # noqa: E402
from servico import EventoInvalido, ServicoFila, validar_evento  # noqa: E402

BASE = "teste/fila"
EVENTO, STATUS = f"{BASE}/evento", f"{BASE}/status"
SESSAO = "a1b2c3d4"


def msg(seq, tipo="CHEGADA", fila=1, atendidos=0, media_ms=0, sessao=SESSAO, **extra):
    n = seq if isinstance(seq, int) and not isinstance(seq, bool) else 1      # seq pode ser lixo de propósito
    d = {"sessao": sessao, "seq": seq, "tipo": tipo, "valido": tipo in ("CHEGADA", "CONCLUSAO"),
         "fila": fila, "atendidos": atendidos, "hora_s": 1794361680 + n, "hora_real": True,
         "uptime_ms": 1000 * n, "espera_ms": 0, "atendimento_ms": 0, "media_ms": media_ms}
    d.update(extra)
    return json.dumps(d).encode()


class Relogio:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def novo_servico(banco=None, t=None):
    # 14:30 UTC = 11:30 em São Paulo
    t = t if t is not None else datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc).timestamp()
    rel = Relogio(t)
    srv = ServicoFila(banco or Banco(":memory:"), carregar_modelo(config.CAMINHO_MODELO), BASE, relogio=rel)
    return srv, rel


class TestValidacao(unittest.TestCase):
    def test_evento_valido(self):
        ev = validar_evento(msg(1))
        self.assertEqual((ev["sessao"], ev["seq"], ev["tipo"], ev["valido"]), (SESSAO, 1, "CHEGADA", True))

    def test_rejeita_entradas_ruins(self):
        ruins = [
            b"nao e json", b"[1,2,3]", b"\xff\xfe",
            msg(1, tipo="TIPO_FALSO"),
            msg(0), msg(True), msg("3"),                                # seq: zero, booleano e texto
            msg(1, fila=-1), msg(1, fila=100000), msg(1, atendidos=1.5),
            msg(1, sessao="ZZZ!"), msg(1, sessao=""),
            msg(1, valido="sim"), msg(1, hora_real=1),
            msg(1, tipo="CHEGADA", valido=False),                  # 'valido' incoerente com o tipo
            msg(1, tipo="REJEITADA_VAZIA", valido=True),
            b"{" + b"x" * 2000 + b"}",                              # grande demais
        ]
        for r in ruins:
            with self.assertRaises(EventoInvalido, msg=repr(r)[:60]):
                validar_evento(r)

    def test_campo_faltando(self):
        d = json.loads(msg(1))
        del d["media_ms"]
        with self.assertRaises(EventoInvalido):
            validar_evento(json.dumps(d))


class TestServico(unittest.TestCase):
    def test_estado_inicial(self):
        srv, _ = novo_servico()
        s = srv.status()
        self.assertEqual((s["fila"], s["atendidos"], s["rejeitadas"]), (0, 0, 0))
        self.assertEqual(s["espera_estimada"]["ia_s"], 0)
        self.assertEqual(s["espera_estimada"]["convencional_s"], 0)
        self.assertEqual(s["dispositivo"]["status"], "desconhecido")
        self.assertIsNone(s["dispositivo"]["ultimo_evento_ha_s"])

    def test_sequencia_de_eventos_atualiza_o_estado(self):
        srv, _ = novo_servico()
        self.assertEqual(srv.processar_mensagem(EVENTO, msg(1, fila=1)), "evento")
        srv.processar_mensagem(EVENTO, msg(2, fila=2))
        srv.processar_mensagem(EVENTO, msg(3, "CONCLUSAO", fila=1, atendidos=1, media_ms=4000, espera_ms=0, atendimento_ms=4000))
        s = srv.status()
        self.assertEqual((s["fila"], s["atendidos"]), (1, 1))
        self.assertEqual(s["eventos_total"], 3)
        self.assertEqual(s["dispositivo"]["status"], "online")        # deduzido do primeiro evento
        self.assertEqual(s["espera_estimada"]["media_atendimento_s"], 4.0)

    def test_tentativa_com_fila_vazia_e_contada_e_nao_altera_a_fila(self):
        srv, _ = novo_servico()
        srv.processar_mensagem(EVENTO, msg(1, "REJEITADA_VAZIA", fila=0))
        s = srv.status()
        self.assertEqual((s["fila"], s["atendidos"], s["rejeitadas"]), (0, 0, 1))

    def test_mensagem_duplicada_e_ignorada(self):
        srv, _ = novo_servico()
        self.assertEqual(srv.processar_mensagem(EVENTO, msg(1)), "evento")
        self.assertEqual(srv.processar_mensagem(EVENTO, msg(1)), "duplicado")     # ex.: mensagem retida reentregue
        s = srv.status()
        self.assertEqual(s["eventos_total"], 1)
        self.assertEqual(s["mensagens_duplicadas"], 1)

    def test_chegada_atrasada_nao_desfaz_o_estado(self):
        srv, _ = novo_servico()
        srv.processar_mensagem(EVENTO, msg(5, fila=4))
        srv.processar_mensagem(EVENTO, msg(4, fila=3))      # chegou fora de ordem
        self.assertEqual(srv.status()["fila"], 4)
        self.assertEqual(srv.status()["eventos_total"], 2)  # mas o evento é guardado no histórico

    def test_novo_boot_do_esp32_reinicia_a_fila(self):
        srv, _ = novo_servico()
        srv.processar_mensagem(EVENTO, msg(7, fila=5, atendidos=3))
        srv.processar_mensagem(EVENTO, msg(1, fila=1, atendidos=0, sessao="deadbeef"))   # ESP32 reiniciou: seq volta a 1
        s = srv.status()
        self.assertEqual((s["fila"], s["atendidos"]), (1, 0))

    def test_eventos_perdidos_aparecem_como_lacuna(self):
        srv, _ = novo_servico()
        srv.processar_mensagem(EVENTO, msg(16, fila=1))      # os 15 anteriores nunca chegaram
        srv.processar_mensagem(EVENTO, msg(17, fila=2))
        srv.processar_mensagem(EVENTO, msg(20, fila=3))      # 18 e 19 também se perderam
        self.assertEqual(srv.status()["eventos_perdidos"], 20 - 3)

    def test_mensagens_invalidas_sao_descartadas_e_contadas(self):
        srv, _ = novo_servico()
        self.assertEqual(srv.processar_mensagem(EVENTO, b"lixo"), "invalida")
        self.assertEqual(srv.processar_mensagem(EVENTO, msg(1, tipo="X")), "invalida")
        self.assertEqual(srv.processar_mensagem(STATUS, b"talvez"), "invalida")
        self.assertEqual(srv.processar_mensagem("outro/topico", msg(1)), "ignorada")
        s = srv.status()
        self.assertEqual((s["mensagens_invalidas"], s["eventos_total"], s["fila"]), (3, 0, 0))

    def test_status_do_dispositivo_pelo_topico(self):
        srv, _ = novo_servico()
        srv.processar_mensagem(STATUS, b"online")
        self.assertEqual(srv.status()["dispositivo"]["status"], "online")
        srv.processar_mensagem(STATUS, b"offline")               # last will do broker
        self.assertEqual(srv.status()["dispositivo"]["status"], "offline")

    def test_estimativa_bate_com_o_modelo_da_etapa_3(self):
        srv, _ = novo_servico()
        srv.processar_mensagem(EVENTO, msg(1, fila=5, atendidos=4, media_ms=230000))
        e = srv.status()["espera_estimada"]
        m = srv.modelo
        self.assertAlmostEqual(e["convencional_s"], round(5 * m.media_historica_s, 1), places=1)
        esperado_ia = m.prever_ia(5, 230.0, 11.5)           # 14:30 UTC = 11:30 em São Paulo
        self.assertAlmostEqual(e["ia_s"], round(esperado_ia, 1), places=1)
        self.assertFalse(e["ia_usou_fallback"])

    def test_sem_media_recente_usa_o_convencional(self):
        srv, _ = novo_servico()
        srv.processar_mensagem(EVENTO, msg(1, fila=3, media_ms=0))
        e = srv.status()["espera_estimada"]
        self.assertTrue(e["ia_usou_fallback"])
        self.assertEqual(e["ia_s"], e["convencional_s"])
        self.assertIsNone(e["media_atendimento_s"])

    def test_estimativa_acompanha_a_fila_e_volta_a_zero(self):
        srv, _ = novo_servico()
        ia = []
        for seq, fila in enumerate([1, 2, 3, 4], start=1):
            srv.processar_mensagem(EVENTO, msg(seq, fila=fila, media_ms=200000))
            ia.append(srv.status()["espera_estimada"]["ia_s"])
        self.assertEqual(ia, sorted(ia))
        self.assertTrue(ia[-1] > ia[0] > 0)
        srv.processar_mensagem(EVENTO, msg(5, "CONCLUSAO", fila=0, atendidos=4, media_ms=200000))
        self.assertEqual(srv.status()["espera_estimada"]["ia_s"], 0)          # fila vazia => sem espera

    def test_reinicio_do_servidor_retoma_do_banco(self):
        banco = Banco(":memory:")
        srv, _ = novo_servico(banco)
        srv.processar_mensagem(EVENTO, msg(1, fila=2, atendidos=1, media_ms=3000))
        srv2, _ = novo_servico(banco)                                    # "reiniciou" o backend, mesmo banco
        s = srv2.status()
        self.assertEqual((s["fila"], s["atendidos"], s["eventos_total"]), (2, 1, 1))

    def test_ultimo_evento_ha_s(self):
        srv, rel = novo_servico()
        srv.processar_mensagem(EVENTO, msg(1))
        rel.t += 42
        self.assertAlmostEqual(srv.status()["dispositivo"]["ultimo_evento_ha_s"], 42.0, places=1)


class TestApi(unittest.TestCase):
    def setUp(self):
        self.srv, _ = novo_servico()
        self.cli = criar_app(self.srv).test_client()

    def test_status_json_e_sem_cache(self):
        self.srv.processar_mensagem(EVENTO, msg(1, fila=2, media_ms=180000))
        r = self.cli.get("/api/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        d = r.get_json()
        for chave in ("fila", "atendidos", "rejeitadas", "espera_estimada", "dispositivo", "mqtt_conectado",
                      "eventos_total", "eventos_perdidos", "origem_do_modelo"):
            self.assertIn(chave, d)
        for chave in ("ia_s", "convencional_s", "ia_usou_fallback", "media_atendimento_s"):
            self.assertIn(chave, d["espera_estimada"])
        self.assertEqual(d["fila"], 2)

    def test_eventos_ordem_e_limite(self):
        for i in range(1, 31):
            self.srv.processar_mensagem(EVENTO, msg(i, fila=i % 5))
        lista = self.cli.get("/api/eventos?limite=10").get_json()
        self.assertEqual(len(lista), 10)
        self.assertEqual(lista[0]["seq"], 30)                          # mais recente primeiro
        self.assertEqual(len(self.cli.get("/api/eventos?limite=9999").get_json()), 30)   # limite máximo de 200
        self.assertEqual(len(self.cli.get("/api/eventos?limite=abc").get_json()), 20)    # valor ruim => padrão
        self.assertEqual(len(self.cli.get("/api/eventos?limite=0").get_json()), 1)

    def test_painel_e_arquivos_estaticos(self):
        r = self.cli.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Fila Virtual", r.get_data(as_text=True))
        r.close()
        for arquivo in ("/static/app.js", "/static/estilo.css"):
            resp = self.cli.get(arquivo)
            self.assertEqual(resp.status_code, 200)
            resp.close()

    def test_saude_e_404(self):
        d = self.cli.get("/api/saude").get_json()
        self.assertTrue(d["ok"])
        self.assertEqual(self.cli.get("/api/nao-existe").status_code, 404)


class TestContratoComOFirmware(unittest.TestCase):
    """Reproduz EXATAMENTE as mensagens que o sketch.ino publica (geradas pela simulação do firmware)."""

    def test_mensagens_do_firmware_sao_aceitas(self):
        caminho = os.path.join(QUI, "dados", "mqtt_firmware.tsv")
        if not os.path.exists(caminho):
            self.skipTest("rode firmware/test/run_tests.sh para gerar o arquivo")
        srv, _ = novo_servico()
        srv.topico_evento, srv.topico_status = None, None
        resultados, ultimo = [], None
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                topico, payload, _retida = linha.rstrip("\n").split("\t")
                if topico.endswith("/evento"):
                    srv.topico_evento = topico
                    ultimo = json.loads(payload)
                else:
                    srv.topico_status = topico
                resultados.append(srv.processar_mensagem(topico, payload.encode()))
        self.assertNotIn("invalida", resultados)
        self.assertEqual(resultados.count("evento"), sum(1 for r in resultados if r == "evento"))
        self.assertGreaterEqual(resultados.count("evento"), 3)
        s = srv.status()
        self.assertEqual((s["fila"], s["atendidos"]), (ultimo["fila"], ultimo["atendidos"]))
        self.assertEqual(s["mensagens_invalidas"], 0)
        self.assertEqual(s["dispositivo"]["status"], "online")
        self.assertGreater(s["eventos_perdidos"], 0)          # o firmware numerou eventos enviados antes do broker voltar


if __name__ == "__main__":
    unittest.main()
