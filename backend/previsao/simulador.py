"""Gerador de DADOS SIMULADOS (sintéticos) de uma fila com um atendente.

ATENÇÃO: nada aqui é medição real. As hipóteses (taxas de chegada, tempos de atendimento) são
inventadas para ter um cenário plausível: horários de pico, atendimento mais lento no almoço,
casos complexos, e um "ritmo do dia" que muda de um dia para o outro. Todo arquivo gerado é
marcado com origem = SIMULADO e acompanhado de um .meta.json com os parâmetros.

Uso:  python simulador.py            (gera dados/dados_simulados.csv e .meta.json)
"""
import csv
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np

from dataset import COLUNAS, FUSO_PADRAO_S, eventos_para_dataset, hora_do_dia

SEED = 2026
DIAS_UTEIS = 40
DATA_INICIAL = date(2026, 9, 1)

# Pessoas que chegam por hora (média de um processo de Poisson) — horário de atendimento 8h às 18h
TAXA_CHEGADA_POR_HORA = {8: 5, 9: 7, 10: 10, 11: 12, 12: 10, 13: 9, 14: 11, 15: 12, 16: 10, 17: 6}
# Mediana do tempo de atendimento (minutos) por hora em que o atendimento COMEÇA; almoço é mais lento
MEDIANA_ATENDIMENTO_MIN = {8: 2.6, 9: 2.6, 10: 3.0, 11: 3.3, 12: 4.0, 13: 4.0, 14: 3.2, 15: 3.0, 16: 3.0, 17: 2.7}
SIGMA_LOGNORMAL = 0.40      # variação do tempo de atendimento entre pessoas
P_COMPLEXO = 0.08           # 8% dos atendimentos são casos complexos...
FATOR_COMPLEXO = 2.2        # ...e duram 2,2x mais
SD_RITMO_DIA = 0.12         # o ritmo do atendente muda de um dia para o outro (desvio da lognormal)


def _dias_uteis(inicio, n):
    d, dias = inicio, []
    while len(dias) < n:
        if d.weekday() < 5:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def simular(dias=DIAS_UTEIS, seed=SEED, data_inicial=DATA_INICIAL, fuso_s=FUSO_PADRAO_S):
    """Devolve a lista de eventos [("CHEGADA"|"CONCLUSAO", t_epoch_s), ...] da simulação."""
    rng = np.random.default_rng(seed)
    tz = timezone(timedelta(seconds=fuso_s))
    eventos = []
    ultima_conclusao = -math.inf
    for dia in _dias_uteis(data_inicial, dias):
        meia_noite = datetime(dia.year, dia.month, dia.day, tzinfo=tz).timestamp()
        ritmo = float(rng.lognormal(0.0, SD_RITMO_DIA))
        chegadas = []
        for h, taxa in TAXA_CHEGADA_POR_HORA.items():
            n = int(rng.poisson(taxa))
            chegadas += list(meia_noite + h * 3600 + rng.uniform(0, 3600, n))
        for t_cheg in sorted(chegadas):
            inicio = max(t_cheg, ultima_conclusao)
            h_ini = min(max(int(hora_do_dia(inicio, fuso_s)), 8), 17)
            mediana_s = MEDIANA_ATENDIMENTO_MIN[h_ini] * 60 * ritmo
            dur = float(rng.lognormal(math.log(mediana_s), SIGMA_LOGNORMAL))
            if rng.random() < P_COMPLEXO:
                dur *= FATOR_COMPLEXO
            ultima_conclusao = inicio + dur
            eventos.append(("CHEGADA", t_cheg))
            eventos.append(("CONCLUSAO", ultima_conclusao))
    return eventos


def gerar_arquivos(pasta="dados", seed=SEED, dias=DIAS_UTEIS):
    os.makedirs(pasta, exist_ok=True)
    linhas = eventos_para_dataset(simular(dias=dias, seed=seed), origem="SIMULADO")
    caminho_csv = os.path.join(pasta, "dados_simulados.csv")
    with open(caminho_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, lineterminator="\n")
        w.writeheader()
        for l in linhas:
            w.writerow({k: ("" if v is None else v) for k, v in l.items()})
    meta = {
        "AVISO": "DADOS SINTETICOS (SIMULADOS). Nao sao medicoes de um atendimento real.",
        "gerado_por": "simulador.py",
        "seed": seed,
        "dias_uteis": dias,
        "data_inicial": DATA_INICIAL.isoformat(),
        "linhas": len(linhas),
        "taxa_chegada_por_hora": TAXA_CHEGADA_POR_HORA,
        "mediana_atendimento_min_por_hora": MEDIANA_ATENDIMENTO_MIN,
        "sigma_lognormal": SIGMA_LOGNORMAL,
        "prob_atendimento_complexo": P_COMPLEXO,
        "fator_atendimento_complexo": FATOR_COMPLEXO,
        "desvio_ritmo_do_dia": SD_RITMO_DIA,
        "colunas": COLUNAS,
    }
    with open(os.path.join(pasta, "dados_simulados.meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return caminho_csv, len(linhas)


if __name__ == "__main__":
    caminho, n = gerar_arquivos()
    print(f"{n} linhas SIMULADAS gravadas em {caminho}")
