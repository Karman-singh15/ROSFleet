"""
Tests for hardware_bridge.py, run with fake ROS so they work on macOS.

    python3 -m pytest ros_ws/src/robot_hardware/test -v

These cover the behaviours that would otherwise only show up as a robot
driving into a wall.
"""

import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)

import ros_stubs  # noqa: E402

NODE = os.path.join(HERE, "..", "scripts", "hardware_bridge.py")

TPR, R, SEP = 780.0, 0.0325, 0.16
CIRC = 2.0 * math.pi * R


@pytest.fixture
def bridge():
    """A bridge wired to the in-process loopback ESP32."""
    rospy = ros_stubs.install({
        "transport": "loopback",
        "ticks_per_rev": TPR,
        "wheel_radius": R,
        "wheel_separation": SEP,
        "max_linear_velocity": 0.35,
        "max_angular_velocity": 1.5,
    })
    module = ros_stubs.load_node(NODE)
    rospy.Time.set_now(10.0)
    node = module.HardwareBridge()
    node._module = module
    node._rospy = rospy
    return node


def cmd(module, linear=0.0, angular=0.0):
    msg = sys.modules["geometry_msgs.msg"].Twist()
    msg.linear.x = linear
    msg.angular.z = angular
    return msg


# ------------------------------------------------------------- connection
def test_bridge_connects_and_reports_connected(bridge):
    assert bridge.connected is True
    assert bridge._rospy.Publisher.registry["hardware_connected"].last.data is True


# ---------------------------------------------------------------- commands
def test_cmd_vel_is_clamped_to_configured_limits(bridge):
    bridge.on_cmd_vel(cmd(bridge._module, linear=99.0, angular=-99.0))
    assert bridge.target_linear == pytest.approx(0.35)
    assert bridge.target_angular == pytest.approx(-1.5)


def test_cmd_vel_is_forwarded_to_the_esp32_as_a_CMD_line(bridge):
    bridge.on_cmd_vel(cmd(bridge._module, linear=0.2, angular=0.1))
    bridge.send_command(None)
    # LoopbackLink parses CMD lines into its own velocity state
    assert bridge.link._lin == pytest.approx(0.2)
    assert bridge.link._ang == pytest.approx(0.1)


def test_stale_cmd_vel_triggers_a_stop(bridge):
    """If the planner dies mid-drive the robot must stop, not keep going."""
    bridge.on_cmd_vel(cmd(bridge._module, linear=0.3))
    bridge.send_command(None)
    assert bridge.link._lin == pytest.approx(0.3)

    bridge._rospy.Time.set_now(bridge._rospy.Time.now().to_sec() + 5.0)
    bridge.send_command(None)
    assert bridge.link._lin == pytest.approx(0.0), "deadman did not stop the robot"


def test_shutdown_stops_the_motors(bridge):
    bridge.on_cmd_vel(cmd(bridge._module, linear=0.3))
    bridge.send_command(None)
    link = bridge.link
    bridge.shutdown()
    assert link._lin == pytest.approx(0.0)


# --------------------------------------------------------------- odometry
def test_encoder_messages_produce_odom_and_tf(bridge):
    bridge.handle_line("ENC,0,0,0")
    bridge.handle_line("ENC,%d,%d,1000" % (int(TPR), int(TPR)))

    odom = bridge._rospy.Publisher.registry["odom"].last
    assert odom is not None, "no /odom published"
    assert odom.pose.pose.position.x == pytest.approx(CIRC, abs=1e-6)
    assert odom.header.frame_id == "odom"
    assert odom.child_frame_id == "base_footprint"

    assert bridge.tf_broadcaster.sent, "no TF broadcast"
    tf = bridge.tf_broadcaster.sent[-1]
    assert tf.header.frame_id == "odom"
    assert tf.child_frame_id == "base_footprint"
    assert tf.transform.translation.x == pytest.approx(CIRC, abs=1e-6)


def test_odom_orientation_is_a_valid_unit_quaternion(bridge):
    bridge.handle_line("ENC,0,0,0")
    bridge.handle_line("ENC,-200,200,1000")
    q = bridge._rospy.Publisher.registry["odom"].last.pose.pose.orientation
    norm = math.sqrt(q.x ** 2 + q.y ** 2 + q.z ** 2 + q.w ** 2)
    assert norm == pytest.approx(1.0, abs=1e-9)
    assert q.z > 0.0                      # left turn


def test_covariance_marks_unmeasurable_axes_as_untrusted(bridge):
    """A diff drive cannot observe y/z/roll/pitch. If those covariances are
    small, AMCL believes them and the pose estimate collapses."""
    bridge.handle_line("ENC,0,0,0")
    bridge.handle_line("ENC,100,100,1000")
    cov = bridge._rospy.Publisher.registry["odom"].last.pose.covariance
    assert cov[0] < 1.0 and cov[7] < 1.0          # x, y measured-ish
    assert cov[14] > 1e5                          # z
    assert cov[21] > 1e5 and cov[28] > 1e5        # roll, pitch
    assert cov[35] < 1.0                          # yaw measured


def test_inverted_encoder_flag_flips_direction(bridge):
    bridge.invert_left = True
    bridge.invert_right = True
    bridge.handle_line("ENC,0,0,0")
    bridge.handle_line("ENC,%d,%d,1000" % (int(TPR), int(TPR)))
    assert bridge.odom.x == pytest.approx(-CIRC, abs=1e-6)


def test_joint_states_are_published_for_rviz(bridge):
    bridge.handle_line("ENC,0,0,0")
    bridge.handle_line("ENC,100,100,1000")
    js = bridge._rospy.Publisher.registry["joint_states"].last
    assert js.name == ["left_wheel_joint", "right_wheel_joint"]
    assert len(js.position) == 2


# -------------------------------------------------------------- telemetry
def test_battery_voltage_maps_to_percent(bridge):
    bridge.handle_line("BAT,8.4")
    assert bridge.battery_percent() == pytest.approx(100.0)
    bridge.handle_line("BAT,6.6")
    assert bridge.battery_percent() == pytest.approx(0.0)
    bridge.handle_line("BAT,7.5")
    assert bridge.battery_percent() == pytest.approx(50.0)


def test_battery_percent_is_clamped_outside_the_range(bridge):
    bridge.handle_line("BAT,9.9")
    assert bridge.battery_percent() == pytest.approx(100.0)
    bridge.handle_line("BAT,3.0")
    assert bridge.battery_percent() == pytest.approx(0.0)


def test_distance_message_becomes_a_range_topic_in_metres(bridge):
    bridge.handle_line("DIST,42")                  # centimetres on the wire
    rng = bridge._rospy.Publisher.registry["front_range"].last
    assert rng.range == pytest.approx(0.42)
    assert bridge.front_distance == pytest.approx(0.42)


def test_firmware_version_and_errors_are_captured(bridge):
    bridge.handle_line("VER,esp32-1.2.0")
    bridge.handle_line("ERR,motor driver fault")
    assert bridge.firmware_version == "esp32-1.2.0"
    assert bridge.last_error == "motor driver fault"


def test_telemetry_message_carries_the_full_robot_state(bridge):
    bridge.handle_line("VER,esp32-1.2.0")
    bridge.handle_line("BAT,7.5")
    bridge.handle_line("ENC,0,0,0")
    bridge.handle_line("ENC,200,200,1000")
    bridge.publish_telemetry(None)
    tel = bridge._rospy.Publisher.registry["robot_telemetry"].last
    assert tel.connected is True
    assert tel.battery_percent == pytest.approx(50.0)
    assert tel.left_ticks == 200
    assert tel.firmware_version == "esp32-1.2.0"


# ------------------------------------------------------------ robustness
def test_malformed_lines_do_not_crash_the_node(bridge):
    for junk in ["", "ENC", "ENC,a,b,c", "BAT,", "DIST,xyz", "???", "ENC,1,2"]:
        bridge.handle_line(junk)        # must not raise
    assert bridge.connected is True


def test_partial_encoder_line_is_ignored_not_half_applied(bridge):
    bridge.handle_line("ENC,0,0,0")
    bridge.handle_line("ENC,500,500")   # truncated: missing timestamp
    assert bridge.odom.pose == (0.0, 0.0, 0.0)


def test_link_loss_is_detected_and_reported(bridge):
    bridge.link.close()
    bridge.link.connected = False
    bridge.publish_telemetry(None)
    assert bridge._rospy.Publisher.registry["hardware_connected"].last.data is False
