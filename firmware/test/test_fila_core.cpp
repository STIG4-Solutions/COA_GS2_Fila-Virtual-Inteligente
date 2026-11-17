// Testes do núcleo (fila_core.h) — rodam no computador, sem hardware.
#include <cstdio>
#include <string>
#include "../fila_core.h"
using namespace fila;

static int falhas = 0, total = 0;
#define CHECK(cond)                                                       \
  do {                                                                    \
    total++;                                                              \
    if (!(cond)) {                                                        \
      falhas++;                                                           \
      printf("  FALHOU  linha %d: %s\n", __LINE__, #cond);                \
    }                                                                     \
  } while (0)

static void teste1_chegadas() {
  printf("[Teste 1] Chegada de novos cidadaos\n");
  FilaVirtual f;
  for (int i = 0; i < 3; i++) {
    Resultado r = f.chegada(1000 + 1000 * i, 100 + i, false);
    CHECK(r.valido && r.tipo == CHEGADA);
    CHECK(r.fila_apos == i + 1);
  }
  CHECK(f.fila() == 3);
  CHECK(f.atendidos() == 0);
  CHECK(f.logTamanho() == 3);
  for (int i = 0; i < 3; i++) {
    CHECK(f.logEm(i).tipo == CHEGADA);
    CHECK(f.logEm(i).fila_apos == i + 1);
    CHECK(f.logEm(i).hora_s == (uint32_t)(100 + i));
  }
}

static void teste2_conclusoes() {
  printf("[Teste 2] Conclusao de atendimentos (tempos reais)\n");
  FilaVirtual f;
  f.chegada(1000, 0, false);
  f.chegada(2000, 0, false);
  f.chegada(3000, 0, false);
  Resultado a = f.conclusao(5000, 0, false);   // 1ª pessoa: chegou 1000, atendida de 1000 a 5000
  CHECK(a.valido && a.tipo == CONCLUSAO);
  CHECK(a.fila_apos == 2 && a.atendidos == 1);
  CHECK(a.espera_ms == 0 && a.atendimento_ms == 4000);
  Resultado b = f.conclusao(9000, 0, false);   // 2ª: chegou 2000, esperou até 5000, atendida de 5000 a 9000
  CHECK(b.fila_apos == 1 && b.atendidos == 2);
  CHECK(b.espera_ms == 3000 && b.atendimento_ms == 4000);
  CHECK(b.media_atendimento_ms == 4000);
  CHECK(f.fila() == 1 && f.atendidos() == 2);
  // atendente ocioso: pessoa chega depois da última conclusão => espera 0
  f.conclusao(10000, 0, false);                // 3ª: chegou 3000, início 9000, espera 6000, atend. 1000
  f.chegada(20000, 0, false);
  Resultado c = f.conclusao(26000, 0, false);  // chegou 20000, atendente livre desde 10000 => espera 0
  CHECK(c.espera_ms == 0 && c.atendimento_ms == 6000);
}

static void teste3_fila_vazia() {
  printf("[Teste 3] Tentativa de saida com fila vazia\n");
  FilaVirtual f;
  for (int i = 0; i < 1000; i++) {
    Resultado r = f.conclusao(i * 10u, 0, false);
    CHECK(!r.valido && r.tipo == REJEITADA_VAZIA);
    CHECK(f.fila() == 0);          // nunca negativa
    CHECK(f.atendidos() == 0);     // nada foi atendido
  }
  CHECK(f.rejeitadas() == 1000);
  CHECK(f.logEm(f.logTamanho() - 1).tipo == REJEITADA_VAZIA);
  // depois de rejeições o sistema continua normal
  f.chegada(20000, 0, false);
  CHECK(f.fila() == 1);
  Resultado r = f.conclusao(21000, 0, false);
  CHECK(r.valido && f.fila() == 0 && f.atendidos() == 1);
}

static void extras() {
  printf("[Extras] fila cheia, log circular, estouro do millis, media movel\n");
  FilaVirtual f;
  for (int i = 0; i < CAP_FILA; i++) CHECK(f.chegada(i, 0, false).valido);
  Resultado cheia = f.chegada(999, 0, false);
  CHECK(!cheia.valido && cheia.tipo == REJEITADA_CHEIA && f.fila() == CAP_FILA);
  CHECK(sizeof(Registro) == 12);

  // log circular: mais eventos que a capacidade => guarda só os 64 mais recentes, em ordem
  FilaVirtual g;
  for (int i = 0; i < 100; i++) g.chegada(i, 1000 + i, true);
  CHECK(g.logTamanho() == CAP_LOG);
  CHECK(g.logEm(0).hora_s == 1000u + 100 - CAP_LOG);
  CHECK(g.logEm(CAP_LOG - 1).hora_s == 1099u);
  CHECK(g.logEm(0).flags & FLAG_HORA_REAL);

  // estouro do millis(): chegada perto de 2^32 e conclusão depois da volta
  FilaVirtual h;
  h.chegada(0xFFFFFF00u, 0, false);
  Resultado r = h.conclusao(0x00000100u, 0, false);  // 0x200 = 512 ms depois, mesmo com a volta
  CHECK(r.valido && r.atendimento_ms == 512 && r.espera_ms == 0);

  // média móvel só considera os últimos JANELA_MEDIA atendimentos
  FilaVirtual m;
  uint32_t t = 0;
  for (int i = 0; i < 25; i++) {
    m.chegada(t, 0, false);
    t += (i < 15) ? 1000 : 3000;  // 15 atendimentos de 1 s e depois 10 de 3 s
    m.conclusao(t, 0, false);
  }
  CHECK(m.mediaAtendimentoMs() == 3000);
}

static void debounce() {
  printf("[Debounce] bounce ao apertar/soltar, segurar e reapertar\n");
  BotaoDebounce b(50);
  int cliques = 0;
  uint32_t t = 0;
  auto passo = [&](bool flag, bool baixo) { if (b.atualiza(flag, baixo, t)) cliques++; t++; };

  // aperta com bounce (várias bordas em ~8 ms), segura 300 ms
  passo(true, true);
  for (int i = 0; i < 4; i++) { passo(false, false); passo(true, true); }
  for (int i = 0; i < 300; i++) passo(false, true);
  CHECK(cliques == 1);
  // solta com bounce (glitches em nível baixo), depois fica solto
  for (int i = 0; i < 3; i++) { passo(false, false); passo(true, true); }
  for (int i = 0; i < 100; i++) passo(false, false);
  CHECK(cliques == 1);  // soltar nunca gera clique
  // segundo aperto, já rearmado
  passo(true, true);
  for (int i = 0; i < 50; i++) passo(false, true);
  CHECK(cliques == 2);
  // glitch em nível alto (flag sem botão realmente pressionado) é ignorado
  BotaoDebounce g(50);
  CHECK(!g.atualiza(true, false, 0));
  // re-aperto em menos de 50 ms depois de soltar é ignorado
  for (int i = 0; i < 20; i++) passo(false, false);
  passo(true, true);
  CHECK(cliques == 2);
}

static void codigos() {
  printf("[Codigos] identificadores do JSON\n");
  CHECK(std::string(codigo(CHEGADA)) == "CHEGADA");
  CHECK(std::string(codigo(CONCLUSAO)) == "CONCLUSAO");
  CHECK(std::string(codigo(REJEITADA_VAZIA)) == "REJEITADA_VAZIA");
  CHECK(std::string(codigo(REJEITADA_CHEIA)) == "REJEITADA_CHEIA");
}

static void pulso() {
  printf("[Pulso] temporizador imune ao estouro do millis\n");
  Pulso p;
  CHECK(!p.ligado(0xFFFFF000u));        // nunca disparado: desligado mesmo com millis alto
  p.dispara(0xFFFFFF00u, 500);          // termina depois da volta (0x1F4 - 0x100 = 0xF4)
  CHECK(p.ligado(0xFFFFFFFFu));
  CHECK(p.ligado(0x000000F0u));
  CHECK(!p.ligado(0x000000F4u));
}

int main() {
  teste1_chegadas();
  teste2_conclusoes();
  teste3_fila_vazia();
  extras();
  debounce();
  codigos();
  pulso();
  printf("\n%d verificacoes, %d falhas\n", total, falhas);
  return falhas ? 1 : 0;
}
