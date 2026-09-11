/*
 * ROSFleet ESP32 firmware
 * =======================
 * The robot's "spinal cord". It is deliberately DUMB:
 *
 *   it does      : turn a velocity command into wheel speeds, run a PID per
 *                  wheel, count encoder ticks, read the battery, and report
 *   it does NOT  : plan paths, hold a map, localise, know about missions,
 *                  know about the database, or talk to the website
 *
 * Everything in that second list lives on the Mac, in ROS. Keeping it out of
 * here is what makes the robot debuggable: any misbehaviour is either "the
 * wheels did not do what was asked" (firmware) or "the wrong thing was
 * asked" (ROS), never a tangle of both.
 *
 * PROTOCOL (see esp32_link.py for the host side)
 *   in : CMD,<lin>,<ang> | PING,<n> | RST | CFG,<key>,<val>
 *   out: ENC,<l>,<r>,<ms> | BAT,<v> | DIST,<cm> | PONG,<n> | VER,<s> | ERR,<s>
 *
 * Both the USB serial port and the Wi-Fi TCP socket speak this protocol at
 * the same time, so you can debug over USB while ROS drives over Wi-Fi.
 */

#include <Arduino.h>

#include "Encoder.h"
#include "Kinematics.h"
#include "Motor.h"
#include "PidController.h"
#include "Protocol.h"
#include "config.h"

#ifdef ENABLE_WIFI
#include <WiFi.h>
WiFiServer tcpServer(TCP_PORT);
WiFiClient tcpClient;
#endif

// ----------------------------------------------------------------- hardware
Motor leftMotor(PIN_LEFT_IN1, PIN_LEFT_IN2, PIN_LEFT_PWM, PWM_CHANNEL_L);
Motor rightMotor(PIN_RIGHT_IN1, PIN_RIGHT_IN2, PIN_RIGHT_PWM, PWM_CHANNEL_R);

Encoder leftEncoder(PIN_LEFT_ENC_A, PIN_LEFT_ENC_B, LEFT_ENCODER_SIGN);
Encoder rightEncoder(PIN_RIGHT_ENC_A, PIN_RIGHT_ENC_B, RIGHT_ENCODER_SIGN);

PidController leftPid(PID_KP, PID_KI, PID_KD, PID_FF, PWM_MAX);
PidController rightPid(PID_KP, PID_KI, PID_KD, PID_FF, PWM_MAX);

void IRAM_ATTR onLeftEncoder() { leftEncoder.handleInterrupt(); }
void IRAM_ATTR onRightEncoder() { rightEncoder.handleInterrupt(); }

// -------------------------------------------------------------------- state
float targetLinear = 0.0f;    // m/s
float targetAngular = 0.0f;   // rad/s

uint32_t lastCommandMs = 0;
uint32_t lastControlMs = 0;
uint32_t lastTelemetryMs = 0;
uint32_t lastBatteryMs = 0;
uint32_t lastRangeMs = 0;

int32_t prevLeftTicks = 0;
int32_t prevRightTicks = 0;

bool motorsEnabled = false;   // false = watchdog has cut the drive

String serialBuffer;
String tcpBuffer;

// ------------------------------------------------------------------ output
// Every reply goes to BOTH transports. Cheap, and it means the USB monitor
// always shows you exactly what ROS is seeing over Wi-Fi.
void emit(const String &line) {
  Serial.println(line);
#ifdef ENABLE_WIFI
  if (tcpClient && tcpClient.connected()) {
    tcpClient.println(line);
  }
#endif
}

// ------------------------------------------------------------ command input
void handleCommand(const char *raw) {
  protocol::ParsedCommand command;
  const bool ok = protocol::parse(raw, &command);

  if (!ok) {
    emit(command.type == protocol::CMD_MALFORMED ? "ERR,malformed command"
                                                 : "ERR,unknown verb");
    return;
  }

  switch (command.type) {
    case protocol::CMD_VELOCITY: {
      // Clamp here as well as on the host: the host limit protects against a
      // bad planner, this one against a corrupted packet.
      targetLinear = kinematics::clampf(command.linear, -MAX_LINEAR_MPS,
                                        MAX_LINEAR_MPS);
      targetAngular = kinematics::clampf(command.angular, -MAX_ANGULAR_RPS,
                                         MAX_ANGULAR_RPS);
      lastCommandMs = millis();
      if (!motorsEnabled) {
        // Coming back from a watchdog cut: clear stale integral so the robot
        // does not lurch on the first re-enabled cycle.
        leftPid.reset();
        rightPid.reset();
        motorsEnabled = true;
      }
      break;
    }

    case protocol::CMD_PING:
      emit("PONG," + String(command.seq));
      break;

    case protocol::CMD_RESET:
      leftEncoder.reset();
      rightEncoder.reset();
      prevLeftTicks = 0;
      prevRightTicks = 0;
      leftPid.reset();
      rightPid.reset();
      emit("LOG,encoders reset");
      break;

    case protocol::CMD_CONFIG: {
      // Live PID tuning with no reflash - invaluable during bringup.
      static float kp = PID_KP, ki = PID_KI, kd = PID_KD, ff = PID_FF;
      if (strcmp(command.key, "kp") == 0) kp = command.value;
      else if (strcmp(command.key, "ki") == 0) ki = command.value;
      else if (strcmp(command.key, "kd") == 0) kd = command.value;
      else if (strcmp(command.key, "ff") == 0) ff = command.value;
      else { emit("ERR,unknown CFG key"); return; }
      leftPid.setGains(kp, ki, kd, ff);
      rightPid.setGains(kp, ki, kd, ff);
      emit("LOG,gains kp=" + String(kp, 3) + " ki=" + String(ki, 3) +
           " kd=" + String(kd, 3) + " ff=" + String(ff, 2));
      break;
    }

    case protocol::CMD_NONE:
    default:
      break;
  }
}

// Read whatever bytes are available and dispatch COMPLETE lines only.
void pumpInput(Stream &stream, String &buffer) {
  while (stream.available()) {
    const char c = (char)stream.read();
    if (c == '\n') {
      handleCommand(buffer.c_str());
      buffer = "";
    } else if (c != '\r') {
      buffer += c;
      if (buffer.length() > 128) buffer = "";   // never grow without bound
    }
  }
}

// ------------------------------------------------------------- control loop
void runControlLoop(uint32_t now) {
  const float dt = (now - lastControlMs) / 1000.0f;
  lastControlMs = now;

  // Watchdog: the host has gone quiet, so stop. This is what saves the robot
  // when Wi-Fi drops or the Mac's battery dies mid-mission.
  if (now - lastCommandMs > CMD_WATCHDOG_MS) {
    if (motorsEnabled) {
      emit("ERR,command watchdog expired - motors stopped");
      motorsEnabled = false;
    }
    targetLinear = 0.0f;
    targetAngular = 0.0f;
    leftMotor.stop();
    rightMotor.stop();
    leftPid.reset();
    rightPid.reset();
    return;
  }

  const int32_t leftTicks = leftEncoder.read();
  const int32_t rightTicks = rightEncoder.read();
  const int32_t dLeft = leftTicks - prevLeftTicks;
  const int32_t dRight = rightTicks - prevRightTicks;
  prevLeftTicks = leftTicks;
  prevRightTicks = rightTicks;

  // Measured wheel speed, rad/s
  const float leftMeasured = kinematics::ticksToRadPerSecond(dLeft, TICKS_PER_REV, dt);
  const float rightMeasured = kinematics::ticksToRadPerSecond(dRight, TICKS_PER_REV, dt);

  float leftTarget, rightTarget;
  kinematics::bodyToWheelSpeeds(targetLinear, targetAngular, WHEEL_SEPARATION_M,
                                WHEEL_RADIUS_M, &leftTarget, &rightTarget);
  // Scale, do not clip: clipping each wheel separately would change the
  // commanded curvature and steer the robot off the planned path.
  kinematics::limitWheelSpeeds(&leftTarget, &rightTarget,
                               MAX_LINEAR_MPS / WHEEL_RADIUS_M);

  // An explicit zero command means STOP, not "PID your way to zero" - the
  // latter leaves the wheels twitching.
  if (leftTarget == 0.0f && rightTarget == 0.0f) {
    leftMotor.stop();
    rightMotor.stop();
    leftPid.reset();
    rightPid.reset();
    return;
  }

  const float leftOut = leftPid.update(leftTarget, leftMeasured, dt);
  const float rightOut = rightPid.update(rightTarget, rightMeasured, dt);

  leftMotor.setDuty((int)leftOut);
  rightMotor.setDuty((int)rightOut);
}

// ------------------------------------------------------------- telemetry
void sendEncoders(uint32_t now) {
  // Cumulative counts, not deltas: a dropped line then costs nothing,
  // because the next message still carries the absolute truth.
  emit("ENC," + String(leftEncoder.read()) + "," + String(rightEncoder.read()) +
       "," + String(now));
}

void sendBattery() {
#if ENABLE_BATTERY
  // Average a few samples - the ESP32 ADC is noisy enough that a single
  // read can wobble by 100 mV and trip a low-battery alarm spuriously.
  uint32_t total = 0;
  for (int i = 0; i < 8; ++i) total += analogRead(PIN_BATTERY_ADC);
  const float counts = total / 8.0f;
  const float volts = (counts / ADC_MAX_COUNTS) * ADC_REF_VOLTS *
                      BATTERY_DIVIDER * BATTERY_CALIBRATION;
  emit("BAT," + String(volts, 2));
#endif
}

void sendRange() {
#if ENABLE_ULTRASONIC
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  // 25 ms timeout ~ 4 m. Without a timeout a missing echo blocks the whole
  // control loop, which is how a sensor fault becomes a runaway robot.
  const unsigned long duration = pulseIn(PIN_ECHO, HIGH, 25000UL);
  if (duration > 0) {
    const float cm = duration / 58.0f;
    emit("DIST," + String(cm, 1));
  }
#endif
}

// ------------------------------------------------------------------- setup
void setup() {
  Serial.begin(115200);
  delay(100);

  leftMotor.begin();
  rightMotor.begin();
  leftMotor.stop();
  rightMotor.stop();

  leftEncoder.begin();
  rightEncoder.begin();
  attachInterrupt(digitalPinToInterrupt(PIN_LEFT_ENC_A), onLeftEncoder, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_RIGHT_ENC_A), onRightEncoder, CHANGE);

#if ENABLE_BATTERY
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_BATTERY_ADC, ADC_11db);   // full 0-3.3 V range
#endif

#if ENABLE_ULTRASONIC
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
#endif

#ifdef ENABLE_WIFI
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  const uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - started < WIFI_CONNECT_TIMEOUT_MS) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    // Print the IP prominently: this is the value you put into
    // hardware.yaml as esp32_ip.
    Serial.println("LOG,wifi connected");
    Serial.print("LOG,ip=");
    Serial.println(WiFi.localIP());
    tcpServer.begin();
    tcpServer.setNoDelay(true);
  } else {
    // Serial still works, so a failed Wi-Fi join is not fatal.
    Serial.println("ERR,wifi connect failed - serial only");
  }
#endif

  const uint32_t now = millis();
  lastCommandMs = now;
  lastControlMs = now;
  motorsEnabled = false;

  emit("VER," FIRMWARE_VERSION);
  emit("LOG,ready");
}

// -------------------------------------------------------------------- loop
void loop() {
  const uint32_t now = millis();

#ifdef ENABLE_WIFI
  if (!tcpClient || !tcpClient.connected()) {
    WiFiClient incoming = tcpServer.available();
    if (incoming) {
      // One controller at a time. A second connection would mean two
      // sources fighting over /cmd_vel.
      if (tcpClient) tcpClient.stop();
      tcpClient = incoming;
      tcpClient.setNoDelay(true);
      tcpBuffer = "";
      emit("VER," FIRMWARE_VERSION);
    }
  }
  if (tcpClient && tcpClient.connected()) {
    pumpInput(tcpClient, tcpBuffer);
  }
#endif

  pumpInput(Serial, serialBuffer);

  if (now - lastControlMs >= CONTROL_PERIOD_MS) {
    runControlLoop(now);
  }
  if (now - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    lastTelemetryMs = now;
    sendEncoders(now);
  }
  if (now - lastBatteryMs >= BATTERY_PERIOD_MS) {
    lastBatteryMs = now;
    sendBattery();
  }
  if (now - lastRangeMs >= RANGE_PERIOD_MS) {
    lastRangeMs = now;
    sendRange();
  }
}
