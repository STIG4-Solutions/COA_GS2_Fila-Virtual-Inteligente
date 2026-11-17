# Backend e painel (Etapa 4)

Projeto **Citizen Assist AI** · Global Solution 2026.2 · 1CC-FEV

Recebe os eventos do ESP32 por **MQTT**, guarda o histórico em **SQLite**, calcula as duas estimativas de espera
(convencional e IA, da Etapa 3) e mostra tudo num **painel no navegador** que se atualiza a cada 2 segundos.

```
ESP32 (Wokwi) --Wi-Fi/MQTT--> broker público --MQTT--> backend Flask --HTTP/JSON--> navegador
                                                          |-- SQLite (log)
                                                          '-- modelo de previsão (Etapa 3)
```

## Como rodar (Windows, Linux ou macOS)

Dentro da pasta `backend`:

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Abra **http://127.0.0.1:5000**. Para parar, `Ctrl+C`. (Se o PowerShell bloquear o `activate`, use o CMD.)

O backend precisa do arquivo `previsao/dados/modelo_regressao.json` (já vem na pasta; para refazer, veja a Etapa 3).

### Passo a passo com o Wokwi

1. **Escolham um tópico único** (o broker é público e aberto). No `sketch.ino`, troque **só o texto entre aspas** da linha
   `const char* TOPICO_BASE = "...";` (ex.: `"fiap1ccfev/citizenassist/gs2026-SEUGRUPO"`). O nome `TOPICO_BASE` não muda.
   Use **o mesmo valor** no backend:
   `set FILA_TOPICO_BASE=fiap1ccfev/citizenassist/gs2026-SEUGRUPO` (CMD) ou `$env:FILA_TOPICO_BASE="..."` (PowerShell).
2. Inicie o backend (`python app.py`) e abra o painel.
3. No Wokwi, **substitua os três arquivos** pelas versões atuais: `sketch.ino`, **`fila_core.h`** (a versão mudou) e
   `libraries.txt` (com `PubSubClient`). Se existir um `modelo_coef.h` no projeto, **apague-o**: não é mais usado.
   Depois clique em **Start**.
4. Aguarde no Serial: `Hora sincronizada via NTP` e `MQTT conectado ao broker`.
5. Clique em Chegada/Conclusão no simulador e acompanhe o painel.

### Sem o Wokwi (ensaio ou vídeo com roteiro previsível)

```bash
python ferramentas/simulador_esp32.py                       # roteiro de demonstração
python ferramentas/simulador_esp32.py --cenario aleatorio --eventos 40 --ritmo 1
```

O simulador publica no mesmo formato do firmware (**não é o firmware**; serve para testar o backend e o painel).

## Mensagens MQTT

| Tópico | Conteúdo | Retido? |
|---|---|---|
| `<base>/evento` | JSON de cada evento (tabela abaixo) | Sim (quem se conecta depois já recebe o último) |
| `<base>/status` | `online` ao conectar; `offline` pelo *last will* se o ESP32 sumir | Sim |

Exemplo de evento (192 bytes típicos, máximo teórico 246 B; buffer MQTT de 512 B):

```json
{"sessao":"a1b2c3d4","seq":17,"tipo":"CONCLUSAO","valido":true,"fila":0,"atendidos":6,"hora_s":1794361680,
 "hora_real":true,"uptime_ms":35236,"espera_ms":0,"atendimento_ms":557,"media_ms":3426}
```

| Campo | Significado |
|---|---|
| `sessao` | identifica cada execução (boot) do firmware |
| `seq` | numeração do evento na sessão (conta **também os eventos não enviados**, revelando perdas) |
| `tipo` | `CHEGADA`, `CONCLUSAO`, `REJEITADA_VAZIA` ou `REJEITADA_CHEIA` |
| `valido` | `false` nas operações recusadas |
| `fila`, `atendidos` | estado do ESP32 depois do evento (o ESP32 é a fonte da verdade) |
| `hora_s`, `hora_real` | hora Unix (NTP) ou segundos desde o boot |
| `uptime_ms` | tempo desde o boot, em ms |
| `espera_ms`, `atendimento_ms` | tempos reais da pessoa concluída (0 nos demais eventos) |
| `media_ms` | média móvel dos últimos 10 atendimentos |

Como o PubSubClient só publica com QoS 0, uma mensagem pode se perder. O backend **não depende do histórico
inteiro**: ele usa `fila` e `atendidos` do último evento, então se recupera na mensagem seguinte. Perdas aparecem
em "Eventos perdidos" no painel.

## API

| Rota | Resposta |
|---|---|
| `GET /` | o painel |
| `GET /api/status` | fila, espera estimada (IA e convencional), atendidos, recusadas, estado do ESP32 e do MQTT |
| `GET /api/eventos?limite=20` | últimos eventos, do mais novo ao mais antigo (máx. 200) |
| `GET /api/saude` | broker, tópico e informações do modelo |

## O que o painel mostra

- **Pessoas na fila**, **tempo estimado de espera** (IA, com o método convencional ao lado), **atendimentos concluídos** e
  **operações recusadas**;
- estado do ESP32 (online/offline), do servidor ↔ broker e contadores de eventos recebidos, perdidos e descartados;
- gráfico da fila nos últimos eventos e tabela dos últimos eventos;
- aviso quando a IA usa o método convencional (ainda sem média recente de atendimento).

Acessibilidade: texto em português (`lang="pt-BR"`), regiões com `aria-live`, tabela com cabeçalhos, estado
indicado por texto além da cor, tema claro/escuro e layout que se adapta ao celular.

## Configuração (variáveis de ambiente)

| Variável | Padrão |
|---|---|
| `FILA_MQTT_BROKER` / `FILA_MQTT_PORTA` | `broker.hivemq.com` / `1883` |
| `FILA_TOPICO_BASE` | `fiap1ccfev/citizenassist/gs2026-x7q9` |
| `FILA_BANCO` | `dados/fila.db` |
| `FILA_MODELO` | `previsao/dados/modelo_regressao.json` |
| `FILA_HTTP_HOST` / `FILA_HTTP_PORTA` | `127.0.0.1` / `5000` (use `0.0.0.0` para abrir na rede local) |

## Testes

```bash
python -m unittest discover -s tests -v          # 30 testes (3 de ponta a ponta são pulados sem o amqtt)
```

- `test_backend.py`: validação das mensagens, estado, duplicadas/atrasadas/perdidas, reinício, estimativas, API e o
  **contrato com o firmware** (reproduz as mensagens exatas que o `sketch.ino` publica na simulação do PC).
- `test_ferramentas.py`: simulador do ESP32 e exportação do dataset.
- `test_e2e_mqtt.py` (opcional, `pip install amqtt`): sobe um **broker MQTT real** local e confere chegada dos eventos,
  mensagens retidas e *last will*.
- `painel.test.js` (opcional, `npm install jsdom`): testa o painel num navegador simulado
  (`NODE_PATH=... node tests/painel.test.js`).

## Retreinar com dados reais

```bash
python ferramentas/exportar_dataset.py                        # SQLite -> previsao/dados/dados_reais.csv (origem = REAL)
cd previsao && python treinar.py --csv dados/dados_reais.csv  # precisa de pelo menos alguns dias de dados
```

## Segurança e limitações

- O broker público **não tem senha nem criptografia**: qualquer pessoa que descubra o tópico pode ler ou publicar nele.
  Por isso o tópico deve ser único, e o backend **valida cada mensagem** (tipo, faixa e coerência dos campos) e descarta o resto.
  Em produção: broker próprio com usuário/senha e TLS.
- O servidor escuta só em `127.0.0.1` por padrão (o Flask embutido é para desenvolvimento/demonstração).
- Sem o broker, o ESP32 continua contando e guardando o log local, mas esses eventos não chegam ao painel.
- A previsão usa o modelo treinado com **dados simulados** (o painel avisa).
