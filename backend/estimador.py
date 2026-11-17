"""Carrega o estimador da Etapa 3 (previsao/previsao.py) sem depender de numpy/scikit-learn."""
import importlib.util
import os

_CAMINHO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previsao", "previsao.py")


def _modulo():
    spec = importlib.util.spec_from_file_location("previsao_modelo", _CAMINHO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def carregar_modelo(caminho_json):
    if not os.path.exists(caminho_json):
        raise FileNotFoundError(
            f"Modelo não encontrado em {caminho_json}. Rode 'python treinar.py' dentro de backend/previsao "
            "(ou copie o modelo_regressao.json que veio no zip da Etapa 3).")
    return _modulo().ModeloEspera.carregar(caminho_json)
