"""
odometry.py - differential-drive dead reckoning.

Deliberately pure Python with no ROS imports so it can be unit-tested on your
Mac without a ROS installation:

    python3 -m pytest ros_ws/src/robot_hardware/test/

THE MATH
--------
Each wheel's travelled distance comes from encoder counts:

    d_wheel = 2*pi*r * (ticks / ticks_per_rev)

For a differential drive:

    d_centre = (d_left + d_right) / 2
    d_theta  = (d_right - d_left) / wheel_separation

Then integrate the pose. We use the exact arc (not the straight-line
approximation) when the robot is turning, which matters a lot on tight
indoor turns where the naive version drifts noticeably:

    if |d_theta| < eps:      # essentially straight
        x += d_centre * cos(theta)
        y += d_centre * sin(theta)
    else:                    # arc of radius R = d_centre / d_theta
        R = d_centre / d_theta
        x += R * (sin(theta + d_theta) - sin(theta))
        y -= R * (cos(theta + d_theta) - cos(theta))
    theta += d_theta

SIGN CONVENTIONS (get these wrong and the robot drives away from goals)
    +linear.x  = forward
    +angular.z = counter-clockwise seen from above (left turn)
    +left tick = left wheel rotating forward
"""

import math


class DiffDriveOdometry(object):
    def __init__(self, ticks_per_rev, wheel_radius, wheel_separation,
                 encoder_min=-2147483648, encoder_max=2147483647):
        self.ticks_per_rev = float(ticks_per_rev)
        self.wheel_radius = float(wheel_radius)
        self.wheel_separation = float(wheel_separation)
        self.encoder_min = encoder_min
        self.encoder_max = encoder_max

        self.metres_per_tick = (2.0 * math.pi * self.wheel_radius) / self.ticks_per_rev

        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0
        self.linear_velocity = 0.0
        self.angular_velocity = 0.0
        self.left_wheel_rps = 0.0
        self.right_wheel_rps = 0.0

        self._have_prev = False
        self._prev_left = 0
        self._prev_right = 0
        self._prev_stamp = 0.0

    def reset(self, x=0.0, y=0.0, theta=0.0):
        self.x, self.y, self.theta = x, y, theta
        self.linear_velocity = self.angular_velocity = 0.0
        self._have_prev = False

    def _tick_delta(self, prev, curr):
        """Delta that survives a 32-bit counter wrapping around."""
        span = self.encoder_max - self.encoder_min + 1
        delta = curr - prev
        if delta > span / 2:
            delta -= span
        elif delta < -span / 2:
            delta += span
        return delta

    def update(self, left_ticks, right_ticks, stamp):
        """Feed one ENC message. `stamp` is seconds (the ESP32's own clock).

        Returns True if the pose was updated, False for the first sample
        (which only establishes a baseline).
        """
        if not self._have_prev:
            self._prev_left = left_ticks
            self._prev_right = right_ticks
            self._prev_stamp = stamp
            self._have_prev = True
            return False

        dt = stamp - self._prev_stamp
        d_left_ticks = self._tick_delta(self._prev_left, left_ticks)
        d_right_ticks = self._tick_delta(self._prev_right, right_ticks)

        self._prev_left = left_ticks
        self._prev_right = right_ticks
        self._prev_stamp = stamp

        # Out-of-order or duplicate timestamp: skip rather than divide by ~0.
        if dt <= 1e-6 or dt > 1.0:
            return False

        d_left = d_left_ticks * self.metres_per_tick
        d_right = d_right_ticks * self.metres_per_tick

        d_centre = (d_left + d_right) / 2.0
        d_theta = (d_right - d_left) / self.wheel_separation

        if abs(d_theta) < 1e-6:
            self.x += d_centre * math.cos(self.theta)
            self.y += d_centre * math.sin(self.theta)
        else:
            radius = d_centre / d_theta
            self.x += radius * (math.sin(self.theta + d_theta) - math.sin(self.theta))
            self.y -= radius * (math.cos(self.theta + d_theta) - math.cos(self.theta))
        self.theta = _normalize_angle(self.theta + d_theta)

        self.linear_velocity = d_centre / dt
        self.angular_velocity = d_theta / dt
        circumference = 2.0 * math.pi * self.wheel_radius
        self.left_wheel_rps = (d_left / circumference) / dt
        self.right_wheel_rps = (d_right / circumference) / dt
        return True

    @property
    def pose(self):
        return (self.x, self.y, self.theta)


def body_to_wheel_speeds(linear, angular, wheel_separation, wheel_radius):
    """Inverse kinematics: /cmd_vel -> per-wheel speed.

    The ESP32 firmware does exactly this same computation; it lives here too
    so the loopback simulator and any host-side checks agree with the board.
    Returns (left_rad_s, right_rad_s).
    """
    v_left = linear - angular * wheel_separation / 2.0
    v_right = linear + angular * wheel_separation / 2.0
    return v_left / wheel_radius, v_right / wheel_radius


def _normalize_angle(angle):
    """Wrap to (-pi, pi] so theta never grows unbounded."""
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle <= -math.pi:
        angle += 2.0 * math.pi
    return angle
