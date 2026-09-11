/*
 * PidController.h - velocity PID for one wheel, with the two guards that
 * matter on a real robot.
 *
 * 1. INTEGRAL WINDUP. If a wheel is stalled against a wall the integral
 *    term grows without bound, and when the robot comes free it launches.
 *    We clamp the integral to whatever could saturate the output.
 *
 * 2. FEEDFORWARD. Pure PID has to build up error before it moves at all,
 *    which feels sluggish and makes low-speed tracking poor. The dominant
 *    term for a DC motor is simply "duty proportional to desired speed",
 *    so we compute that directly and let PID correct the remainder.
 */
#ifndef PID_CONTROLLER_H
#define PID_CONTROLLER_H

#include "Kinematics.h"

class PidController {
 public:
  PidController(float kp, float ki, float kd, float ff, float outputLimit)
      : kp_(kp), ki_(ki), kd_(kd), ff_(ff), outputLimit_(outputLimit) {}

  // setpoint and measured are wheel speed in rad/s; dt in seconds.
  float update(float setpoint, float measured, float dt) {
    if (dt <= 0.0f) return lastOutput_;

    const float error = setpoint - measured;

    const float feedforward = ff_ * setpoint;

    integral_ += error * dt;
    const float integralLimit = (ki_ > 0.0f) ? (outputLimit_ / ki_) : 0.0f;
    integral_ = kinematics::clampf(integral_, -integralLimit, integralLimit);

    const float derivative = (error - lastError_) / dt;
    lastError_ = error;

    float output = feedforward + kp_ * error + ki_ * integral_ + kd_ * derivative;
    output = kinematics::clampf(output, -outputLimit_, outputLimit_);
    lastOutput_ = output;
    return output;
  }

  // Call whenever the robot is commanded to stop, so stale integral does
  // not kick the wheels on the next start.
  void reset() {
    integral_ = 0.0f;
    lastError_ = 0.0f;
    lastOutput_ = 0.0f;
  }

  void setGains(float kp, float ki, float kd, float ff) {
    kp_ = kp; ki_ = ki; kd_ = kd; ff_ = ff;
  }

 private:
  float kp_, ki_, kd_, ff_, outputLimit_;
  float integral_ = 0.0f;
  float lastError_ = 0.0f;
  float lastOutput_ = 0.0f;
};

#endif  // PID_CONTROLLER_H
