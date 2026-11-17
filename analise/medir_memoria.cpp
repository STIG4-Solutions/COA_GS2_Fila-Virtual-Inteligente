// Mede o tamanho real (sizeof) das estruturas do firmware, como o compilador as organiza na memória.
// Compilar de 32 bits (como o ESP32):  g++ -m32 -std=c++17 -I../firmware medir_memoria.cpp -o /tmp/medir && /tmp/medir
// (Se o -m32 não existir no seu g++, compile sem ele: os tamanhos abaixo não usam ponteiros, então coincidem.)
#include <cstddef>
#include <cstdio>
#include "fila_core.h"

int main() {
  using namespace fila;
  printf("Plataforma: ponteiro = %zu bytes, long = %zu bytes, alinhamento de uint64_t = %zu\n\n", sizeof(void*), sizeof(long), alignof(uint64_t));
  printf("%-34s %6s\n", "Estrutura / componente", "bytes");
  printf("%-34s %6zu\n", "Registro (1 evento no log)", sizeof(Registro));
  printf("%-34s %6zu\n", "Resultado (retorno de cada operacao)", sizeof(Resultado));
  printf("%-34s %6zu\n", "FilaVirtual (objeto inteiro)", sizeof(FilaVirtual));
  printf("%-34s %6zu\n", "  FIFO: CAP_FILA x uint32_t", (size_t)CAP_FILA * sizeof(uint32_t));
  printf("%-34s %6zu\n", "  Log circular: CAP_LOG x Registro", (size_t)CAP_LOG * sizeof(Registro));
  printf("%-34s %6zu\n", "  Janela da media: N x uint32_t", (size_t)JANELA_MEDIA * sizeof(uint32_t));
  printf("%-34s %6zu\n", "BotaoDebounce (x2 no sketch)", sizeof(BotaoDebounce));
  printf("%-34s %6zu\n", "Pulso (x3 no sketch)", sizeof(Pulso));
  size_t fixo = sizeof(FilaVirtual);
  printf("\nFilaVirtual = %zu B  (dados puros: %zu B; o resto e' contadores e preenchimento de alinhamento)\n", fixo,
         (size_t)CAP_FILA * 4 + (size_t)CAP_LOG * 12 + (size_t)JANELA_MEDIA * 4);
  return 0;
}
