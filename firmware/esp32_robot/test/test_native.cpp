/*
 * Native tests for the hardware-independent firmware logic.
 *
 * Build and run on your Mac - no ESP32 required:
 *     ./scripts/test_firmware.sh
 *
 * Covers the parser, the kinematics and the PID guards. Everything these
 * catch would otherwise only show up as a robot behaving strangely on a
 * desk, which is a far slower way to find a sign error.
 */

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>

#include "../src/Kinematics.h"
#include "../src/PidController.h"
#include "../src/Protocol.h"

static int g_failures = 0;
static int g_checks = 0;

static void check(bool condition, const char *what) {
  ++g_checks;
  if (!condition) {
    ++g_failures;
    std::printf("  FAIL  %s\n", what);
  }
}

static void checkClose(float actual, float expected, float tolerance,
                       const char *what) {
  ++g_checks;
  if (std::fabs(actual - expected) > tolerance) {
    ++g_failures;
    std::printf("  FAIL  %s (got %.6f, expected %.6f)\n", what, actual, expected);
  }
}

static void section(const char *name) { std::printf("\n%s\n", name); }

// ============================================================== protocol
static void testProtocol() {
  section("protocol parser");
  protocol::ParsedCommand cmd;

  check(protocol::parse("CMD,0.300,-0.150", &cmd), "valid CMD parses");
  check(cmd.type == protocol::CMD_VELOCITY, "CMD yields CMD_VELOCITY");
  checkClose(cmd.linear, 0.300f, 1e-5f, "linear parsed");
  checkClose(cmd.angular, -0.150f, 1e-5f, "angular parsed");

  check(protocol::parse("CMD,0.1,0\r\n", &cmd), "trailing CRLF tolerated");
  checkClose(cmd.angular, 0.0f, 1e-6f, "zero angular parsed after trim");

  // The important one: a truncated command must be REJECTED, never
  // half-applied as "drive forward, turn by garbage".
  check(!protocol::parse("CMD,0.3", &cmd), "truncated CMD is rejected");
  check(cmd.type == protocol::CMD_MALFORMED, "truncated CMD is MALFORMED");

  check(!protocol::parse("CMD,abc,def", &cmd), "non-numeric CMD is rejected");
  check(cmd.type == protocol::CMD_MALFORMED, "non-numeric CMD is MALFORMED");
  check(!protocol::parse("CMD,,", &cmd), "empty fields rejected");

  check(protocol::parse("PING,77", &cmd) && cmd.type == protocol::CMD_PING,
        "PING parses");
  check(cmd.seq == 77, "ping sequence preserved");

  check(protocol::parse("RST", &cmd) && cmd.type == protocol::CMD_RESET,
        "RST parses");

  check(protocol::parse("CFG,kp,1.25", &cmd) && cmd.type == protocol::CMD_CONFIG,
        "CFG parses");
  check(std::strcmp(cmd.key, "kp") == 0, "CFG key preserved");
  checkClose(cmd.value, 1.25f, 1e-5f, "CFG value preserved");
  check(!protocol::parse("CFG,kp", &cmd), "CFG without value rejected");

  check(protocol::parse("", &cmd) && cmd.type == protocol::CMD_NONE,
        "empty line is a no-op");
  check(protocol::parse("   \r\n", &cmd) && cmd.type == protocol::CMD_NONE,
        "whitespace line is a no-op");
  check(!protocol::parse("FLY,1,2", &cmd) && cmd.type == protocol::CMD_UNKNOWN,
        "unknown verb reported");

  // A hostile / corrupted long line must not overflow the 128-byte buffer.
  std::string huge = "CMD,";
  huge.append(5000, '9');
  huge.append(",0.1");
  protocol::parse(huge.c_str(), &cmd);
  check(true, "oversized line does not crash");
}

// ============================================================ kinematics
static void testKinematics() {
  section("kinematics");
  const float sep = 0.160f, radius = 0.0325f;
  float left = 0.0f, right = 0.0f;

  kinematics::bodyToWheelSpeeds(0.3f, 0.0f, sep, radius, &left, &right);
  checkClose(left, right, 1e-6f, "straight drives both wheels equally");
  checkClose(left, 0.3f / radius, 1e-4f, "straight wheel speed = v/r");

  kinematics::bodyToWheelSpeeds(0.0f, 1.0f, sep, radius, &left, &right);
  checkClose(left, -right, 1e-6f, "spin is antisymmetric");
  // REP-103: +angular is counter-clockwise, so the RIGHT wheel goes forward.
  check(right > 0.0f, "+angular drives right wheel forward (turns left)");

  kinematics::bodyToWheelSpeeds(0.0f, 0.0f, sep, radius, &left, &right);
  checkClose(left, 0.0f, 1e-9f, "zero command = zero left");
  checkClose(right, 0.0f, 1e-9f, "zero command = zero right");

  // Round trip must be lossless, otherwise firmware and host disagree.
  float linear = 0.0f, angular = 0.0f;
  kinematics::bodyToWheelSpeeds(0.25f, 0.6f, sep, radius, &left, &right);
  kinematics::wheelSpeedsToBody(left, right, sep, radius, &linear, &angular);
  checkClose(linear, 0.25f, 1e-5f, "round trip preserves linear");
  checkClose(angular, 0.6f, 1e-5f, "round trip preserves angular");

  // Saturation must preserve curvature, not flatten the turn.
  left = 40.0f;
  right = 20.0f;
  const float ratioBefore = left / right;
  kinematics::limitWheelSpeeds(&left, &right, 10.0f);
  checkClose(left / right, ratioBefore, 1e-4f,
             "saturation preserves the turn ratio");
  checkClose(left, 10.0f, 1e-4f, "saturation clamps the peak wheel");
  check(right < 10.0f, "saturation scales the slower wheel down too");

  left = 2.0f;
  right = 1.0f;
  kinematics::limitWheelSpeeds(&left, &right, 10.0f);
  checkClose(left, 2.0f, 1e-6f, "under the limit is left untouched");

  left = -40.0f;
  right = -20.0f;
  kinematics::limitWheelSpeeds(&left, &right, 10.0f);
  checkClose(left, -10.0f, 1e-4f, "saturation works in reverse too");

  checkClose(kinematics::ticksToRadPerSecond(780, 780.0f, 1.0f),
             6.28318530718f, 1e-4f, "one rev per second = 2*pi rad/s");
  checkClose(kinematics::ticksToRadPerSecond(100, 780.0f, 0.0f), 0.0f, 1e-9f,
             "zero dt yields zero, not infinity");
  checkClose(kinematics::ticksToRadPerSecond(-780, 780.0f, 1.0f),
             -6.28318530718f, 1e-4f, "negative ticks give negative speed");
}

// =================================================================== PID
static void testPid() {
  section("PID controller");

  // Feedforward alone must produce output on the very first cycle, with no
  // accumulated error - that is the whole point of having it.
  PidController feedforwardOnly(0.0f, 0.0f, 0.0f, 38.0f, 1023.0f);
  const float out = feedforwardOnly.update(5.0f, 0.0f, 0.02f);
  checkClose(out, 190.0f, 1e-3f, "feedforward acts immediately");

  // Anti-windup: a stalled wheel must not bank unbounded integral.
  PidController stalled(0.0f, 2.5f, 0.0f, 0.0f, 1023.0f);
  for (int i = 0; i < 2000; ++i) stalled.update(10.0f, 0.0f, 0.02f);
  const float saturated = stalled.update(10.0f, 0.0f, 0.02f);
  check(saturated <= 1023.0f + 1e-3f, "output respects the limit");
  // Now the wheel comes free and overshoots. Without anti-windup the
  // controller would stay pinned for seconds; it must recover quickly.
  float recovered = saturated;
  for (int i = 0; i < 50; ++i) recovered = stalled.update(0.0f, 10.0f, 0.02f);
  check(recovered < saturated, "controller recovers after a stall");

  PidController controller(0.6f, 2.5f, 0.0f, 38.0f, 1023.0f);
  controller.update(5.0f, 0.0f, 0.02f);
  controller.reset();
  checkClose(controller.update(0.0f, 0.0f, 0.02f), 0.0f, 1e-6f,
             "reset clears the integral");

  // Output must be symmetric: driving backwards is not a special case.
  PidController symmetric(0.6f, 0.0f, 0.0f, 38.0f, 1023.0f);
  const float forward = symmetric.update(5.0f, 0.0f, 0.02f);
  symmetric.reset();
  const float reverse = symmetric.update(-5.0f, 0.0f, 0.02f);
  checkClose(forward, -reverse, 1e-4f, "forward and reverse are symmetric");

  // A zero dt must not produce NaN/inf from the derivative term.
  PidController derivative(0.0f, 0.0f, 1.0f, 0.0f, 1023.0f);
  derivative.update(1.0f, 0.0f, 0.02f);
  const float safe = derivative.update(1.0f, 0.0f, 0.0f);
  check(std::isfinite(safe), "zero dt does not produce NaN or inf");
}

// ======================================== firmware/host agreement check
static void testFirmwareMatchesHostGeometry() {
  section("firmware <-> host consistency");
  // These MUST equal the values in ros_ws/.../config/hardware.yaml.
  // scripts/check_geometry_sync.py enforces it automatically; this is the
  // in-firmware restatement so a reader of this file sees the coupling.
  const float sep = 0.160f, radius = 0.0325f, ticksPerRev = 780.0f;

  // Simulate: command a velocity, integrate the wheel motion into ticks the
  // way the ESP32 would, then recover the body velocity the way the host's
  // odometry.py does. They must agree.
  const float linear = 0.25f, angular = 0.6f, dt = 0.5f;
  float left = 0.0f, right = 0.0f;
  kinematics::bodyToWheelSpeeds(linear, angular, sep, radius, &left, &right);

  const long leftTicks = (long)(left / 6.28318530718f * ticksPerRev * dt);
  const long rightTicks = (long)(right / 6.28318530718f * ticksPerRev * dt);

  const float leftMeasured = kinematics::ticksToRadPerSecond(leftTicks, ticksPerRev, dt);
  const float rightMeasured = kinematics::ticksToRadPerSecond(rightTicks, ticksPerRev, dt);

  float recoveredLinear = 0.0f, recoveredAngular = 0.0f;
  kinematics::wheelSpeedsToBody(leftMeasured, rightMeasured, sep, radius,
                                &recoveredLinear, &recoveredAngular);
  checkClose(recoveredLinear, linear, 0.005f, "commanded linear survives the loop");
  checkClose(recoveredAngular, angular, 0.02f, "commanded angular survives the loop");
}

int main() {
  std::printf("ESP32 firmware native tests\n===========================");
  testProtocol();
  testKinematics();
  testPid();
  testFirmwareMatchesHostGeometry();

  std::printf("\n---------------------------\n");
  if (g_failures == 0) {
    std::printf("PASS: %d checks\n", g_checks);
    return 0;
  }
  std::printf("FAIL: %d of %d checks failed\n", g_failures, g_checks);
  return 1;
}
