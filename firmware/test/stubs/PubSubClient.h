// Stub da PubSubClient: registra o que o sketch publica, sem rede (só para testes no computador).
#pragma once
#include <string>
#include <vector>
#include "Arduino.h"
#include "WiFi.h"

namespace sim {
struct MsgMqtt {
  std::string topico, payload;
  bool retida;
};
inline std::vector<MsgMqtt> mqttPublicadas;   // tudo que foi publicado
inline bool mqttBrokerAcessivel = true;       // o teste escolhe: broker no ar ou não
inline int mqttConnectCalls = 0;
inline std::string mqttWillTopic, mqttWillMsg;
inline bool mqttWillRetida = false;
}  // namespace sim

class PubSubClient {
 public:
  explicit PubSubClient(WiFiClient&) {}
  PubSubClient& setServer(const char*, uint16_t) { return *this; }
  bool setBufferSize(uint16_t n) { buffer_ = n; return true; }
  PubSubClient& setSocketTimeout(uint16_t) { return *this; }
  PubSubClient& setKeepAlive(uint16_t) { return *this; }
  bool connected() { return conectado_; }
  bool connect(const char*, const char* willTopic, uint8_t, bool willRetain, const char* willMsg) {
    sim::mqttConnectCalls++;
    if (!sim::mqttBrokerAcessivel) return false;
    conectado_ = true;
    sim::mqttWillTopic = willTopic;
    sim::mqttWillMsg = willMsg;
    sim::mqttWillRetida = willRetain;
    return true;
  }
  bool publish(const char* topico, const char* payload, bool retida = false) {
    if (!conectado_) return false;
    if (strlen(payload) + strlen(topico) + 10 > buffer_) return false;   // como a biblioteca real
    sim::mqttPublicadas.push_back({topico, payload, retida});
    return true;
  }
  bool loop() { return conectado_; }
  int state() { return conectado_ ? 0 : -2; }
  void derruba() { conectado_ = false; }   // só no stub: simula queda do broker

 private:
  bool conectado_ = false;
  uint16_t buffer_ = 256;                  // padrão da biblioteca real
};
