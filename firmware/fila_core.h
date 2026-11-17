// fila_core.h — Núcleo da Fila Virtual (Citizen Assist AI · Etapa 2)
//
// Esta parte NÃO depende de hardware: só usa inteiros e aritmética. Por isso ela é
// testada no computador (ver test/) e usada sem alterações pelo sketch do ESP32.
//
//  - FilaVirtual     : fila FIFO de chegadas, contadores, validação e log circular
//  - BotaoDebounce   : decide quando um acionamento de botão deve ser contado
//  - Pulso           : temporizador "liga por X ms" imune ao estouro do millis()
//
// Tempos em milissegundos usam uint32_t e subtração sem sinal: continuam corretos
// mesmo quando millis() "dá a volta" (a cada ~49,7 dias).
#pragma once
#define FILA_CORE_VERSAO 4   // 4 = versão final (MQTT + diagnóstico, sem previsão embarcada). O sketch.ino confere este número.
#include <stddef.h>
#include <stdint.h>

namespace fila {

// Parâmetros 
constexpr uint16_t CAP_FILA = 100;      // pessoas na FIFO (100 x 4 bytes = 400 B)
constexpr uint8_t CAP_LOG = 64;         // registros do log circular (64 x 12 B = 768 B)
constexpr uint16_t DEBOUNCE_MS = 50;    // janela de debounce dos botões
constexpr uint8_t JANELA_MEDIA = 10;    // atendimentos usados na média móvel

// Tipo do evento. As duas últimas são tentativas recusadas (operações inválidas).
enum Tipo : uint8_t { CHEGADA = 0, CONCLUSAO = 1, REJEITADA_VAZIA = 2, REJEITADA_CHEIA = 3 };

constexpr uint8_t FLAG_HORA_REAL = 0x01;  // registro carimbado com hora NTP (senão, tempo desde o boot)

inline bool tipoValido(uint8_t t) { return t == CHEGADA || t == CONCLUSAO; }

inline const char* descricao(uint8_t t) {
  switch (t) {
    case CHEGADA: return "CHEGADA";
    case CONCLUSAO: return "CONCLUSAO";
    case REJEITADA_VAZIA: return "REJEITADA (fila vazia)";
    case REJEITADA_CHEIA: return "REJEITADA (fila cheia)";
  }
  return "?";
}

// Identificador estável do tipo, usado no JSON publicado por MQTT (sem espaços nem acentos).
inline const char* codigo(uint8_t t) {
  switch (t) {
    case CHEGADA: return "CHEGADA";
    case CONCLUSAO: return "CONCLUSAO";
    case REJEITADA_VAZIA: return "REJEITADA_VAZIA";
    case REJEITADA_CHEIA: return "REJEITADA_CHEIA";
  }
  return "DESCONHECIDO";
}

// Registro do log: exatamente 12 bytes (hora, espera, fila, tipo, flags).
struct Registro {
  uint32_t hora_s;     // hora Unix (NTP) ou segundos desde o boot, conforme FLAG_HORA_REAL
  uint32_t espera_ms;  // só em CONCLUSAO: quanto a pessoa esperou antes de ser atendida
  uint16_t fila_apos;  // pessoas na fila depois do evento
  uint8_t tipo;        // fila::Tipo
  uint8_t flags;
};
static_assert(sizeof(Registro) == 12, "Registro deve ocupar 12 bytes");

// O que cada operação devolve (usado para Serial, LCD, LEDs e, depois, MQTT).
struct Resultado {
  Tipo tipo;
  bool valido;
  uint16_t fila_apos;
  uint32_t atendidos;
  uint32_t espera_ms;            // CONCLUSAO: tempo esperando até o início do atendimento
  uint32_t atendimento_ms;       // CONCLUSAO: duração do atendimento
  uint32_t media_atendimento_ms; // média móvel dos últimos atendimentos
};

class FilaVirtual {
 public:
  // Botão "Chegada": entra mais uma pessoa no fim da fila.
  Resultado chegada(uint32_t agora_ms, uint32_t hora_s, bool hora_real) {
    if (count_ >= CAP_FILA) {
      rejeitadas_++;
      return fecha(REJEITADA_CHEIA, false, 0, 0, hora_s, hora_real);
    }
    chegadas_[(head_ + count_) % CAP_FILA] = agora_ms;
    count_++;
    return fecha(CHEGADA, true, 0, 0, hora_s, hora_real);
  }

  // Botão "Conclusão": a pessoa da frente termina o atendimento.
  // Fila vazia => operação inválida: nada muda e o contador nunca fica negativo.
  Resultado conclusao(uint32_t agora_ms, uint32_t hora_s, bool hora_real) {
    if (count_ == 0) {
      rejeitadas_++;
      return fecha(REJEITADA_VAZIA, false, 0, 0, hora_s, hora_real);
    }
    const uint32_t chegou = chegadas_[head_];
    head_ = (head_ + 1) % CAP_FILA;
    count_--;

    // O atendimento começa quando o atendente fica livre (conclusão anterior)
    // ou quando a pessoa chega, o que acontecer por último.
    uint32_t inicio = chegou;
    if (temConclusao_ && (int32_t)(ultimaConclusao_ - chegou) > 0) inicio = ultimaConclusao_;
    const uint32_t espera = inicio - chegou;      // ULA: SUB
    const uint32_t atend = agora_ms - inicio;     // ULA: SUB
    ultimaConclusao_ = agora_ms;
    temConclusao_ = true;
    atendidos_++;
    registraAtendimento(atend);
    return fecha(CONCLUSAO, true, espera, atend, hora_s, hora_real);
  }

  uint16_t fila() const { return count_; }
  uint32_t atendidos() const { return atendidos_; }
  uint32_t rejeitadas() const { return rejeitadas_; }

  // Média móvel (últimos JANELA_MEDIA atendimentos). ULA: DIV. Zero se ainda não há dados.
  uint32_t mediaAtendimentoMs() const {
    return nJanela_ == 0 ? 0 : (uint32_t)(somaJanela_ / nJanela_);
  }

  // Log circular: i = 0 é o registro mais antigo ainda guardado.
  uint8_t logTamanho() const { return logN_; }
  const Registro& logEm(uint8_t i) const {
    return log_[(uint8_t)((logProx_ + CAP_LOG - logN_ + i) % CAP_LOG)];
  }

 private:
  Resultado fecha(Tipo t, bool valido, uint32_t espera, uint32_t atend, uint32_t hora_s, bool hora_real) {
    Registro reg;
    reg.hora_s = hora_s;
    reg.espera_ms = espera;
    reg.fila_apos = count_;
    reg.tipo = t;
    reg.flags = hora_real ? FLAG_HORA_REAL : 0;
    log_[logProx_] = reg;
    logProx_ = (uint8_t)((logProx_ + 1) % CAP_LOG);
    if (logN_ < CAP_LOG) logN_++;

    Resultado r;
    r.tipo = t;
    r.valido = valido;
    r.fila_apos = count_;
    r.atendidos = atendidos_;
    r.espera_ms = espera;
    r.atendimento_ms = atend;
    r.media_atendimento_ms = mediaAtendimentoMs();
    return r;
  }

  void registraAtendimento(uint32_t ms) {
    if (nJanela_ == JANELA_MEDIA) {
      somaJanela_ -= janela_[iJanela_];
    } else {
      nJanela_++;
    }
    janela_[iJanela_] = ms;
    somaJanela_ += ms;
    iJanela_ = (uint8_t)((iJanela_ + 1) % JANELA_MEDIA);
  }

  // FIFO de chegadas (horário de cada pessoa, em ms)
  uint32_t chegadas_[CAP_FILA] = {};
  uint16_t head_ = 0;
  uint16_t count_ = 0;  // este é o contador "fila"

  uint32_t atendidos_ = 0;
  uint32_t rejeitadas_ = 0;
  uint32_t ultimaConclusao_ = 0;
  bool temConclusao_ = false;

  // Média móvel
  uint32_t janela_[JANELA_MEDIA] = {};
  uint64_t somaJanela_ = 0;
  uint8_t nJanela_ = 0;
  uint8_t iJanela_ = 0;

  // Log circular
  Registro log_[CAP_LOG] = {};
  uint8_t logProx_ = 0;
  uint8_t logN_ = 0;
};

// Debounce: um acionamento só vale se o botão estiver realmente pressionado, e o
// botão só é "rearmado" depois de ficar solto por janela_ms seguidos. Assim,
// o ruído de contato (bounce) ao apertar OU ao soltar nunca gera um 2º evento,
// e segurar o botão conta uma única vez.
class BotaoDebounce {
 public:
  explicit BotaoDebounce(uint16_t janela_ms = DEBOUNCE_MS) : janela_(janela_ms) {}

  // flagIsr : a interrupção marcou uma borda de descida desde a última chamada
  // baixo   : o pino está em nível baixo agora (botão pressionado)
  // retorna : true quando um clique válido deve ser contado
  bool atualiza(bool flagIsr, bool baixo, uint32_t agora_ms) {
    if (!armado_) {
      if (!baixo) {
        if (!soltoMedindo_) {
          soltoMedindo_ = true;
          soltoDesde_ = agora_ms;
        } else if ((uint32_t)(agora_ms - soltoDesde_) >= janela_) {
          armado_ = true;
          soltoMedindo_ = false;
        }
      } else {
        soltoMedindo_ = false;  // voltou a ficar baixo: reinicia a contagem de "solto"
      }
      return false;
    }
    if (flagIsr && baixo) {
      armado_ = false;
      soltoMedindo_ = false;
      return true;
    }
    return false;
  }

 private:
  uint16_t janela_;
  bool armado_ = true;
  bool soltoMedindo_ = false;
  uint32_t soltoDesde_ = 0;
};

// Liga por uma duração (LED, mensagem do LCD) sem bloquear o laço principal.
struct Pulso {
  bool ativo = false;
  uint32_t fim = 0;
  void dispara(uint32_t agora_ms, uint32_t duracao_ms) {
    ativo = true;
    fim = agora_ms + duracao_ms;
  }
  bool ligado(uint32_t agora_ms) {
    if (ativo && (int32_t)(fim - agora_ms) <= 0) ativo = false;
    return ativo;
  }
};

}  // namespace fila
