"""Teste de ponta a ponta com um broker MQTT REAL rodando no computador (opcional).

Fluxo testado:  mensagens do firmware -> broker MQTT -> backend (ClienteMqtt) -> API /api/status

Precisa de:  pip install amqtt paho-mqtt flask      (amqtt só serve para este teste)
Sem o amqtt, o teste é pulado.
"""
import asyncio
import json
import os
import socket
import sys
import threading
import time
import unittest

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(QUI))

try:
    from amqtt.broker import Broker
    TEM_AMQTT = True
except ImportError:                                  # pragma: no cover
    TEM_AMQTT = False

import paho.mqtt.client as mqtt  # noqa: E402

import config  # noqa: E402
from app import criar_app  # noqa: E402
from banco import Banco  # noqa: E402
from estimador import carregar_modelo  # noqa: E402
from mqtt_cliente import ClienteMqtt  # noqa: E402
from servico import ServicoFila  # noqa: E402

FIXTURE = os.path.join(QUI, "dados", "mqtt_firmware.tsv")


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BrokerLocal:
    """Broker amqtt em thread própria."""

    def __init__(self):
        self.porta = porta_livre()
        self.loop = asyncio.new_event_loop()
        self.broker = None
        self.pronto = threading.Event()
        self.thread = threading.Thread(target=self._rodar, daemon=True)

    def _rodar(self):
        asyncio.set_event_loop(self.loop)
        cfg = {
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.porta}"}},
            "sys_interval": 0,
            "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]},
            "topic-check": {"enabled": False},
        }
        self.broker = Broker(cfg, loop=self.loop) if "loop" in Broker.__init__.__code__.co_varnames else Broker(cfg)
        self.loop.run_until_complete(self.broker.start())
        self.pronto.set()
        self.loop.run_forever()

    def iniciar(self):
        self.thread.start()
        if not self.pronto.wait(15):
            raise RuntimeError("broker de teste não subiu")
        time.sleep(0.3)

    def parar(self):
        try:
            fut = asyncio.run_coroutine_threadsafe(self.broker.shutdown(), self.loop)
            fut.result(timeout=5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


def esperar(condicao, tempo=10.0):
    fim = time.time() + tempo
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(0.05)
    return False


def publicar(porta, mensagens, will=None):
    """Publica como o ESP32: eventos retidos, QoS 0 (a PubSubClient só publica QoS 0)."""
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="esp32-teste")
    if will:
        c.will_set(*will)
    c.connect("127.0.0.1", porta, 30)
    c.loop_start()
    for topico, payload, retida in mensagens:
        c.publish(topico, payload, qos=0, retain=retida).wait_for_publish()
    return c


def ler_fixture():
    mensagens = []
    with open(FIXTURE, encoding="utf-8") as f:
        for linha in f:
            t, p, r = linha.rstrip("\n").split("\t")
            mensagens.append((t, p, r == "1"))
    return mensagens


@unittest.skipUnless(TEM_AMQTT, "amqtt não instalado")
@unittest.skipUnless(os.path.exists(FIXTURE), "gere tests/dados/mqtt_firmware.tsv (firmware/test/run_tests.sh)")
class TestPontaAPonta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.broker = BrokerLocal()
        cls.broker.iniciar()

    @classmethod
    def tearDownClass(cls):
        cls.broker.parar()

    def _backend(self, topico_base):
        srv = ServicoFila(Banco(":memory:"), carregar_modelo(config.CAMINHO_MODELO), topico_base)
        cli = ClienteMqtt(srv, "127.0.0.1", self.broker.porta, topico_base, client_id=f"backend-{time.time_ns()}")
        cli.iniciar()
        self.addCleanup(cli.parar)
        self.assertTrue(esperar(lambda: srv.mqtt_conectado), "backend não conectou no broker")
        time.sleep(0.6)   # deixa a assinatura terminar: o amqtt (broker de teste) tem uma corrida entre assinar e conectar outro cliente
        return srv

    def _remapear(self, mensagens, base):
        original = mensagens[0][0].rsplit("/", 1)[0]
        return [(t.replace(original, base), p, r) for t, p, r in mensagens]

    def test_mensagens_do_firmware_chegam_ao_painel(self):
        base = f"e2e/{time.time_ns()}"
        srv = self._backend(base)
        msgs = self._remapear(ler_fixture(), base)
        cliente = publicar(self.broker.porta, msgs)
        self.addCleanup(cliente.disconnect)
        n_eventos = sum(1 for t, _, _ in msgs if t.endswith("/evento"))
        self.assertTrue(esperar(lambda: srv.banco.contagens()["total"] >= n_eventos), "eventos não chegaram")
        ultimo = json.loads([p for t, p, _ in msgs if t.endswith("/evento")][-1])

        status = criar_app(srv).test_client().get("/api/status").get_json()
        self.assertEqual((status["fila"], status["atendidos"]), (ultimo["fila"], ultimo["atendidos"]))
        self.assertTrue(status["mqtt_conectado"])
        self.assertEqual(status["dispositivo"]["status"], "online")
        self.assertEqual(status["mensagens_invalidas"], 0)

    def test_backend_iniciado_depois_recebe_o_ultimo_estado_retido(self):
        base = f"e2e/{time.time_ns()}"
        msgs = self._remapear(ler_fixture(), base)
        cliente = publicar(self.broker.porta, msgs)               # o ESP32 já publicou antes do backend existir
        self.addCleanup(cliente.disconnect)
        time.sleep(0.5)
        srv = self._backend(base)                                  # backend sobe depois: recebe só os retidos
        ultimo = json.loads([p for t, p, _ in msgs if t.endswith("/evento")][-1])
        self.assertTrue(esperar(lambda: srv.estado["seq"] == ultimo["seq"]), "estado retido não chegou")
        self.assertEqual(srv.estado["fila"], ultimo["fila"])

    def test_queda_do_esp32_vira_offline_pelo_last_will(self):
        base = f"e2e/{time.time_ns()}"
        srv = self._backend(base)
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"esp32-{time.time_ns()}")
        c.will_set(f"{base}/status", "offline", qos=1, retain=True)
        c.connect("127.0.0.1", self.broker.porta, 30)
        c.loop_start()
        c.publish(f"{base}/status", "online", qos=1, retain=True).wait_for_publish()
        self.assertTrue(esperar(lambda: srv.dispositivo == "online"))
        c._sock.close()                                            # queda abrupta, sem DISCONNECT (como tirar da tomada)
        self.assertTrue(esperar(lambda: srv.dispositivo == "offline", 10), "last will não chegou")
        c.loop_stop()


if __name__ == "__main__":
    unittest.main()
