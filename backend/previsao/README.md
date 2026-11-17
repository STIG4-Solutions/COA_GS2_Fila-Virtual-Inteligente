# Previsão de espera (Etapa 3)

Projeto **Citizen Assist AI** · Global Solution 2026.2 · 1CC-FEV

Compara dois jeitos de estimar **quanto tempo uma pessoa que chega agora vai esperar**:

1. **Convencional**: `pessoas à frente × tempo médio histórico de atendimento`
2. **IA (regressão linear)**: `espera = w1·pessoas_à_frente + w2·média_recente + w3·hora_do_dia + b`

> ## ⚠️ DADOS SIMULADOS
> Todos os resultados abaixo vêm de **dados sintéticos** gerados por `simulador.py` (hipóteses inventadas:
> picos de movimento, atendimento mais lento no almoço, casos complexos, ritmo diferente a cada dia).
> Não são medições de um atendimento real. Cada linha do CSV tem `origem = SIMULADO`, e há um
> `dados_simulados.meta.json` com todos os parâmetros. Ao treinar com eventos reais (Etapa 4), a coluna vira `REAL`.

## Arquivos

| Arquivo | Função |
|---|---|
| `dataset.py` | Transforma eventos (chegada/conclusão) nas colunas de treino, **com as mesmas regras do firmware** |
| `simulador.py` | Gera 40 dias úteis de dados simulados (3.703 pessoas atendidas) |
| `treinar.py` | Treina, compara, grava modelo, métricas e gráfico |
| `previsao.py` | Estimador usado pelo backend (Python puro, sem scikit-learn); `--demo` mostra a estimativa mudando com a fila |
| `dados/` | `dados_simulados.csv`, `.meta.json`, `modelo_regressao.json`, `resultados_comparacao.json`, `comparacao_modelos.png` |
| `tests/` | 23 testes automáticos |

## Como rodar

```bash
pip install -r requirements.txt
python simulador.py            # gera dados/dados_simulados.csv (+ meta.json)
python treinar.py              # treina, compara e grava modelo + gráfico
python previsao.py --demo      # estimativa se atualizando a cada chegada/conclusão
python -m unittest discover -s tests -v
```

Tudo é determinístico (semente 2026): rodar de novo reproduz os mesmos números.

## Atributos e alvo

| Coluna | Significado |
|---|---|
| `pessoas_a_frente` | fila no instante da chegada (antes de entrar) |
| `media_atendimento_recente_s` | média móvel dos últimos 10 atendimentos (a mesma do firmware) |
| `hora_do_dia` | hora decimal da chegada (11,5 = 11h30) |
| **`espera_real_s`** (alvo) | início do atendimento − chegada (definição da Etapa 2) |

Regra de domínio, aplicada aos dois métodos: **sem ninguém à frente, a espera é 0**; previsões negativas viram 0.
Sem média recente disponível (início do histórico), a IA usa a estimativa convencional.

## Como a avaliação foi feita

- **Divisão cronológica**: os 28 primeiros dias treinam, os 12 últimos testam. O modelo nunca vê o futuro.
- O modelo foi treinado só com linhas em que há espera para prever (fila ≥ 1).
- Dois conjuntos de atributos foram candidatos (A: brutos; B: A + `pessoas × média`). A escolha foi feita por
  **validação cruzada só nos dias de treino**: empate técnico (RMSE 6,26 × 6,31 min), então ficou o mais simples (A).
  O conjunto de teste não participou da escolha.
- Média histórica usada no convencional: **227,8 s** (média dos atendimentos nos dias de treino).

## Resultados (conjunto de teste, linhas com fila ≥ 1)

| Método | MAE | RMSE | R² | Viés | Acertos ≤ 2 min |
|---|---|---|---|---|---|
| Convencional (média histórica) | 2,93 min | **3,96 min** | **0,799** | +0,70 min | 41,5% |
| Convencional (média recente × fila) *(referência extra)* | 3,43 min | 4,98 min | 0,682 | +1,59 min | 43,8% |
| **IA: regressão linear** | **2,70 min** | 4,02 min | 0,793 | **+0,09 min** | **55,0%** |

Gráfico: `dados/comparacao_modelos.png`. Considerando **todas** as linhas (incluindo fila vazia, onde a espera é 0):
MAE 1,73 × 1,59 min, RMSE 3,04 × 3,09 min, R² 0,848 × 0,843 (convencional × IA).

### O que isso significa (leitura honesta)

- A IA **não vence em tudo**. Ela erra menos **na média** (MAE −8%), praticamente **elimina o viés** do convencional
  e acerta dentro de 2 minutos com mais frequência (55% × 41,5%). Mas **RMSE e R² ficam empatados** (o convencional é
  até um pouco melhor): nos erros grandes, a regressão linear não ajuda.
- Por faixa de fila: a IA é melhor com 1–2 pessoas (MAE 2,03 × 2,41 min), perde um pouco com 3–5 (4,13 × 3,87) e fica
  parecida com 6 ou mais (5,21 × 5,40), mas com viés de +4,3 min (só 43 linhas, estimativa instável).
- A média móvel recente **sozinha** é pior que a média histórica: com 10 atendimentos ela é ruidosa. Por isso o ganho
  da IA vem de corrigir o viés e usar a hora do dia, não de "adivinhar" o ritmo atual.
- Grande parte do erro é **irredutível**: depende da duração *futura* dos atendimentos, que é aleatória.
  Com estes atributos, nenhum modelo elimina isso.
- Estes números dependem das hipóteses do simulador. **Com dados reais podem mudar**; por isso o pipeline aceita
  `python treinar.py --csv eventos_reais.csv` (mesmo formato).

## Teste 4 do enunciado (atualização da estimativa)

`python previsao.py --demo` mostra a estimativa recalculada a cada evento (média recente = 200 s, 11h30):

```
evento                 fila   convencional        IA
inicio                    0         0.0 min    0.0 min
chegada                   1         3.8 min    1.9 min
chegada                   2         7.6 min    7.0 min
chegada                   3        11.4 min   12.2 min
chegada                   4        15.2 min   17.3 min
conclusao                 3        11.4 min   12.2 min
...
conclusao (recusada)      0              -         -
```

No painel (Etapa 4), essa mesma conta rodará no backend a cada evento recebido do ESP32.

## Limitações

- Dados simulados; um único atendente e atendimento em ordem de chegada (premissas da Etapa 2).
- Modelo linear: não captura efeitos não lineares nem picos súbitos.
