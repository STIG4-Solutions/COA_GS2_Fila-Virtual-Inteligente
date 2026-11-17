#pragma once
#include "Arduino.h"
#define WIFI_STA 1
enum { WL_IDLE_STATUS = 0, WL_CONNECTED = 3, WL_DISCONNECTED = 6 };
struct WiFiClient {};
struct WiFiClass {
  int st = WL_DISCONNECTED;  // o teste escolhe: conectado ou não
  int beginCalls = 0;
  void mode(int) {}
  void begin(const char*, const char*, int = 0) { beginCalls++; }
  int status() { return st; }
};
inline WiFiClass WiFi;
