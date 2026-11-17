"""Treina a regressão linear e compara com a estimativa convencional.

  python treinar.py                       (usa dados/dados_simulados.csv)
  python treinar.py --csv outro.csv       (mesmo formato; ex.: eventos REAIS convertidos na Etapa 4)

Divisão CRONOLÓGICA (primeiros 70% dos dias treinam, últimos 30% testam): o modelo nunca vê o futuro.
Saídas em dados/: modelo_regressao.json, resultados_comparacao.json, comparacao_modelos.png
"""
import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from previsao import ModeloEspera, montar_atributos

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados")
FRACAO_TREINO = 0.70
LIMITE_ACERTO_S = 120          # "acertou" = erro de até 2 minutos

# Conjuntos de atributos candidatos. A = só os atributos brutos; B = A + (pessoas x média), o termo "físico" da espera.
# A escolha entre eles é feita por validação cruzada SÓ nos dias de treino (o teste não participa da escolha).
CANDIDATOS = {
    "A_atributos_brutos": ["pessoas_a_frente", "media_atendimento_recente_s", "hora_do_dia"],
    "B_com_pessoas_x_media": ["pessoas_a_frente", "media_atendimento_recente_s", "pessoas_x_media", "hora_do_dia"],
}
EMPATE_RELATIVO = 0.01         # diferença de RMSE menor que 1% = empate -> fica o modelo mais simples


def metricas(real, previsto):
    real, previsto = np.asarray(real, float), np.asarray(previsto, float)
    erro = previsto - real
    ss_res = float(np.sum(erro ** 2))
    ss_tot = float(np.sum((real - real.mean()) ** 2))
    return {
        "MAE_s": float(np.mean(np.abs(erro))),
        "RMSE_s": float(np.sqrt(np.mean(erro ** 2))),
        "R2": 1 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        "vies_s": float(np.mean(erro)),
        "acerto_ate_2min_pct": float(100 * np.mean(np.abs(erro) <= LIMITE_ACERTO_S)),
    }


def carregar_dados(caminho_csv):
    d = pd.read_csv(caminho_csv)
    d = d.dropna(subset=["media_atendimento_recente_s"]).copy()          # início do histórico, sem média ainda
    return d.sort_values(["data", "hora_do_dia"]).reset_index(drop=True)


def dividir_cronologicamente(d):
    dias = sorted(d["data"].unique())
    corte = int(round(len(dias) * FRACAO_TREINO))
    treino = d[d["data"].isin(dias[:corte])].copy()
    teste = d[d["data"].isin(dias[corte:])].copy()
    return treino, teste, dias[:corte], dias[corte:]


def matriz(d, nomes):
    return np.array([montar_atributos(nomes, r.pessoas_a_frente, r.media_atendimento_recente_s, r.hora_do_dia)
                     for r in d.itertuples()])


def treinar_regressao(treino, nomes):
    """Treina só com linhas em que existe espera para prever (pessoas_a_frente >= 1)."""
    t = treino[treino["pessoas_a_frente"] >= 1]
    lr = LinearRegression().fit(matriz(t, nomes), t["espera_real_s"].values)
    return lr


def validacao_cruzada_cronologica(treino, n_blocos=5):
    """Janela expansiva por dias: treina nos primeiros k blocos de dias e valida no bloco seguinte."""
    dias = sorted(treino["data"].unique())
    blocos = np.array_split(np.array(dias), n_blocos)
    cv = {}
    for rotulo, nomes in CANDIDATOS.items():
        rmses, maes = [], []
        for k in range(1, n_blocos):
            tr = treino[treino["data"].isin(np.concatenate(blocos[:k]))]
            va = treino[treino["data"].isin(blocos[k]) & (treino["pessoas_a_frente"] >= 1)]
            lr = treinar_regressao(tr, nomes)
            erro = np.maximum(lr.predict(matriz(va, nomes)), 0) - va["espera_real_s"].values
            rmses.append(float(np.sqrt(np.mean(erro ** 2))))
            maes.append(float(np.mean(np.abs(erro))))
        cv[rotulo] = {"RMSE_s_medio": float(np.mean(rmses)), "MAE_s_medio": float(np.mean(maes)), "folds": n_blocos - 1}
    ordem = list(CANDIDATOS)                      # do mais simples para o mais complexo
    melhor = min(ordem, key=lambda r: cv[r]["RMSE_s_medio"])
    escolhido = melhor
    for r in ordem:                               # empate técnico => o mais simples
        if cv[r]["RMSE_s_medio"] <= cv[melhor]["RMSE_s_medio"] * (1 + EMPATE_RELATIVO):
            escolhido = r
            break
    return cv, escolhido


def prever_todas(teste, nomes, lr, media_historica_s):
    n = teste["pessoas_a_frente"].values.astype(float)
    conv = n * media_historica_s
    recente = n * teste["media_atendimento_recente_s"].values
    ia = lr.predict(matriz(teste, nomes))
    ia = np.where(n <= 0, 0.0, np.maximum(ia, 0.0))
    return conv, recente, ia


def comparar(caminho_csv, pasta_saida=PASTA, grafico=True):
    d = carregar_dados(caminho_csv)
    origem = sorted(d["origem"].unique())
    treino, teste, dias_tr, dias_te = dividir_cronologicamente(d)
    media_hist = float(treino["atendimento_real_s"].mean())

    cv, escolhido = validacao_cruzada_cronologica(treino)
    resultados = {}
    modelos = {}
    for rotulo, nomes in CANDIDATOS.items():
        lr = treinar_regressao(treino, nomes)
        modelos[rotulo] = (nomes, lr)
        conv, recente, ia = prever_todas(teste, nomes, lr, media_hist)
        real = teste["espera_real_s"].values
        com_fila = teste["pessoas_a_frente"].values >= 1
        resultados[rotulo] = {
            "todas_as_linhas": {"convencional": metricas(real, conv), "convencional_media_recente": metricas(real, recente),
                                "ia_regressao_linear": metricas(real, ia)},
            "so_com_fila_ge_1": {"convencional": metricas(real[com_fila], conv[com_fila]),
                                 "convencional_media_recente": metricas(real[com_fila], recente[com_fila]),
                                 "ia_regressao_linear": metricas(real[com_fila], ia[com_fila])},
        }

    nomes_f, lr_f = modelos[escolhido]
    conv, recente, ia = prever_todas(teste, nomes_f, lr_f, media_hist)

    info = {
        "origem_dos_dados": origem,
        "AVISO": "Treinado com dados SIMULADOS" if origem == ["SIMULADO"] else "Ver origem_dos_dados",
        "linhas_treino": int(len(treino)), "linhas_teste": int(len(teste)),
        "dias_treino": len(dias_tr), "dias_teste": len(dias_te),
        "treinado_em_linhas_com_fila_ge_1": int((treino["pessoas_a_frente"] >= 1).sum()),
        "regra": "pessoas_a_frente == 0 => espera 0; previsoes negativas viram 0",
        "modelo_escolhido": escolhido,
        "validacao_cruzada_treino": cv,
    }
    modelo = ModeloEspera(nomes_f, lr_f.coef_, lr_f.intercept_, media_hist, info)
    os.makedirs(pasta_saida, exist_ok=True)
    with open(os.path.join(pasta_saida, "modelo_regressao.json"), "w", encoding="utf-8") as f:
        json.dump(modelo.para_dict(), f, ensure_ascii=False, indent=2)
    # erro por faixa de fila (modelo escolhido, conjunto de teste)
    n_t = teste["pessoas_a_frente"].values
    real_t = teste["espera_real_s"].values
    faixas = {}
    for nome, lo, hi in (("1-2 pessoas", 1, 2), ("3-5 pessoas", 3, 5), ("6 ou mais", 6, 10 ** 6)):
        m = (n_t >= lo) & (n_t <= hi)
        if m.sum():
            faixas[nome] = {"linhas": int(m.sum()), "convencional": metricas(real_t[m], conv[m]),
                            "ia_regressao_linear": metricas(real_t[m], ia[m])}
    saida = {"info": info, "media_historica_s": media_hist, "limite_acerto_s": LIMITE_ACERTO_S,
             "modelo_escolhido": escolhido, "resultados": resultados, "por_faixa_de_fila": faixas}
    with open(os.path.join(pasta_saida, "resultados_comparacao.json"), "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    if grafico:
        desenhar(teste, conv, recente, ia, resultados[escolhido]["so_com_fila_ge_1"],
                 origem, os.path.join(pasta_saida, "comparacao_modelos.png"))
    return saida, modelo


def desenhar(teste, conv, recente, ia, met, origem, caminho):
    real_min = teste["espera_real_s"].values / 60
    com_fila = teste["pessoas_a_frente"].values >= 1
    rng = np.random.default_rng(0)
    idx = np.flatnonzero(com_fila)
    if len(idx) > 700:
        idx = rng.choice(idx, 700, replace=False)
    lim = float(max(real_min[idx].max(), conv[idx].max() / 60, ia[idx].max() / 60)) * 1.05

    fig, ax = plt.subplots(1, 3, figsize=(17, 5.4), gridspec_kw={"width_ratios": [1, 1, 1.05]})
    rotulo_dados = "DADOS SIMULADOS" if origem == ["SIMULADO"] else "dados: " + ", ".join(origem)
    fig.suptitle(f"Estimativa de espera: convencional x regressão linear — conjunto de TESTE ({rotulo_dados}); só linhas com fila ≥ 1",
                 fontsize=12.5, fontweight="bold")
    for a, prev, titulo, cor, chave in ((ax[0], conv, "Convencional\n(pessoas à frente × média histórica)", "#c0392b", "convencional"),
                                        (ax[1], ia, "IA: regressão linear", "#1f77b4", "ia_regressao_linear")):
        a.scatter(real_min[idx], prev[idx] / 60, s=10, alpha=0.35, color=cor)
        a.plot([0, lim], [0, lim], "k--", lw=1, label="previsão perfeita")
        a.set_xlim(0, lim); a.set_ylim(0, lim)
        a.set_xlabel("espera real (min)"); a.set_ylabel("espera prevista (min)")
        m = met[chave]
        a.set_title(f"{titulo}\nMAE {m['MAE_s']/60:.1f} min · RMSE {m['RMSE_s']/60:.1f} min · R² {m['R2']:.2f}", fontsize=10.5)
        a.legend(loc="upper left", fontsize=8)
        a.grid(alpha=0.25)
    nomes = ["Convencional\n(média histórica)", "Convencional\n(média recente)", "IA: regressão\nlinear"]
    chaves = ["convencional", "convencional_media_recente", "ia_regressao_linear"]
    x = np.arange(3); w = 0.38
    mae = [met[k]["MAE_s"] / 60 for k in chaves]
    rmse = [met[k]["RMSE_s"] / 60 for k in chaves]
    b1 = ax[2].bar(x - w / 2, mae, w, label="MAE", color="#7f8c8d")
    b2 = ax[2].bar(x + w / 2, rmse, w, label="RMSE", color="#34495e")
    for b in list(b1) + list(b2):
        ax[2].text(b.get_x() + b.get_width() / 2, b.get_height() + 0.1, f"{b.get_height():.1f}", ha="center", fontsize=9)
    ax[2].set_xticks(x); ax[2].set_xticklabels(nomes, fontsize=9)
    ax[2].set_ylabel("erro (min) — menor é melhor"); ax[2].set_title("Erro nos mesmos dados de teste", fontsize=10.5)
    ax[2].legend(); ax[2].grid(axis="y", alpha=0.25)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(caminho, dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(PASTA, "dados_simulados.csv"))
    args = ap.parse_args()
    saida, modelo = comparar(args.csv)
    print(json.dumps(saida["info"], ensure_ascii=False, indent=2))
    print(f"\nMédia histórica de atendimento (treino): {saida['media_historica_s']:.1f} s")
    for rotulo, r in saida["resultados"].items():
        print(f"\n=== Modelo {rotulo} ===")
        for sub, nome in (("so_com_fila_ge_1", "SÓ COM FILA >= 1"), ("todas_as_linhas", "TODAS AS LINHAS")):
            print(f"-- {nome}")
            for k, m in r[sub].items():
                print(f"   {k:<28} MAE {m['MAE_s']/60:5.2f} min | RMSE {m['RMSE_s']/60:5.2f} min | R2 {m['R2']:6.3f} | vies {m['vies_s']/60:6.2f} min | <=2min {m['acerto_ate_2min_pct']:5.1f}%")
    print("\nValidação cruzada (só treino):", {k: round(v["RMSE_s_medio"] / 60, 3) for k, v in saida["info"]["validacao_cruzada_treino"].items()}, "(RMSE em min)")
    print("Modelo escolhido:", saida["modelo_escolhido"])
    print("Coeficientes:", dict(zip(modelo.atributos, [round(c, 4) for c in modelo.coeficientes])), "| intercepto", round(modelo.intercepto, 2))
    print("\nErro por faixa de fila (teste):")
    for nome, r in saida["por_faixa_de_fila"].items():
        c, i = r["convencional"], r["ia_regressao_linear"]
        print(f"   {nome:<12} ({r['linhas']:>3} linhas)  MAE conv {c['MAE_s']/60:5.2f} | IA {i['MAE_s']/60:5.2f} min   viés conv {c['vies_s']/60:5.2f} | IA {i['vies_s']/60:5.2f} min")
