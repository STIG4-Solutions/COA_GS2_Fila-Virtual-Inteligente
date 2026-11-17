// Stub mínimo da API do Arduino/ESP32 para rodar o sketch no computador (só para testes).
#pragma once
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>

#define IRAM_ATTR
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define FALLING 2

namespace sim {
inline uint32_t now_ms = 0;          // relógio simulado (controlado pelo teste)
inline int level[40] = {};           // nível de cada pino (entradas: o teste define; saídas: o sketch define)
inline long highWrites[40] = {};     // quantas vezes o sketch escreveu HIGH em cada pino (conta bipes)
inline void (*isr[40])() = {};       // ISRs registradas
inline std::string serialOut;        // tudo que foi para o Monitor Serial
}  // namespace sim

inline uint32_t millis() { return sim::now_ms; }
inline uint32_t micros() { return sim::now_ms * 1000u; }
inline void delay(uint32_t ms) { sim::now_ms += ms; }
inline void delayMicroseconds(unsigned) {}
inline void pinMode(uint8_t p, uint8_t m) {
  if (m == INPUT_PULLUP) sim::level[p] = HIGH;
}
inline void digitalWrite(uint8_t p, uint8_t v) {
  sim::level[p] = v;
  if (v == HIGH) sim::highWrites[p]++;
}
inline int digitalRead(uint8_t p) { return sim::level[p]; }
inline int digitalPinToInterrupt(int p) { return p; }
inline void attachInterrupt(int p, void (*f)(), int) { sim::isr[p] = f; }
inline void configTime(long, int, const char*, const char* = nullptr) {}

typedef void* TaskHandle_t;
inline unsigned uxTaskGetStackHighWaterMark(TaskHandle_t) { return 6500; }
struct EspClass {                       // valores fixos: só para o sketch compilar e imprimir no computador
  const char* getChipModel() { return "ESP32-SIM"; }
  int getChipRevision() { return 3; }
  int getChipCores() { return 2; }
  unsigned getCpuFreqMHz() { return 240; }
  unsigned getFlashChipSize() { return 4u * 1024 * 1024; }
  unsigned getSketchSize() { return 900000; }
  unsigned getFreeSketchSpace() { return 1310720; }
  unsigned getHeapSize() { return 330000; }
  unsigned getFreeHeap() { return 250000; }
  unsigned getMinFreeHeap() { return 240000; }
  unsigned getMaxAllocHeap() { return 110000; }
};
inline EspClass ESP;

struct SerialClass {
  void begin(unsigned long) {}
  void print(const char* s) { sim::serialOut += s; }
  void println(const char* s = "") {
    sim::serialOut += s;
    sim::serialOut += "\n";
  }
  void printf(const char* fmt, ...) __attribute__((format(printf, 2, 3))) {
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    sim::serialOut += buf;
  }
};
inline SerialClass Serial;
