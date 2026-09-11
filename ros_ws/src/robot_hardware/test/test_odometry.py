"""
Unit tests for the odometry + protocol logic.

These run on macOS with plain pytest - no ROS, no robot:

    pip install pytest
    python3 -m pytest ros_ws/src/robot_hardware/test -v

Every test here encodes a bug that is painful to find on real hardware.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from robot_hardware.esp32_link import LoopbackLink  # noqa: E402
from robot_hardware.odometry import (DiffDriveOdometry,  # noqa: E402
                                     body_to_wheel_speeds)

TPR = 780.0
R = 0.0325
SEP = 0.16
CIRC = 2.0 * math.pi * R


def make_odom():
    return DiffDriveOdometry(TPR, R, SEP)


# --------------------------------------------------------------- straight line
def test_driving_straight_moves_x_by_wheel_circumference():
    odom = make_odom()
    odom.update(0, 0, 0.0)
    odom.update(int(TPR), int(TPR), 1.0)   # exactly one wheel revolution
    assert odom.x == pytest.approx(CIRC, abs=1e-6)
    assert odom.y == pytest.approx(0.0, abs=1e-9)
    assert odom.theta == pytest.approx(0.0, abs=1e-9)
    assert odom.linear_velocity == pytest.approx(CIRC, abs=1e-6)


def test_reversing_moves_x_negative():
    odom = make_odom()
    odom.update(0, 0, 0.0)
    odom.update(-int(TPR), -int(TPR), 1.0)
    assert odom.x == pytest.approx(-CIRC, abs=1e-6)


# ------------------------------------------------------------------- rotation
def test_spinning_in_place_does_not_translate():
    odom = make_odom()
    odom.update(0, 0, 0.0)
    odom.update(-100, 100, 1.0)            # wheels opposite => pure rotation
    assert odom.x == pytest.approx(0.0, abs=1e-9)
    assert odom.y == pytest.approx(0.0, abs=1e-9)
    assert odom.theta > 0.0                # right wheel forward => turn LEFT


def test_positive_angular_is_counter_clockwise():
    """ROS REP-103: +z rotation is counter-clockwise (left). Getting this
    backwards makes the robot turn away from every goal it is given."""
    odom = make_odom()
    odom.update(0, 0, 0.0)
    odom.update(-50, 50, 1.0)
    assert odom.angular_velocity > 0.0


def test_full_circle_of_wheel_rotation_matches_geometry():
    """Rotating in place by a known wheel distance must give the exact yaw:
        d_theta = (d_right - d_left) / wheel_separation
    """
    odom = make_odom()
    ticks = 200
    odom.update(0, 0, 0.0)
    odom.update(-ticks, ticks, 1.0)
    d_wheel = ticks * CIRC / TPR
    expected = (d_wheel - (-d_wheel)) / SEP
    assert odom.theta == pytest.approx(expected, abs=1e-6)


def test_theta_stays_normalised():
    odom = make_odom()
    odom.update(0, 0, 0.0)
    stamp = 0.0
    for _ in range(50):                    # spin a long way
        stamp += 0.1
        odom.update(-500 * int(stamp * 10), 500 * int(stamp * 10), stamp)
        assert -math.pi < odom.theta <= math.pi


# ---------------------------------------------------------------- arc motion
def test_arc_uses_exact_integration_not_straight_line_approximation():
    """Driving a quarter circle: the exact arc formula must land on the
    circle, while the naive x += d*cos(theta) version would undershoot."""
    odom = make_odom()
    odom.update(0, 0, 0.0)
    # right wheel travels further => left turn along an arc
    odom.update(int(TPR * 0.5), int(TPR * 1.5), 1.0)
    d_left = int(TPR * 0.5) * CIRC / TPR
    d_right = int(TPR * 1.5) * CIRC / TPR
    d_centre = (d_left + d_right) / 2.0
    d_theta = (d_right - d_left) / SEP
    radius = d_centre / d_theta
    assert odom.x == pytest.approx(radius * math.sin(d_theta), abs=1e-6)
    assert odom.y == pytest.approx(radius * (1 - math.cos(d_theta)), abs=1e-6)


# --------------------------------------------------------------- robustness
def test_first_sample_only_establishes_baseline():
    odom = make_odom()
    assert odom.update(5000, 5000, 0.0) is False   # must NOT jump the pose
    assert odom.pose == (0.0, 0.0, 0.0)


def test_encoder_wraparound_does_not_teleport_the_robot():
    """A 32-bit counter wrapping must read as a small forward step, not as
    4 billion ticks of instant travel."""
    odom = make_odom()
    odom.update(2147483600, 2147483600, 0.0)
    odom.update(-2147483648 + 47, -2147483648 + 47, 0.1)   # +95 ticks, wrapped
    expected = 95 * CIRC / TPR
    assert odom.x == pytest.approx(expected, abs=1e-6)


def test_duplicate_timestamp_is_ignored():
    odom = make_odom()
    odom.update(0, 0, 1.0)
    assert odom.update(100, 100, 1.0) is False     # dt == 0, would divide by zero


def test_absurd_gap_is_ignored():
    """A 5 s gap means we lost the link; integrating it would inject a huge
    bogus jump into /odom and destroy AMCL's pose estimate."""
    odom = make_odom()
    odom.update(0, 0, 0.0)
    assert odom.update(100000, 100000, 5.0) is False


def test_reset_clears_pose_and_baseline():
    odom = make_odom()
    odom.update(0, 0, 0.0)
    odom.update(500, 500, 1.0)
    odom.reset()
    assert odom.pose == (0.0, 0.0, 0.0)
    assert odom.update(9999, 9999, 2.0) is False   # baseline re-established


# --------------------------------------------------- inverse kinematics
def test_straight_command_drives_both_wheels_equally():
    left, right = body_to_wheel_speeds(0.3, 0.0, SEP, R)
    assert left == pytest.approx(right)
    assert left == pytest.approx(0.3 / R)


def test_pure_rotation_command_is_antisymmetric():
    left, right = body_to_wheel_speeds(0.0, 1.0, SEP, R)
    assert left == pytest.approx(-right)
    assert right > 0.0                       # +angular => right wheel forward


def test_kinematics_round_trip_through_odometry():
    """Command a velocity, integrate the resulting wheel motion, and confirm
    the odometry recovers the velocity that was commanded. This is the test
    that catches a wheel_separation mismatch between firmware and host."""
    lin, ang = 0.25, 0.6
    left_rad_s, right_rad_s = body_to_wheel_speeds(lin, ang, SEP, R)
    dt = 0.5
    left_ticks = int(left_rad_s / (2 * math.pi) * TPR * dt)
    right_ticks = int(right_rad_s / (2 * math.pi) * TPR * dt)

    odom = make_odom()
    odom.update(0, 0, 0.0)
    odom.update(left_ticks, right_ticks, dt)
    assert odom.linear_velocity == pytest.approx(lin, rel=0.01)
    assert odom.angular_velocity == pytest.approx(ang, rel=0.01)


# ------------------------------------------------------------ link framing
def test_link_reassembles_lines_split_across_reads():
    """TCP does not preserve message boundaries. A message arriving in two
    pieces must still parse as one line."""
    link = LoopbackLink(TPR, R, SEP)
    link.connect()
    link._buf = b"ENC,10,20,"          # simulate a truncated first packet
    link._outbox = ["100"]
    lines = link.read_lines()
    assert "ENC,10,20,100" in lines


def test_link_drops_garbage_without_unbounded_growth():
    link = LoopbackLink(TPR, R, SEP)
    link.connect()
    link._buf = b"X" * 9000            # a peer that never sends a newline
    link._outbox = []
    link.read_lines()
    assert len(link._buf) < 8192


def test_loopback_integrates_commanded_velocity_into_ticks():
    """The loopback ESP32 must move when commanded, so the bridge can be
    tested end to end with no hardware."""
    import time
    link = LoopbackLink(TPR, R, SEP)
    link.connect()
    link.send_velocity(0.2, 0.0)
    time.sleep(0.15)
    encs = [l for l in link.read_lines() if l.startswith("ENC")]
    assert encs, "loopback produced no encoder messages"
    left = int(encs[-1].split(",")[1])
    assert left > 0, "commanding forward must increase the left tick count"


def test_loopback_answers_ping():
    link = LoopbackLink(TPR, R, SEP)
    link.connect()
    link.send_ping(42)
    assert any(l == "PONG,42" for l in link.read_lines())
