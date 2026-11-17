#pragma once
#include <string>
#include "Arduino.h"
class LiquidCrystal_I2C {
 public:
  LiquidCrystal_I2C(uint8_t, uint8_t, uint8_t) {}
  void init() {}
  void backlight() {}
  void setCursor(uint8_t, uint8_t r) { row_ = r; }
  void print(const char* s) { linhas[row_] = s; }
  std::string linhas[2];  // o que está "na tela"
 private:
  uint8_t row_ = 0;
};
