/*
 * Kinematics.h - differential-drive maths, free of any hardware.
 *
 * Kept separate from main.cpp so it can be compiled and tested on a laptop
 * (see firmware/esp32_robot/test/) instead of only being "tested" by
 * watching a robot drive into a wall.
 *
 * THIS MUST STAY IDENTICAL TO
 *   ros_ws/src/robot_hardware/src/robot_hardware/odometry.py
 * The host integrates ticks into a pose using the same geometry the
 * firmware uses to turn a velocity into wheel speeds. If the two disagree
 * about wheel separation or radius, /odom drifts in a way that looks like
 * a navigation bug and is nearly impossible to find from the ROS side.
 */
#ifndef KINEMATICS_H
#define KINEMATICS_H

namespace kinematics {

inline float clampf(float value, float low, float high) {
  if (value < low) return low;
  if (value > high) return high;
  return value;
}

/*
 * Inverse kinematics: body velocity -> wheel angular speeds (rad/s).
 *
 *   v_left  = v - w * L/2        w_left  = v_left  / r
 *   v_right = v + w * L/2        w_right = v_right / r
 *
 * Sign convention (ROS REP-103): +linear is forward, +angular is
 * counter-clockwise, so a positive angular command drives the RIGHT wheel
 * faster and turns the robot LEFT.
 */
inline void bodyToWheelSpeeds(float linear, float angular, float wheelSeparation,
                              float wheelRadius, float *leftRadS, float *rightRadS) {
  const float vLeft = linear - angular * (wheelSeparation / 2.0f);
  const float vRight = linear + angular * (wheelSeparation / 2.0f);
  *leftRadS = vLeft / wheelRadius;
  *rightRadS = vRight / wheelRadius;
}

/*
 * Forward kinematics: wheel speeds -> body velocity. Used to report back
 * what the robot is ACTUALLY doing, as opposed to what it was told to do.
 */
inline void wheelSpeedsToBody(float leftRadS, float rightRadS,
                              float wheelSeparation, float wheelRadius,
                              float *linear, float *angular) {
  const float vLeft = leftRadS * wheelRadius;
  const float vRight = rightRadS * wheelRadius;
  *linear = (vLeft + vRight) / 2.0f;
  *angular = (vRight - vLeft) / wheelSeparation;
}

/*
 * Scale a command that would saturate a wheel back to what the drivetrain
 * can actually deliver, PRESERVING THE TURN RATIO.
 *
 * Why this matters: clamping each wheel independently changes the ratio
 * between them, which changes the robot's curvature. Asked to drive fast
 * around a tight arc, naive clamping makes the robot go straighter than
 * commanded - straight into the obstacle it was trying to curve around.
 * Scaling both wheels by the same factor keeps the path and only slows it.
 */
inline void limitWheelSpeeds(float *leftRadS, float *rightRadS, float maxRadS) {
  const float magLeft = (*leftRadS < 0) ? -*leftRadS : *leftRadS;
  const float magRight = (*rightRadS < 0) ? -*rightRadS : *rightRadS;
  const float peak = (magLeft > magRight) ? magLeft : magRight;
  if (peak > maxRadS && peak > 0.0f) {
    const float scale = maxRadS / peak;
    *leftRadS *= scale;
    *rightRadS *= scale;
  }
}

/*
 * Encoder tick delta -> wheel angular speed (rad/s).
 * Returns 0 for a non-positive dt rather than dividing by zero, because a
 * duplicated timestamp must not produce an infinite measured speed that
 * slams the PID.
 */
inline float ticksToRadPerSecond(long deltaTicks, float ticksPerRev, float dtSeconds) {
  if (dtSeconds <= 0.0f || ticksPerRev <= 0.0f) return 0.0f;
  const float revolutions = (float)deltaTicks / ticksPerRev;
  return revolutions * 6.28318530718f / dtSeconds;
}

}  // namespace kinematics

#endif  // KINEMATICS_H
