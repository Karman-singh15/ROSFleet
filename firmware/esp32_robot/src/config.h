/*
 * config.h - every pin and constant for the ROSFleet robot.
 *
 * IMPORTANT: the drivetrain numbers here MUST match
 * ros_ws/src/robot_hardware/config/hardware.yaml. If the firmware thinks
 * the wheelbase is 0.16 m and ROS thinks it is 0.20 m, the robot will
 * consistently over- or under-rotate and no amount of PID tuning fixes it.
 */
#ifndef CONFIG_H
#define CONFIG_H

// ===================== MOTOR DRIVER PINS =====================
// Wiring assumes an L298N or TB6612FNG:
//   IN1/IN2 set direction, ENA/ENB take the PWM speed signal.
// Avoid ESP32 pins 6-11 (flash) and 34-39 (input only, no pull-ups).
#define PIN_LEFT_IN1    26
#define PIN_LEFT_IN2    27
#define PIN_LEFT_PWM    14

#define PIN_RIGHT_IN1   25
#define PIN_RIGHT_IN2   33
#define PIN_RIGHT_PWM   32

// LEDC hardware PWM: 20 kHz is above hearing, so the motors stop whining.
#define PWM_FREQ_HZ     20000
#define PWM_RESOLUTION  10          // 10 bit -> duty 0..1023
#define PWM_MAX         1023
#define PWM_CHANNEL_L   0
#define PWM_CHANNEL_R   1

// ===================== ENCODER PINS =====================
// Both channels must be interrupt-capable AND support internal pull-ups.
// Deliberately NOT using 34-39: those are input-only with no internal
// pull-ups, and most hall encoders need one. On a WROVER module 16/17 are
// taken by PSRAM - move to 13/15 there.
#define PIN_LEFT_ENC_A  16
#define PIN_LEFT_ENC_B  17
#define PIN_RIGHT_ENC_A  4
#define PIN_RIGHT_ENC_B 23

// Set to -1 if your wheel counts DOWN while driving forward. Flipping this
// is much easier than re-soldering, and must agree with
// invert_*_encoder in hardware.yaml (set one or the other, never both).
#define LEFT_ENCODER_SIGN   1
#define RIGHT_ENCODER_SIGN  1

// ===================== DRIVETRAIN GEOMETRY =====================
// KEEP IN SYNC WITH hardware.yaml
#define WHEEL_RADIUS_M       0.0325f
#define WHEEL_SEPARATION_M   0.160f
// encoder PPR * gear ratio * 4 (quadrature counts all 4 edges)
#define TICKS_PER_REV        780.0f

// ===================== SAFETY LIMITS =====================
#define MAX_LINEAR_MPS       0.35f
#define MAX_ANGULAR_RPS      1.50f
// If no CMD arrives within this window the motors are cut. This is the
// last line of defence against a Wi-Fi dropout at full speed.
#define CMD_WATCHDOG_MS      500
// Minimum duty that actually overcomes static friction. Below this a cheap
// gearmotor just buzzes, so we snap small outputs to zero instead.
#define MIN_MOVE_PWM         120

// ===================== CONTROL LOOP =====================
#define CONTROL_PERIOD_MS    20     // 50 Hz velocity PID
#define TELEMETRY_PERIOD_MS  20     // 50 Hz ENC messages to the host
#define BATTERY_PERIOD_MS    1000
#define RANGE_PERIOD_MS      100

// Per-wheel PID on wheel speed in rad/s. Start with feedforward only
// (KP=0, KI=0) to confirm wiring, then raise KP until it tracks.
#define PID_KP   0.60f
#define PID_KI   2.50f
#define PID_KD   0.00f
// Feedforward: duty needed per rad/s. Measured, not guessed - see
// docs/HARDWARE_INTEGRATION.md "Step 7: calibrate feedforward".
#define PID_FF   38.0f

// ===================== BATTERY SENSING =====================
// Voltage divider into an ADC pin. With R1=10k (to battery) and R2=10k
// (to ground) the ratio is 2.0, so an 8.4 V pack reads 4.2 V - still too
// high for the ESP32's 3.3 V ADC, so use R1=20k/R2=10k -> ratio 3.0.
// GPIO34 is input-only, which is exactly right for an analog divider.
#define PIN_BATTERY_ADC      34
#define BATTERY_DIVIDER      3.0f
#define ADC_REF_VOLTS        3.30f
#define ADC_MAX_COUNTS       4095.0f
// The ESP32 ADC is noticeably non-linear; correct with a measured factor.
#define BATTERY_CALIBRATION  1.00f
#define ENABLE_BATTERY       1

// ===================== ULTRASONIC (OPTIONAL) =====================
// A cheap HC-SR04 bumper. It does NOT replace the LiDAR for navigation;
// it is a last-resort "something is right in front of me" check.
#define ENABLE_ULTRASONIC    0
#define PIN_TRIG             18
#define PIN_ECHO             19

// ===================== WIFI =====================
#ifdef ENABLE_WIFI
  #define WIFI_SSID      "YOUR_WIFI_SSID"
  #define WIFI_PASSWORD  "YOUR_WIFI_PASSWORD"
  #define TCP_PORT       9000
  // Give up on Wi-Fi after this long and run serial-only rather than
  // leaving the robot unresponsive while it retries forever.
  #define WIFI_CONNECT_TIMEOUT_MS 15000
#endif

#endif  // CONFIG_H
