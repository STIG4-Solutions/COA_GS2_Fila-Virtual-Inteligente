"""Servidor Flask: painel no navegador + API JSON + assinatura MQTT.

    python app.py            ->  http://127.0.0.1:5000
"""
import logging
import os

from flask import Flask, jsonify, request, send_from_directory

import config
from banco import Banco
from estimador import carregar_modelo
from mqtt_cliente import ClienteMqtt
from servico import ServicoFila

PASTA_ESTATICA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def criar_app(servico):
    app = Flask(__name__, static_folder=PASTA_ESTATICA, static_url_path="/static")
    app.config["JSON_AS_ASCII"] = False

    @app.get("/")
    def painel():
        return send_from_directory(PASTA_ESTATICA, "index.html")

    @app.get("/api/status")
    def api_status():
        return jsonify(servico.status())

    @app.get("/api/eventos")
    def api_eventos():
        try:
            limite = int(request.args.get("limite", 20))
        except ValueError:
            limite = 20
        return jsonify(servico.eventos(max(1, min(limite, 200))))

    @app.get("/api/saude")
    def api_saude():
        return jsonify({
            "ok": True,
            "mqtt_conectado": servico.mqtt_conectado,
            "broker": f"{config.MQTT_BROKER}:{config.MQTT_PORTA}",
            "topico_base": config.TOPICO_BASE,
            "modelo": servico.modelo.info,
        })

    @app.after_request
    def sem_cache(resp):                              # o painel precisa sempre do dado mais recente
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    banco = Banco(config.CAMINHO_BANCO)
    servico = ServicoFila(banco, carregar_modelo(config.CAMINHO_MODELO), config.TOPICO_BASE, fuso_s=config.FUSO_S)
    mqtt_cli = ClienteMqtt(servico, config.MQTT_BROKER, config.MQTT_PORTA, config.TOPICO_BASE)
    mqtt_cli.iniciar()
    print(f"Painel:  http://{config.HTTP_HOST}:{config.HTTP_PORTA}")
    print(f"Broker:  {config.MQTT_BROKER}:{config.MQTT_PORTA}   tópico base: {config.TOPICO_BASE}")
    try:
        criar_app(servico).run(host=config.HTTP_HOST, port=config.HTTP_PORTA, debug=False, use_reloader=False,
                               threaded=True)
    finally:
        mqtt_cli.parar()
        banco.fechar()


if __name__ == "__main__":
    main()
