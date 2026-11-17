"""Estimador de tempo de espera: convencional x regressão linear (IA).

Roda SEM numpy/sklearn: o treino (treinar.py) grava os coeficientes em dados/modelo_regressao.json
e aqui basta uma soma ponderada — a mesma conta poderia rodar no ESP32 (y = w1*x1 + ... + b).

Entradas do estimador (todas disponíveis no momento da chegada):
  pessoas_a_frente              fila atual
  media_atendimento_recente_s   média móvel dos últimos atendimentos (None se ainda não há dados)
  hora_do_dia                   hora decimal (ex.: 11.5)

Regra de domínio (vale para os dois métodos): sem ninguém à frente, a espera é 0.
"""
import json
import os
import sys

CAMINHO_MODELO_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados", "modelo_regressao.json")

# Atributos que o modelo sabe calcular a partir das entradas
FUNCOES_ATRIBUTO = {
    "pessoas_a_frente": lambda n, media, hora: float(n),
    "media_atendimento_recente_s": lambda n, media, hora: float(media),
    "pessoas_x_media": lambda n, media, hora: float(n) * float(media),
    "hora_do_dia": lambda n, media, hora: float(hora),
}


def montar_atributos(nomes, pessoas_a_frente, media_s, hora):
    return [FUNCOES_ATRIBUTO[nome](pessoas_a_frente, media_s, hora) for nome in nomes]


class ModeloEspera:
    def __init__(self, atributos, coeficientes, intercepto, media_historica_s, info=None):
        if len(atributos) != len(coeficientes):
            raise ValueError("atributos e coeficientes precisam ter o mesmo tamanho")
        for nome in atributos:
            if nome not in FUNCOES_ATRIBUTO:
                raise ValueError(f"atributo desconhecido: {nome}")
        self.atributos = list(atributos)
        self.coeficientes = [float(c) for c in coeficientes]
        self.intercepto = float(intercepto)
        self.media_historica_s = float(media_historica_s)
        self.info = info or {}

    # ---- persistência -----------------------------------------------------
    @classmethod
    def carregar(cls, caminho=CAMINHO_MODELO_PADRAO):
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        return cls(d["atributos"], d["coeficientes"], d["intercepto"], d["media_historica_s"], d.get("info"))

    def para_dict(self):
        return {
            "atributos": self.atributos,
            "coeficientes": self.coeficientes,
            "intercepto": self.intercepto,
            "media_historica_s": self.media_historica_s,
            "info": self.info,
        }

    # ---- estimativas ------------------------------------------------------
    def prever_convencional(self, pessoas_a_frente):
        """Estimativa convencional: pessoas à frente x tempo médio histórico de atendimento."""
        return max(0, pessoas_a_frente) * self.media_historica_s

    def prever_ia(self, pessoas_a_frente, media_s, hora):
        """Regressão linear. Sem média recente disponível, recorre à estimativa convencional."""
        if pessoas_a_frente <= 0:
            return 0.0
        if media_s is None:
            return self.prever_convencional(pessoas_a_frente)
        x = montar_atributos(self.atributos, pessoas_a_frente, media_s, hora)
        y = self.intercepto + sum(c * v for c, v in zip(self.coeficientes, x))
        return max(0.0, y)   # espera nunca é negativa

    def estimar(self, pessoas_a_frente, media_s=None, hora=12.0):
        return {
            "pessoas_a_frente": pessoas_a_frente,
            "convencional_s": self.prever_convencional(pessoas_a_frente),
            "ia_s": self.prever_ia(pessoas_a_frente, media_s, hora),
            "ia_usou_fallback": media_s is None and pessoas_a_frente > 0,
        }


def _demo(modelo):
    """Mostra a estimativa se atualizando conforme a fila muda (apoia o Teste 4 do enunciado)."""
    print("Estimativa de espera para QUEM CHEGAR AGORA (media recente = 200 s, 11h30)\n")
    print(f"{'evento':<22}{'fila':>5}{'convencional':>15}{'IA':>10}")
    fila = 0
    passos = ["inicio"] + ["chegada"] * 4 + ["conclusao"] * 2 + ["chegada"] * 2 + ["conclusao"] * 5
    for p in passos:
        if p == "chegada":
            fila += 1
        elif p == "conclusao":
            if fila == 0:
                print(f"{'conclusao (recusada)':<22}{fila:>5}{'-':>15}{'-':>10}")
                continue
            fila -= 1
        e = modelo.estimar(fila, 200.0, 11.5)
        print(f"{p:<22}{fila:>5}{e['convencional_s']/60:>12.1f} min{e['ia_s']/60:>7.1f} min")


if __name__ == "__main__":
    m = ModeloEspera.carregar()
    if "--demo" in sys.argv:
        _demo(m)
    else:
        print(json.dumps(m.para_dict(), ensure_ascii=False, indent=2))
