/*
 * Citizen Assist AI — Fila Virtual · Etapa 2 (firmware do ESP32)
 *
 * Entradas : botão Chegada (GPIO 18) e botão Conclusão (GPIO 19), com pull-up interno,
 *            lidos por interrupção (a ISR só sinaliza) + debounce de 50 ms no laço.
 * Processo : fila FIFO, contadores, validação (nunca negativa) e log circular — ver fila_core.h.
 * Saídas   : LCD I2C 16x2 (fila e atendidos), LED verde/vermelho, buzzer e Monitor Serial.
 * Hora     : NTP via Wi-Fi (rede "Wokwi-GUEST"). Sem rede, a fila funciona normalmente e o
 *            log usa o tempo desde o boot (T+hh:mm:ss).
 * Rede     : (Etapa 4) cada evento é publicado em JSON por MQTT no tópico <base>/evento e o estado
 *            do dispositivo em <base>/status (online/offline, via "last will"). Sem broker, a fila
 *            continua funcionando; os eventos ficam só no log local e a numeração (seq) revela a lacuna.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
#include <LiquidCrystal_I2C.h>
#include <PubSubClient.h>
#include <esp_system.h>

#include "fila_core.h"

#if !defined(FILA_CORE_VERSAO) || FILA_CORE_VERSAO < 4
#error "fila_core.h DESATUALIZADO: copie para o projeto do Wokwi a versao mais recente do fila_core.h (e apague o modelo_coef.h, se existir)."
#endif

// pinos
constexpr uint8_t PIN_BTN_CHEGADA = 18;
constexpr uint8_t PIN_BTN_CONCLUSAO = 19;
constexpr uint8_t PIN_LED_VERDE = 26;
constexpr uint8_t PIN_LED_VERMELHO = 27;
constexpr uint8_t PIN_BUZZER = 25;
// LCD I2C: SDA = GPIO 21, SCL = GPIO 22 (pinos padrão do Wire no ESP32)

// configuração
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_SENHA = "";
constexpr int WIFI_CANAL = 6;                     // canal 6 acelera a conexão no Wokwi
constexpr long GMT_OFFSET_S = -3 * 3600;          // São Paulo (UTC-3)
constexpr uint32_t REPETE_WIFI_MS = 30000;        // nova tentativa de Wi-Fi a cada 30 s
constexpr uint32_t LED_VALIDO_MS = 300;
constexpr uint32_t LED_INVALIDO_MS = 800;
constexpr uint32_t MSG_LCD_MS = 1500;

// MQTT (Etapa 4)
// ATENÇÃO: o broker é PÚBLICO e sem senha. portanto, o nome do tópico PRECISA ser o mesmo no firmware 
// e no backend para que o projeto funcione.
const char* MQTT_BROKER = "broker.hivemq.com";
constexpr uint16_t MQTT_PORTA = 1883;
const char* TOPICO_BASE = "fiap1ccfev/citizenassist/gs2026-Stig4";
constexpr uint32_t REPETE_MQTT_MS = 5000;         // nova tentativa de conexão ao broker

// estado
LiquidCrystal_I2C lcd(0x27, 16, 2);
fila::FilaVirtual filaVirtual;
fila::BotaoDebounce btnChegada(fila::DEBOUNCE_MS);
fila::BotaoDebounce btnConclusao(fila::DEBOUNCE_MS);

// A ISR apenas conta bordas de descida; o laço principal compara com o que já viu.
volatile uint32_t pulsosChegada = 0;
volatile uint32_t pulsosConclusao = 0;
uint32_t vistosChegada = 0;
uint32_t vistosConclusao = 0;

fila::Pulso ledVerde, ledVermelho, msgLcd;
char textoMsgLcd[17] = "";
bool msgLcdVisivel = false;
bool lcdSujo = true;

bool horaSincronizada = false;
bool ntpIniciado = false;
uint32_t ultimaTentativaWifi = 0;

// Diagnóstico (Etapa 5): medições feitas no próprio chip e impressas no Serial
constexpr uint32_t DIAG_PERIODO_MS = 60000;
uint32_t ultimoDiag = 0;
uint32_t iteracoesNoPeriodo = 0;
uint64_t somaLoopUs = 0;
uint32_t maxLoopUs = 0;
uint32_t maxLcdUs = 0;       // maior tempo de um redesenho completo do LCD (I2C)
uint32_t maxPublishUs = 0;   // maior tempo de um mqtt.publish() (TCP/Wi-Fi)
bool diagAposMqtt = false;

WiFiClient clienteWifi;
PubSubClient mqtt(clienteWifi);
char sessao[9] = "";               // identifica esta execução do firmware (muda a cada boot)
char topicoEvento[96] = "";
char topicoStatus[96] = "";
uint32_t seqEvento = 0;            // numera TODOS os eventos (enviados ou não)
uint32_t ultimaTentativaMqtt = 0;
bool mqttJaTentou = false;

// ISRs
void IRAM_ATTR isrChegada() { pulsosChegada = pulsosChegada + 1; }
void IRAM_ATTR isrConclusao() { pulsosConclusao = pulsosConclusao + 1; }

// relógio
void atualizaRelogio(uint32_t agora) {
  if (horaSincronizada) return;
  if (WiFi.status() == WL_CONNECTED) {
    if (!ntpIniciado) {
      configTime(GMT_OFFSET_S, 0, "pool.ntp.org", "time.google.com");
      ntpIniciado = true;
      Serial.println("[REDE] Wi-Fi conectado; sincronizando a hora via NTP...");
    }
    if (time(nullptr) > 1700000000L) {  // passou de nov/2023 => a hora é real
      horaSincronizada = true;
      Serial.println("[REDE] Hora sincronizada via NTP.");
    }
  } else if ((uint32_t)(agora - ultimaTentativaWifi) >= REPETE_WIFI_MS) {
    WiFi.begin(WIFI_SSID, WIFI_SENHA, WIFI_CANAL);
    ultimaTentativaWifi = agora;
  }
}

uint32_t horaParaLog(uint32_t agora) {
  return horaSincronizada ? (uint32_t)time(nullptr) : agora / 1000;
}

void horaTexto(char* buf, size_t n, uint32_t agora) {
  if (horaSincronizada) {
    time_t t = time(nullptr);
    struct tm tmv;
    localtime_r(&t, &tmv);
    strftime(buf, n, "%d/%m/%Y %H:%M:%S", &tmv);
  } else {
    const uint32_t s = agora / 1000;
    snprintf(buf, n, "T+%02lu:%02lu:%02lu", (unsigned long)(s / 3600), (unsigned long)((s / 60) % 60),
             (unsigned long)(s % 60));
  }
}

// MQTT
void atualizaMqtt(uint32_t agora) {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) {
    mqtt.loop();
    return;
  }
  if (mqttJaTentou && (uint32_t)(agora - ultimaTentativaMqtt) < REPETE_MQTT_MS) return;
  mqttJaTentou = true;
  ultimaTentativaMqtt = agora;

  char id[32];
  snprintf(id, sizeof(id), "fila-esp32-%s", sessao);
  // "Last will": se o ESP32 sumir sem avisar, o broker publica "offline" (retido) no tópico de status.
  if (mqtt.connect(id, topicoStatus, 1, true, "offline")) {
    mqtt.publish(topicoStatus, "online", true);
    Serial.println("[REDE] MQTT conectado ao broker.");
    diagAposMqtt = true;
  } else {
    Serial.printf("[REDE] MQTT indisponivel (rc=%d); nova tentativa em %lu s.\n", mqtt.state(),
                  (unsigned long)(REPETE_MQTT_MS / 1000));
  }
}

// Monta o JSON do evento em 'buf'. Devolve o tamanho (ou -1 se não coube).
int montaJson(char* buf, size_t n, const fila::Resultado& r, uint32_t agora) {
  const int len = snprintf(
      buf, n,
      "{\"sessao\":\"%s\",\"seq\":%lu,\"tipo\":\"%s\",\"valido\":%s,\"fila\":%u,\"atendidos\":%lu,"
      "\"hora_s\":%lu,\"hora_real\":%s,\"uptime_ms\":%lu,\"espera_ms\":%lu,\"atendimento_ms\":%lu,"
      "\"media_ms\":%lu}",
      sessao, (unsigned long)seqEvento, fila::codigo(r.tipo), r.valido ? "true" : "false", (unsigned)r.fila_apos,
      (unsigned long)r.atendidos, (unsigned long)horaParaLog(agora), horaSincronizada ? "true" : "false",
      (unsigned long)agora, (unsigned long)r.espera_ms, (unsigned long)r.atendimento_ms,
      (unsigned long)r.media_atendimento_ms);
  return (len > 0 && len < (int)n) ? len : -1;
}

// Publica o evento em JSON (retido: quem se conectar depois já recebe o último estado).
// Sem conexão, o evento NÃO é enviado, mas o seq avança, então o backend detecta a lacuna.
void publicaEvento(const fila::Resultado& r, uint32_t agora) {
  seqEvento++;
  if (!mqtt.connected()) return;
  char json[360];
  if (montaJson(json, sizeof(json), r, agora) > 0) {
    const uint32_t a = micros();
    mqtt.publish(topicoEvento, json, true);
    const uint32_t d = micros() - a;
    if (d > maxPublishUs) maxPublishUs = d;
  }
}

// diagnóstico (Etapa 5)
// Mede no próprio chip: memória, pilha, tempo do laço, LCD, publicação MQTT e custo do JSON. Saída no Monitor Serial.
void diagIdentificacao() {
  Serial.printf("[DIAG] chip=%s rev=%d nucleos=%d cpu=%luMHz | flash=%luKB sketch=%luKB (livre p/ OTA: %luKB)\n",
                ESP.getChipModel(), (int)ESP.getChipRevision(), (int)ESP.getChipCores(),
                (unsigned long)ESP.getCpuFreqMHz(), (unsigned long)(ESP.getFlashChipSize() / 1024),
                (unsigned long)(ESP.getSketchSize() / 1024), (unsigned long)(ESP.getFreeSketchSpace() / 1024));
}

void diagMemoria(const char* momento) {
  Serial.printf("[DIAG] %s: heap total=%lu B livre=%lu B minimo_livre=%lu B maior_bloco=%lu B | pilha do loop: livre_min=%lu B de 8192\n",
                momento, (unsigned long)ESP.getHeapSize(), (unsigned long)ESP.getFreeHeap(),
                (unsigned long)ESP.getMinFreeHeap(), (unsigned long)ESP.getMaxAllocHeap(),
                (unsigned long)uxTaskGetStackHighWaterMark(NULL));
}

void diagLaco() {
  const unsigned long media = iteracoesNoPeriodo ? (unsigned long)(somaLoopUs / iteracoesNoPeriodo) : 0;
  Serial.printf("[DIAG] laco: %lu iteracoes no periodo | duracao media=%lu us maxima=%lu us | lcd_max=%lu us | publish_max=%lu us\n",
                (unsigned long)iteracoesNoPeriodo, media, (unsigned long)maxLoopUs, (unsigned long)maxLcdUs,
                (unsigned long)maxPublishUs);
  iteracoesNoPeriodo = 0;
  somaLoopUs = 0;
  maxLoopUs = 0;
  maxLcdUs = 0;
  maxPublishUs = 0;
}

// Custo de montar o JSON do evento (snprintf com 12 campos), medido com micros() em várias repetições.
void diagBenchmarks() {
  fila::Resultado r;
  r.tipo = fila::CONCLUSAO; r.valido = true; r.fila_apos = 3; r.atendidos = 12;
  r.espera_ms = 65000; r.atendimento_ms = 215000; r.media_atendimento_ms = 220000;
  char buf[360];
  int tam = 0;
  const int M = 200;
  const uint32_t t0 = micros();
  for (int i = 0; i < M; i++) tam = montaJson(buf, sizeof(buf), r, millis());
  const uint32_t dtJson = micros() - t0;
  Serial.printf("[DIAG] custo: montaJson=%.1f us/chamada (%d bytes)\n", dtJson / (float)M, tam);
}

// saídas
void beep(uint16_t freq_hz, uint16_t dur_ms) {  // onda quadrada simples (bloqueia por dur_ms)
  const uint32_t meio_periodo_us = 500000UL / freq_hz;
  const uint32_t ciclos = (uint32_t)freq_hz * dur_ms / 1000UL;
  for (uint32_t i = 0; i < ciclos; i++) {
    digitalWrite(PIN_BUZZER, HIGH);
    delayMicroseconds(meio_periodo_us);
    digitalWrite(PIN_BUZZER, LOW);
    delayMicroseconds(meio_periodo_us);
  }
}

void desenhaLcd() {
  char tmp[24], l1[17], l2[17];  // cada linha do LCD tem 16 colunas (%.16s corta o excedente)
  snprintf(tmp, sizeof(tmp), "Fila: %u", (unsigned)filaVirtual.fila());
  snprintf(l1, sizeof(l1), "%-16.16s", tmp);
  if (msgLcdVisivel) {
    snprintf(l2, sizeof(l2), "%-16.16s", textoMsgLcd);
  } else {
    snprintf(tmp, sizeof(tmp), "Atendidos: %lu", (unsigned long)filaVirtual.atendidos());
    snprintf(l2, sizeof(l2), "%-16.16s", tmp);
  }
  const uint32_t a = micros();
  lcd.setCursor(0, 0);
  lcd.print(l1);
  lcd.setCursor(0, 1);
  lcd.print(l2);
  const uint32_t d = micros() - a;
  if (d > maxLcdUs) maxLcdUs = d;
}

void imprimeEvento(const fila::Resultado& r, uint32_t agora) {
  char hora[24];
  horaTexto(hora, sizeof(hora), agora);
  Serial.printf("[%s] %s | fila=%u | atendidos=%lu", hora, fila::descricao(r.tipo), (unsigned)r.fila_apos,
                (unsigned long)r.atendidos);
  if (r.tipo == fila::CONCLUSAO) {
    Serial.printf(" | espera=%.1fs | atendimento=%.1fs | media=%.1fs", r.espera_ms / 1000.0f,
                  r.atendimento_ms / 1000.0f, r.media_atendimento_ms / 1000.0f);
  }
  Serial.println();
}

// Resultado de qualquer evento => registro serial + feedback visual/sonoro + LCD.
void tratarResultado(const fila::Resultado& r, uint32_t agora) {
  imprimeEvento(r, agora);
  publicaEvento(r, agora);   // antes dos bipes (que bloqueiam ~0,3 s)

  if (r.valido) {  // evento aceito: LED verde e LCD atualizado
    ledVerde.dispara(agora, LED_VALIDO_MS);
    lcdSujo = true;
    return;
  }

  // Operação inválida: LED vermelho, mensagem no LCD e dois bipes curtos.
  // O LED e o LCD são atualizados primeiro; os bipes (bloqueantes, ~0,3 s) ficam por último.
  ledVermelho.dispara(agora, LED_INVALIDO_MS);
  digitalWrite(PIN_LED_VERMELHO, HIGH);
  snprintf(textoMsgLcd, sizeof(textoMsgLcd), "%s",
           r.tipo == fila::REJEITADA_VAZIA ? "Fila vazia!" : "Fila cheia!");
  msgLcd.dispara(agora, MSG_LCD_MS);
  msgLcdVisivel = true;
  desenhaLcd();
  lcdSujo = false;
  beep(2000, 100);
  delay(80);
  beep(2000, 100);
}

void aoPressionarChegada(uint32_t agora) {
  tratarResultado(filaVirtual.chegada(agora, horaParaLog(agora), horaSincronizada), agora);
}

void aoPressionarConclusao(uint32_t agora) {
  tratarResultado(filaVirtual.conclusao(agora, horaParaLog(agora), horaSincronizada), agora);
}

// setup / loop
void setup() {
  Serial.begin(115200);

  pinMode(PIN_BTN_CHEGADA, INPUT_PULLUP);
  pinMode(PIN_BTN_CONCLUSAO, INPUT_PULLUP);
  pinMode(PIN_LED_VERDE, OUTPUT);
  pinMode(PIN_LED_VERMELHO, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED_VERDE, LOW);
  digitalWrite(PIN_LED_VERMELHO, LOW);
  digitalWrite(PIN_BUZZER, LOW);

  lcd.init();
  lcd.backlight();
  desenhaLcd();

  attachInterrupt(digitalPinToInterrupt(PIN_BTN_CHEGADA), isrChegada, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_BTN_CONCLUSAO), isrConclusao, FALLING);

  snprintf(sessao, sizeof(sessao), "%08lx", (unsigned long)esp_random());
  snprintf(topicoEvento, sizeof(topicoEvento), "%s/evento", TOPICO_BASE);
  snprintf(topicoStatus, sizeof(topicoStatus), "%s/status", TOPICO_BASE);
  mqtt.setServer(MQTT_BROKER, MQTT_PORTA);
  mqtt.setBufferSize(512);      // o padrão (256 B) é pequeno para o JSON do evento
  mqtt.setSocketTimeout(2);     // limita o bloqueio quando o broker não responde
  mqtt.setKeepAlive(30);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_SENHA, WIFI_CANAL);
  ultimaTentativaWifi = millis();

  Serial.println();
  Serial.println("=== Citizen Assist AI - Fila Virtual (Etapa 2) ===");
  Serial.println("Chegada = GPIO 18 | Conclusao = GPIO 19 | LCD I2C 0x27 (SDA 21, SCL 22)");
  Serial.println("Formato: [hora] EVENTO | fila | atendidos | tempos (na conclusao)");
  diagIdentificacao();
  diagBenchmarks();
  diagMemoria("apos o setup");
  ultimoDiag = millis();
  Serial.printf("MQTT: %s:%u | topico base: %s | sessao: %s\n", MQTT_BROKER, (unsigned)MQTT_PORTA, TOPICO_BASE, sessao);
}

void loop() {
  const uint32_t inicioUs = micros();
  const uint32_t agora = millis();
  atualizaRelogio(agora);
  atualizaMqtt(agora);

  // 1) Lê o que a ISR sinalizou desde a última volta
  const uint32_t pc = pulsosChegada;
  const uint32_t pk = pulsosConclusao;
  const bool flagChegada = (pc != vistosChegada);
  const bool flagConclusao = (pk != vistosConclusao);
  vistosChegada = pc;
  vistosConclusao = pk;

  // 2) Debounce + tratamento dos eventos
  if (btnChegada.atualiza(flagChegada, digitalRead(PIN_BTN_CHEGADA) == LOW, agora)) {
    aoPressionarChegada(agora);
  }
  if (btnConclusao.atualiza(flagConclusao, digitalRead(PIN_BTN_CONCLUSAO) == LOW, agora)) {
    aoPressionarConclusao(agora);
  }

  // 3) Saídas: LEDs, mensagem temporária do LCD e redesenho quando algo mudou
  const uint32_t t = millis();
  digitalWrite(PIN_LED_VERDE, ledVerde.ligado(t) ? HIGH : LOW);
  digitalWrite(PIN_LED_VERMELHO, ledVermelho.ligado(t) ? HIGH : LOW);
  const bool msgAgora = msgLcd.ligado(t);
  if (msgAgora != msgLcdVisivel) {
    msgLcdVisivel = msgAgora;
    lcdSujo = true;
  }
  if (lcdSujo) {
    desenhaLcd();
    lcdSujo = false;
  }

  // 4) Diagnóstico: tempo deste laço e, a cada 60 s (ou após conectar ao broker), memória e laço
  const uint32_t duracaoUs = micros() - inicioUs;
  iteracoesNoPeriodo++;
  somaLoopUs += duracaoUs;
  if (duracaoUs > maxLoopUs) maxLoopUs = duracaoUs;
  if (diagAposMqtt) {
    diagAposMqtt = false;
    diagMemoria("apos conectar Wi-Fi e MQTT");
  }
  if ((uint32_t)(t - ultimoDiag) >= DIAG_PERIODO_MS) {
    ultimoDiag = t;
    diagMemoria("periodico");
    diagLaco();
  }
}
