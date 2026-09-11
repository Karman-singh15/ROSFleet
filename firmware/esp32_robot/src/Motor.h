/*
 * Motor.h - one H-bridge channel.
 *
 * Takes a signed duty in [-PWM_MAX, +PWM_MAX] and sets direction + speed.
 * Deliberately knows nothing about PID, ROS or encoders.
 */
#ifndef MOTOR_H
#define MOTOR_H

#include <Arduino.h>
#include "config.h"

class Motor {
 public:
  Motor(uint8_t in1, uint8_t in2, uint8_t pwmPin, uint8_t channel)
      : in1_(in1), in2_(in2), pwmPin_(pwmPin), channel_(channel) {}

  void begin() {
    pinMode(in1_, OUTPUT);
    pinMode(in2_, OUTPUT);
    ledcSetup(channel_, PWM_FREQ_HZ, PWM_RESOLUTION);
    ledcAttachPin(pwmPin_, channel_);
    stop();
  }

  // duty: negative = reverse, positive = forward
  void setDuty(int duty) {
    duty = constrain(duty, -PWM_MAX, PWM_MAX);

    // A cheap gearmotor below its stiction threshold just buzzes and heats
    // up without turning, which also confuses the PID. Snap it to zero.
    if (abs(duty) < MIN_MOVE_PWM) {
      stop();
      return;
    }

    if (duty > 0) {
      digitalWrite(in1_, HIGH);
      digitalWrite(in2_, LOW);
    } else {
      digitalWrite(in1_, LOW);
      digitalWrite(in2_, HIGH);
    }
    ledcWrite(channel_, abs(duty));
    lastDuty_ = duty;
  }

  void stop() {
    // Both inputs low = coast. Both high would be an active brake, which
    // slams a plastic gearbox; coasting is kinder to a cheap chassis.
    digitalWrite(in1_, LOW);
    digitalWrite(in2_, LOW);
    ledcWrite(channel_, 0);
    lastDuty_ = 0;
  }

  int lastDuty() const { return lastDuty_; }

 private:
  uint8_t in1_, in2_, pwmPin_, channel_;
  int lastDuty_ = 0;
};

#endif  // MOTOR_H
