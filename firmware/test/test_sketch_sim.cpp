// Simula o sketch.ino REAL no computador: botões com bounce, LEDs, buzzer, LCD e Serial (stubs em test/stubs).
// Não substitui a simulação no Wokwi, mas valida a lógica de ligação (ISR -> debounce -> fila -> saídas).
#include <cstdio>
#include <string>
#include "Arduino.h"
#include "WiFi.h"
#include "LiquidCrystal_I2C.h"
#include "PubSubClient.h"
#include "../fila_core.h"

void setup();
void loop();
extern LiquidCrystal_I2C lcd;
extern fila::FilaVirtual filaVirtual;
extern PubSubClient mqtt;

static int falhas = 0, total = 0;
#define CHECK(cond)                                                \
  do {                                                             \
    total++;                                                       \
    if (!(cond)) { falhas++; printf("  FALHOU  linha %d: %s\n", __LINE__, #cond); } \
  } while (0)

enum { CHEGADA = 18, CONCLUSAO = 19, LED_V = 26, LED_R = 27, BUZ = 25 };

static void tick(int ms = 1) { for (int i = 0; i < ms; i++) { sim::now_ms++; loop(); } }
static void borda(int pin, int nivel) {            // muda o pino; borda de descida dispara a ISR
  bool desceu = (sim::level[pin] == HIGH && nivel == LOW);
  sim::level[pin] = nivel;
  if (desceu && sim::isr[pin]) sim::isr[pin]();
}
// Aperta com 'bounces' oscilações, segura 'hold_ms', solta (também com bounce) e deixa assentar.
static void clique(int pin, int hold_ms = 120, int bounces = 4) {
  borda(pin, LOW); tick(1);
  for (int i = 0; i < bounces; i++) { borda(pin, HIGH); tick(1); borda(pin, LOW); tick(1); }
  tick(hold_ms);
  for (int i = 0; i < bounces; i++) { borda(pin, HIGH); tick(1); borda(pin, LOW); tick(1); }
  borda(pin, HIGH); tick(120);
}
static int conta(const std::string& s, const char* sub) {
  int n = 0; size_t p = 0;
  while ((p = s.find(sub, p)) != std::string::npos) { n++; p += strlen(sub); }
  return n;
}
static std::string trim(std::string s) { while (!s.empty() && s.back() == ' ') s.pop_back(); return s; }

int main(int argc, char** argv) {
  sim::now_ms = 5000;
  setup();
  printf("--- Sem rede (relogio = tempo desde o boot) ---\n");
  CHECK(trim(lcd.linhas[0]) == "Fila: 0" && trim(lcd.linhas[1]) == "Atendidos: 0");

  printf("[Diagnostico] medicoes impressas no Serial (Etapa 5)\n");
  CHECK(sim::serialOut.find("[DIAG] chip=") != std::string::npos);
  CHECK(sim::serialOut.find("[DIAG] apos o setup: heap total=") != std::string::npos);
  CHECK(sim::serialOut.find("montaJson=") != std::string::npos && sim::serialOut.find("bytes)") != std::string::npos);

  printf("[Teste 1] Chegada de novos cidadaos (com bounce nos botoes)\n");
  for (int i = 0; i < 3; i++) { clique(CHEGADA); tick(400); }
  CHECK(filaVirtual.fila() == 3);                       // 1 evento por clique, apesar do bounce
  CHECK(conta(sim::serialOut, "CHEGADA |") == 3);
  CHECK(trim(lcd.linhas[0]) == "Fila: 3");
  CHECK(sim::highWrites[LED_V] > 0);                    // LED verde acendeu
  CHECK(sim::highWrites[BUZ] == 0);                     // eventos válidos não apitam

  printf("[Teste 2] Conclusao de atendimentos\n");
  clique(CONCLUSAO); tick(600);
  clique(CONCLUSAO); tick(600);
  CHECK(filaVirtual.fila() == 1 && filaVirtual.atendidos() == 2);
  CHECK(trim(lcd.linhas[0]) == "Fila: 1" && trim(lcd.linhas[1]) == "Atendidos: 2");
  CHECK(conta(sim::serialOut, "CONCLUSAO |") == 2);
  CHECK(conta(sim::serialOut, "espera=") == 2 && conta(sim::serialOut, "media=") == 2);

  printf("[Teste 3] Tentativa de saida com fila vazia\n");
  clique(CONCLUSAO); tick(300);                         // esvazia a fila (3o atendimento)
  CHECK(filaVirtual.fila() == 0 && filaVirtual.atendidos() == 3);
  long bipesAntes = sim::highWrites[BUZ];
  long vermelhoAntes = sim::highWrites[LED_R];
  for (int i = 0; i < 5; i++) {
    clique(CONCLUSAO, 60, 3);
    if (i == 0) {                                       // logo após a 1ª tentativa recusada
      CHECK(trim(lcd.linhas[1]) == "Fila vazia!");
      CHECK(sim::highWrites[BUZ] > bipesAntes);         // buzzer tocou
      CHECK(sim::highWrites[LED_R] > vermelhoAntes);    // LED vermelho acendeu
    }
  }
  CHECK(filaVirtual.fila() == 0);                       // nunca negativa
  CHECK(filaVirtual.atendidos() == 3);                  // nada foi atendido nas tentativas inválidas
  CHECK(conta(sim::serialOut, "REJEITADA (fila vazia)") == 5);
  tick(2000);                                           // a mensagem some sozinha
  CHECK(trim(lcd.linhas[1]) == "Atendidos: 3");
  CHECK(sim::level[LED_R] == LOW && sim::level[LED_V] == LOW);

  printf("[Extra] segurar o botao conta uma vez so\n");
  size_t antes = conta(sim::serialOut, "CHEGADA |");
  borda(CHEGADA, LOW); tick(3000); borda(CHEGADA, HIGH); tick(200);
  CHECK(conta(sim::serialOut, "CHEGADA |") == (int)antes + 1);

  const int eventosOffline = conta(sim::serialOut, "CHEGADA |") + conta(sim::serialOut, "CONCLUSAO |") +
                             conta(sim::serialOut, "REJEITADA");   // todos os eventos até aqui, sem rede
  CHECK(sim::mqttPublicadas.empty());                      // sem Wi-Fi nada é publicado

  printf("[Etapa 4] Wi-Fi no ar, mas broker MQTT indisponivel\n");
  WiFi.st = WL_CONNECTED;
  sim::mqttBrokerAcessivel = false;
  tick(12000);
  CHECK(sim::serialOut.find("[REDE] Hora sincronizada") != std::string::npos);   // NTP independe do broker
  CHECK(sim::mqttConnectCalls >= 2 && sim::mqttConnectCalls <= 3);                // tenta a cada 5 s, sem inundar
  clique(CHEGADA); tick(300);                                                     // a fila segue funcionando...
  clique(CONCLUSAO); tick(300);
  clique(CONCLUSAO); tick(300);                                                   // ...ate esvaziar de novo
  CHECK(filaVirtual.fila() == 0);
  CHECK(sim::mqttPublicadas.empty());                                             // nada foi enviado
  const int eventosSemBroker = eventosOffline + 3;

  printf("[Etapa 4] Broker volta: status online + eventos em JSON\n");
  sim::mqttBrokerAcessivel = true;
  tick(5200);
  CHECK(mqtt.connected());
  CHECK(sim::mqttWillTopic.size() > 0 && sim::mqttWillTopic.find("/status") != std::string::npos);
  CHECK(sim::mqttWillMsg == "offline" && sim::mqttWillRetida);                    // last will configurado
  CHECK(sim::mqttPublicadas.size() == 1 && sim::mqttPublicadas[0].payload == "online" && sim::mqttPublicadas[0].retida);

  clique(CHEGADA); tick(300);
  clique(CONCLUSAO); tick(300);
  clique(CONCLUSAO); tick(300);                                                   // fila ja esta vazia: recusada
  CHECK(sim::mqttPublicadas.size() == 4);
  auto campo = [&](const std::string& j, const char* chave) {                     // le "chave":valor do JSON
    std::string k = std::string("\"") + chave + "\":";
    size_t p = j.find(k);
    if (p == std::string::npos) return std::string("<ausente>");
    p += k.size();
    size_t f = j.find_first_of(",}", p);
    std::string v = j.substr(p, f - p);
    if (!v.empty() && v.front() == '"') v = v.substr(1, v.size() - 2);
    return v;
  };
  const std::string j1 = sim::mqttPublicadas[1].payload, j2 = sim::mqttPublicadas[2].payload, j3 = sim::mqttPublicadas[3].payload;
  CHECK(sim::mqttPublicadas[1].retida && sim::mqttPublicadas[1].topico.find("/evento") != std::string::npos);
  CHECK(campo(j1, "tipo") == "CHEGADA" && campo(j1, "valido") == "true");
  CHECK(campo(j2, "tipo") == "CONCLUSAO" && campo(j2, "valido") == "true" && campo(j2, "fila") == "0");
  CHECK(campo(j3, "tipo") == "CONCLUSAO" || campo(j3, "tipo") == "REJEITADA_VAZIA");
  CHECK(campo(j1, "sessao") == "a1b2c3d4" && campo(j2, "sessao") == "a1b2c3d4");
  CHECK(campo(j1, "hora_real") == "true");
  // numeracao: o seq conta tambem os eventos que NAO foram enviados (a lacuna fica visivel para o backend)
  CHECK(std::stoi(campo(j1, "seq")) == eventosSemBroker + 1);
  CHECK(std::stoi(campo(j2, "seq")) == eventosSemBroker + 2);
  CHECK(std::stoi(campo(j3, "seq")) == eventosSemBroker + 3);
  CHECK(sim::mqttPublicadas[3].payload.size() < 300);                              // cabe no buffer de 512 B
  CHECK(campo(j3, "valido") == "false" && campo(j3, "tipo") == "REJEITADA_VAZIA");

  printf("[Etapa 4] Queda do broker no meio da operacao\n");
  sim::mqttBrokerAcessivel = false;
  mqtt.derruba();
  clique(CHEGADA);                                                                 // continua contando
  CHECK(filaVirtual.fila() == 1);
  CHECK(sim::mqttPublicadas.size() == 4);                                          // nada novo foi publicado
  sim::mqttBrokerAcessivel = true;
  tick(5200);                                                                      // reconecta sozinho
  CHECK(mqtt.connected());
  CHECK(sim::mqttPublicadas.size() == 5 && sim::mqttPublicadas[4].payload == "online");   // status volta a "online"


  printf("[Fila cheia] a 101a chegada e recusada e o LCD continua legivel\n");
  while (filaVirtual.fila() > 0) { clique(CONCLUSAO); tick(300); }
  for (int i = 0; i < 100; i++) { clique(CHEGADA, 20, 1); tick(50); }
  CHECK(filaVirtual.fila() == 100);
  CHECK(trim(lcd.linhas[0]) == "Fila: 100");
  CHECK(lcd.linhas[0].size() == 16 && lcd.linhas[1].size() == 16);      // sempre cabe nas 16 colunas
  clique(CHEGADA); tick(300);                                           // 101a chegada
  CHECK(filaVirtual.fila() == 100);                                     // a fila nao passa da capacidade
  CHECK(conta(sim::serialOut, "REJEITADA (fila cheia)") == 1);
  CHECK(trim(lcd.linhas[1]) == "Fila cheia!");
  tick(2000);
  CHECK(trim(lcd.linhas[1]).rfind("Atendidos:", 0) == 0);               // a mensagem some sozinha
  for (int i = 0; i < 100; i++) { clique(CONCLUSAO, 20, 1); tick(50); }  // esvazia de novo
  CHECK(filaVirtual.fila() == 0);

  if (argc > 1) {                                       // grava o que o firmware publicaria (contrato com o backend)
    FILE* f = fopen(argv[1], "w");
    for (auto& m : sim::mqttPublicadas) fprintf(f, "%s\t%s\t%d\n", m.topico.c_str(), m.payload.c_str(), m.retida ? 1 : 0);
    fclose(f);
  }
  CHECK(conta(sim::serialOut, "[DIAG] periodico: heap") >= 1);          // a cada 60 s imprime memoria
  CHECK(conta(sim::serialOut, "[DIAG] laco:") >= 1);
  CHECK(sim::serialOut.find("lcd_max=") != std::string::npos && sim::serialOut.find("publish_max=") != std::string::npos);
  CHECK(sim::serialOut.find("[DIAG] apos conectar Wi-Fi e MQTT") != std::string::npos);
  printf("\n===== Monitor Serial simulado =====\n%s", sim::serialOut.c_str());
  printf("\n%d verificacoes, %d falhas\n", total, falhas);
  return falhas ? 1 : 0;
}
