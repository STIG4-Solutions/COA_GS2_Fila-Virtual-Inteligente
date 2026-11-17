"""Converte o histórico REAL guardado pelo backend (SQLite) no CSV de treino da Etapa 3.

  python ferramentas/exportar_dataset.py                       # grava previsao/dados/dados_reais.csv
  cd previsao && python treinar.py --csv dados/dados_reais.csv  # retreina com os dados reais

Usa as mesmas regras do firmware (previsao/dataset.py). Limitações: a hora do evento tem resolução de 1 s
e só entram eventos com hora real (NTP). Cada reinício do ESP32 (nova sessão) começa uma fila nova.
"""
import argparse
import csv
import importlib.util
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import config  # noqa: E402
from banco import Banco  # noqa: E402


def _dataset():
    spec = importlib.util.spec_from_file_location("dataset_etapa3", os.path.join(RAIZ, "previsao", "dataset.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def exportar(banco, caminho_saida, fuso_s=config.FUSO_S):
    ds = _dataset()
    por_sessao = {}
    for e in banco.todos_em_ordem():
        if e["valido"] and e["hora_real"]:
            por_sessao.setdefault(e["sessao"], []).append((e["tipo"], float(e["hora_s"])))
    linhas = []
    for eventos in por_sessao.values():
        linhas += ds.eventos_para_dataset(eventos, origem="REAL", fuso_s=fuso_s)
    os.makedirs(os.path.dirname(os.path.abspath(caminho_saida)), exist_ok=True)
    with open(caminho_saida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ds.COLUNAS, lineterminator="\n")
        w.writeheader()
        for l in linhas:
            w.writerow({k: ("" if v is None else v) for k, v in l.items()})
    return len(linhas)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--banco", default=config.CAMINHO_BANCO)
    ap.add_argument("--saida", default=os.path.join(RAIZ, "previsao", "dados", "dados_reais.csv"))
    a = ap.parse_args()
    n = exportar(Banco(a.banco), a.saida)
    print(f"{n} pessoas atendidas exportadas para {a.saida} (origem = REAL)")
