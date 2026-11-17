"""Do histórico de eventos ao dataset de treino.

Os eventos têm o mesmo significado do firmware (fila_core.h, Etapa 2):
  - atendimento em ordem de chegada (FIFO) com um único atendente;
  - início do atendimento = o que ocorrer por último entre a chegada da pessoa e a conclusão anterior;
  - espera = início - chegada;  atendimento = conclusão - início;
  - média recente = média móvel dos últimos 10 atendimentos (JANELA_MEDIA).

Esta função serve tanto para os dados SIMULADOS (simulador.py) quanto, na Etapa 4,
para os eventos REAIS publicados pelo ESP32. Assim o treino usa a mesma lógica nos dois casos.
"""
from collections import deque
from datetime import datetime, timedelta, timezone

JANELA_MEDIA = 10                 # igual a fila::JANELA_MEDIA no firmware
FUSO_PADRAO_S = -3 * 3600         # São Paulo (UTC-3)

COLUNAS = [
    "origem",                         # SIMULADO ou REAL
    "data",
    "hora_chegada",
    "hora_do_dia",                    # hora decimal da chegada (ex.: 11.5 = 11h30)
    "pessoas_a_frente",               # fila no instante da chegada (antes de entrar)
    "media_atendimento_recente_s",    # média móvel dos últimos atendimentos, em segundos (vazio no início)
    "espera_real_s",                  # ALVO: tempo esperando até o início do atendimento
    "atendimento_real_s",
]


def hora_do_dia(t_s, fuso_s=FUSO_PADRAO_S):
    return ((t_s + fuso_s) % 86400) / 3600.0


def eventos_para_dataset(eventos, origem, fuso_s=FUSO_PADRAO_S):
    """eventos: iterável de (tipo, t_s), tipo em {"CHEGADA", "CONCLUSAO"}, t_s = segundos (epoch).

    Conclusões com a fila vazia são ignoradas (no firmware elas são recusadas).
    Devolve uma lista de dicts (uma linha por pessoa atendida) com as colunas de COLUNAS.
    """
    fila = deque()                    # (t_chegada, pessoas_a_frente, media_recente)
    janela = deque(maxlen=JANELA_MEDIA)
    ultima_conclusao = None
    linhas = []
    tz = timezone(timedelta(seconds=fuso_s))

    for tipo, t in sorted(eventos, key=lambda e: e[1]):
        if tipo == "CHEGADA":
            media = (sum(janela) / len(janela)) if janela else None
            fila.append((t, len(fila), media))
        elif tipo == "CONCLUSAO":
            if not fila:
                continue
            chegou, a_frente, media = fila.popleft()
            inicio = chegou
            if ultima_conclusao is not None and ultima_conclusao > chegou:
                inicio = ultima_conclusao
            espera = inicio - chegou
            atendimento = t - inicio
            ultima_conclusao = t
            janela.append(atendimento)
            dt = datetime.fromtimestamp(chegou, tz=tz)
            linhas.append({
                "origem": origem,
                "data": dt.strftime("%Y-%m-%d"),
                "hora_chegada": dt.strftime("%H:%M:%S"),
                "hora_do_dia": round(hora_do_dia(chegou, fuso_s), 4),
                "pessoas_a_frente": a_frente,
                "media_atendimento_recente_s": None if media is None else round(media, 3),
                "espera_real_s": round(espera, 3),
                "atendimento_real_s": round(atendimento, 3),
            })
        else:
            raise ValueError(f"tipo de evento desconhecido: {tipo!r}")
    return linhas
