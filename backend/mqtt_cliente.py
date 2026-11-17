"""Cliente MQTT do backend: assina os tópicos do ESP32 e entrega as mensagens ao serviço (paho-mqtt 2.x)."""
import logging

import paho.mqtt.client as mqtt

log = logging.getLogger("fila.mqtt")


class ClienteMqtt:
    def __init__(self, servico, broker, porta, topico_base, client_id=None):
        self.servico = servico
        self.broker = broker
        self.porta = porta
        self.topicos = [f"{topico_base}/evento", f"{topico_base}/status"]
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id or "")
        self.cliente.on_connect = self._ao_conectar
        self.cliente.on_disconnect = self._ao_desconectar
        self.cliente.on_message = self._ao_receber
        self.cliente.reconnect_delay_set(min_delay=1, max_delay=30)

    def iniciar(self):
        """Conecta em segundo plano; se o broker estiver fora do ar, tenta de novo sozinho."""
        self.cliente.connect_async(self.broker, self.porta, keepalive=30)
        self.cliente.loop_start()

    def parar(self):
        self.cliente.disconnect()
        self.cliente.loop_stop()

    def _ao_conectar(self, cliente, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Falha ao conectar no broker: %s", reason_code)
            return
        for t in self.topicos:                       # (re)assina a cada conexão; QoS 1 entrega também as mensagens retidas
            cliente.subscribe(t, qos=1)
        self.servico.mqtt_conectado = True
        log.info("Conectado ao broker %s:%s e assinando %s", self.broker, self.porta, self.topicos)

    def _ao_desconectar(self, cliente, userdata, disconnect_flags, reason_code, properties):
        self.servico.mqtt_conectado = False
        log.warning("Desconectado do broker (%s); reconectando...", reason_code)

    def _ao_receber(self, cliente, userdata, msg):
        try:
            resultado = self.servico.processar_mensagem(msg.topic, msg.payload)
            log.debug("%s -> %s", msg.topic, resultado)
        except Exception:                            # uma mensagem ruim nunca derruba o recebimento
            log.exception("Erro ao processar mensagem de %s", msg.topic)
