/*
 * Encoder.h - quadrature decoding on the ESP32.
 *
 * Interrupt on BOTH edges of channel A, and read channel B to decide the
 * direction. This gives 2 counts per A-period; TICKS_PER_REV in config.h
 * must be measured to match whatever this actually produces (see the
 * "count the ticks" step in docs/HARDWARE_INTEGRATION.md).
 *
 * count_ is volatile and written from an ISR, so every read from normal
 * code goes through a critical section. Skipping that on a dual-core ESP32
 * gives you torn 32-bit reads and occasional impossible odometry jumps.
 */
#ifndef ENCODER_H
#define ENCODER_H

#include <Arduino.h>

class Encoder {
 public:
  Encoder(uint8_t pinA, uint8_t pinB, int sign) : pinA_(pinA), pinB_(pinB), sign_(sign) {}

  void begin() {
    pinMode(pinA_, INPUT_PULLUP);
    pinMode(pinB_, INPUT_PULLUP);
    mux_ = portMUX_INITIALIZER_UNLOCKED;
  }

  // Called from the ISR. Keep it short: no Serial, no floating point.
  void IRAM_ATTR handleInterrupt() {
    bool a = digitalRead(pinA_);
    bool b = digitalRead(pinB_);
    // A leading B means one direction; A lagging B means the other.
    count_ += (a == b) ? sign_ : -sign_;
  }

  int32_t read() {
    portENTER_CRITICAL(&mux_);
    int32_t value = count_;
    portEXIT_CRITICAL(&mux_);
    return value;
  }

  void reset() {
    portENTER_CRITICAL(&mux_);
    count_ = 0;
    portEXIT_CRITICAL(&mux_);
  }

  uint8_t pinA() const { return pinA_; }

 private:
  uint8_t pinA_, pinB_;
  int sign_;
  volatile int32_t count_ = 0;
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
};

#endif  // ENCODER_H
