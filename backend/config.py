"""Configuração do backend. Tudo pode ser trocado por variável de ambiente (prefixo FILA_)."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Broker MQTT público (sem senha). O tópico base precisa ser IGUAL ao TOPICO_BASE do firmware (sketch.ino)
# e, por ser público, deve ser único do grupo.
MQTT_BROKER = os.environ.get("FILA_MQTT_BROKER", "broker.hivemq.com")
MQTT_PORTA = int(os.environ.get("FILA_MQTT_PORTA", "1883"))
TOPICO_BASE = os.environ.get("FILA_TOPICO_BASE", "fiap1ccfev/citizenassist/gs2026-Stig4")

CAMINHO_BANCO = os.environ.get("FILA_BANCO", os.path.join(BASE_DIR, "dados", "fila.db"))
CAMINHO_MODELO = os.environ.get("FILA_MODELO", os.path.join(BASE_DIR, "previsao", "dados", "modelo_regressao.json"))

FUSO_S = int(os.environ.get("FILA_FUSO_S", str(-3 * 3600)))   # São Paulo (UTC-3), usado na "hora do dia"

HTTP_HOST = os.environ.get("FILA_HTTP_HOST", "127.0.0.1")     # só este computador; use 0.0.0.0 para a rede local
HTTP_PORTA = int(os.environ.get("FILA_HTTP_PORTA", "5000"))
