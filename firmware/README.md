# Firmware da Fila Virtual (Etapas 2 e 4)

Projeto **Citizen Assist AI** · Global Solution 2026.2 · 1CC-FEV · Arquitetura e Organização de Computadores

ESP32 (simulado no Wokwi) com dois botões, LCD I2C, LEDs, buzzer e Monitor Serial.
Registra chegadas e conclusões, impede contagem negativa, guarda um log com horário e
calcula os tempos de espera e de atendimento (base da previsão da Etapa 3) e **publica cada evento por MQTT** (Etapa 4).

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `sketch.ino` | Programa do ESP32 (pinos, interrupções, LCD, LEDs, buzzer, Serial, hora via NTP) |
| `fila_core.h` | Núcleo da fila: FIFO, validação, log circular, média móvel e debounce. **Sem hardware**, por isso é testável no PC |
| `diagram.json` | Circuito do Wokwi (ESP32 + peças) |
| `libraries.txt` | Bibliotecas usadas no Wokwi (`LiquidCrystal I2C` e `PubSubClient`) |
| `test/` | Testes que rodam no computador (`bash test/run_tests.sh`) |

## Como rodar no Wokwi

1. Em [wokwi.com](https://wokwi.com), crie um projeto **ESP32** (Arduino).
2. Cole o conteúdo de `sketch.ino`, `diagram.json` e `libraries.txt` nas abas de mesmo nome.
3. Antes de iniciar, troque **só o texto entre aspas** de `const char* TOPICO_BASE = "...";` no `sketch.ino` por algo único do grupo
   (o broker é público) e use o mesmo valor no backend. O nome `TOPICO_BASE` não pode mudar.
4. Crie um arquivo novo chamado `fila_core.h` (botão **+** ao lado das abas) e cole o conteúdo.
5. Clique em **Start**. Abra o Monitor Serial para ver o log.

**Se atualizar de uma versão anterior**, o projeto tem 3 arquivos de código: substitua `sketch.ino` e `fila_core.h` e mantenha o `libraries.txt`. **Se existir um `modelo_coef.h` no projeto do Wokwi, apague-o** (não é mais usado). O `sketch.ino` confere a versão do `fila_core.h` e, se estiver desatualizado, a compilação mostra uma mensagem em português dizendo o que copiar.

Uso: clique nos botões, ou use as teclas **c** (Chegada) e **s** (Conclusão) com o diagrama em foco.
O Wokwi simula o ruído de contato dos botões (bounce), então o debounce é exercitado de verdade.

## Pinos

| Função | Pino |
|---|---|
| Botão Chegada | GPIO 18 (pull-up interno, interrupção na borda de descida) |
| Botão Conclusão | GPIO 19 (idem) |
| LCD I2C 16x2 (0x27) | SDA = GPIO 21 · SCL = GPIO 22. Linha 1: `Fila: 3`; linha 2: `Atendidos: 12` |
| LED verde (evento válido) | GPIO 26 |
| LED vermelho (evento inválido) | GPIO 27 |
| Buzzer | GPIO 25 |

## Regras da fila

- **Chegada**: entra no fim da FIFO (capacidade 100). Com a fila cheia, a chegada é recusada.
- **Conclusão**: sai a pessoa da frente. Com a fila vazia, a operação é **recusada**: o contador não muda,
  o LED vermelho acende, o buzzer apita duas vezes e o LCD mostra "Fila vazia!".
- Segurar o botão conta **uma** vez só; soltar nunca gera evento.
- Cada evento (aceito ou recusado) vai para o log circular (64 registros de 12 bytes) e para o Serial.

## Definições usadas nos tempos

Com um botão de conclusão só, o sistema assume **atendimento em ordem de chegada (FIFO) com um único atendente**:

- **início do atendimento** = o que ocorrer por último entre a chegada da pessoa e a conclusão da anterior;
- **espera** = início do atendimento − chegada;
- **atendimento** = conclusão − início do atendimento;
- **média de atendimento** = média móvel dos últimos 10 atendimentos.

## Roteiro dos testes do enunciado (Etapa 2)

| # | Situação | Como fazer no Wokwi | Resultado esperado |
|---|---|---|---|
| 1 | Chegada de novos cidadãos | Pressione Chegada 3 vezes | LCD: `Fila: 3` / `Atendidos: 0`; 3 linhas `CHEGADA`; LED verde pisca |
| 2 | Conclusão de atendimentos | Pressione Conclusão 2 vezes | LCD: `Fila: 1` / `Atendidos: 2`; linhas `CONCLUSAO` com espera, atendimento e média |
| 3 | Saída com fila vazia | Esvazie a fila e pressione Conclusão | `REJEITADA (fila vazia)`; fila continua 0; LED vermelho + buzzer + `Fila vazia!` no LCD |
| 4 | Atualização da estimativa | Aumente a fila com Chegada e diminua com Conclusão | A estimativa de espera do **painel** (backend) muda a cada evento; no ESP32, o LCD e o Serial mostram fila e atendidos |

Exemplo de saída do Monitor Serial:

```
[T+00:00:05] CHEGADA | fila=1 | atendidos=0
[T+00:00:06] CONCLUSAO | fila=0 | atendidos=1 | espera=0.0s | atendimento=2.0s | media=2.0s
[T+00:00:09] REJEITADA (fila vazia) | fila=0 | atendidos=1
[09/11/2026 22:54:02] CHEGADA | fila=1 | atendidos=1      <- depois que o NTP sincroniza
```

A **previsão de espera** (convencional × regressão linear) é calculada no **backend** e mostrada no painel (ver `../backend/README.md`).

## Testes no computador

```bash
bash test/run_tests.sh      # precisa de g++
```

- `test_fila_core.cpp`: testa o núcleo (chegadas, conclusões e tempos, fila vazia, fila cheia, log circular,
  estouro do `millis()`, média móvel, debounce).
- `test_sketch_sim.cpp`: compila o `sketch.ino` **real** contra stubs do Arduino e aciona botões com bounce,
  conferindo LCD, LEDs, buzzer, Serial, MQTT e o diagnóstico.

Esses testes validam a lógica. Eles **não substituem** a execução no Wokwi (tempos do simulador, bibliotecas
e desenho do circuito).

## Comunicação MQTT (Etapa 4)

- Broker: `broker.hivemq.com:1883` (público, sem senha), pela rede `Wokwi-GUEST`.
- `<base>/evento`: JSON de cada evento, **retido**; `<base>/status`: `online` ao conectar e `offline` pelo *last will*.
- O formato dos campos está documentado em `../backend/README.md`. Mensagem típica: 192 bytes (máx. 246 B); buffer MQTT: 512 B.
- **Sem broker ou sem Wi-Fi a fila continua funcionando.** O evento fica só no log local, mas o `seq` avança, então o backend
  vê a lacuna. A reconexão é tentada a cada 5 s (a tentativa pode bloquear o laço por até 2 s se o broker não responder).
- RAM da aplicação: `FilaVirtual` 1248 B (medido) + buffer MQTT 512 B + tópicos/strings ~220 B + objetos e variáveis ~0,3 KB, ou seja, **~2,3 KB** dos ~520 KB (conta detalhada em `analise/`).

## Diagnóstico no Serial (medições para o relatório)

Ao iniciar, ao conectar no broker e a cada 60 s o firmware imprime linhas `[DIAG]` com o que o **chip realmente** está usando:
modelo/revisão/núcleos/clock, tamanho do sketch e da Flash, heap (total, livre, mínimo livre, maior bloco), pilha livre do `loop`,
custo de montar o JSON (µs por chamada) e, por período, duração do laço, redesenho do LCD e `mqtt.publish`.
Copiem essas linhas para a tabela de medições do relatório (Etapa 5).

## Limitações conhecidas

- Os bipes usam onda quadrada por software e bloqueiam o laço por ~0,3 s (cliques nesse intervalo são contados depois).
- Sem Wi-Fi, o log usa o tempo desde o boot (`T+hh:mm:ss`); a hora real só aparece após o NTP sincronizar.
- O log local fica só na RAM (perde-se ao reiniciar); o histórico completo fica no servidor (SQLite).
- A PubSubClient publica só com QoS 0: uma mensagem pode se perder (o `seq` mostra a lacuna).
