#!/usr/bin/env python
"""
hardware_bridge.py - the ONLY node that talks to the physical robot.

    ROS world                         |  embedded world
    ----------------------------------+-----------------------------
    /cmd_vel   (Twist)       ------>  |  CMD,<lin>,<ang>
    /odom      (Odometry)    <------  |  ENC,<l>,<r>,<ms>
    /joint_states            <------  |  ENC
    /robot_telemetry         <------  |  BAT / DIST / ERR
    TF odom -> base_footprint <-----  |  ENC
    /hardware_connected (Bool) <----  |  link state

Everything above this node (move_base, AMCL, mission_manager, the backend,
the website) is written against those ROS topics and has no idea an ESP32
exists. Swap the ESP32 for an STM32 or a Pi Pico and only this file plus the
firmware change.

Run it:
    rosrun robot_hardware hardware_bridge.py _transport:=loopback
    roslaunch robot_hardware hardware.launch transport:=serial
"""

import math

import rospy
import tf2_ros
from geometry_msgs.msg import Quaternion, TransformStamped, Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState, Range
from std_msgs.msg import Bool

from robot_hardware.esp32_link import LinkError, make_link
from robot_hardware.msg import RobotTelemetry
from robot_hardware.odometry import DiffDriveOdometry


def yaw_to_quaternion(yaw):
    return Quaternion(x=0.0, y=0.0, z=math.sin(yaw / 2.0), w=math.cos(yaw / 2.0))


class HardwareBridge(object):

    def __init__(self):
        self.transport = rospy.get_param("~transport", "loopback")
        self.params = {
            "transport": self.transport,
            "serial_port": rospy.get_param("~serial_port", "/dev/ttyUSB0"),
            "baud_rate": rospy.get_param("~baud_rate", 115200),
            "esp32_ip": rospy.get_param("~esp32_ip", "192.168.1.50"),
            "esp32_port": rospy.get_param("~esp32_port", 9000),
            "ticks_per_rev": rospy.get_param("~ticks_per_rev", 780.0),
            "wheel_radius": rospy.get_param("~wheel_radius", 0.0325),
            "wheel_separation": rospy.get_param("~wheel_separation", 0.16),
        }

        self.wheel_radius = float(self.params["wheel_radius"])
        self.wheel_separation = float(self.params["wheel_separation"])
        self.max_linear = rospy.get_param("~max_linear_velocity", 0.35)
        self.max_angular = rospy.get_param("~max_angular_velocity", 1.5)

        self.cmd_timeout = rospy.get_param("~cmd_timeout", 0.5)     # s
        self.cmd_rate = rospy.get_param("~cmd_rate", 20.0)          # Hz
        self.link_timeout = rospy.get_param("~link_timeout", 1.0)   # s without rx
        self.publish_tf = rospy.get_param("~publish_tf", True)
        self.invert_left = rospy.get_param("~invert_left_encoder", False)
        self.invert_right = rospy.get_param("~invert_right_encoder", False)

        self.odom_frame = rospy.get_param("~odom_frame", "odom")
        self.base_frame = rospy.get_param("~base_frame", "base_footprint")

        self.battery_full = rospy.get_param("~battery_full_voltage", 8.4)
        self.battery_empty = rospy.get_param("~battery_empty_voltage", 6.6)
        self.battery_warn = rospy.get_param("~battery_warn_percent", 20.0)

        # Dead reckoning is confident about motion it measured and clueless
        # about sideways slip, so y/z/roll/pitch get huge variances. AMCL
        # reads these to decide how much to trust /odom between scans.
        self.pose_covariance = rospy.get_param(
            "~pose_covariance", [0.02, 0.02, 1e6, 1e6, 1e6, 0.08])
        self.twist_covariance = rospy.get_param(
            "~twist_covariance", [0.02, 0.02, 1e6, 1e6, 1e6, 0.08])

        self.odom = DiffDriveOdometry(self.params["ticks_per_rev"],
                                      self.wheel_radius, self.wheel_separation)
        self.link = None
        self.target_linear = 0.0
        self.target_angular = 0.0
        self.last_cmd_time = rospy.Time(0)
        self.last_rx_time = rospy.Time(0)
        self.last_reconnect = rospy.Time(0)
        self.ping_seq = 0
        self.ping_sent_at = {}
        self.link_latency_ms = 0.0
        self.battery_voltage = float("nan")
        self.front_distance = -1.0
        self.left_ticks = 0
        self.right_ticks = 0
        self.firmware_version = "unknown"
        self.last_error = ""
        self.low_battery_warned = False
        self.left_wheel_angle = 0.0
        self.right_wheel_angle = 0.0

        self.odom_pub = rospy.Publisher("odom", Odometry, queue_size=10)
        self.joint_pub = rospy.Publisher("joint_states", JointState, queue_size=10)
        self.telemetry_pub = rospy.Publisher("robot_telemetry", RobotTelemetry,
                                             queue_size=5)
        self.connected_pub = rospy.Publisher("hardware_connected", Bool,
                                             queue_size=1, latch=True)
        self.range_pub = rospy.Publisher("front_range", Range, queue_size=5)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster()

        rospy.Subscriber("cmd_vel", Twist, self.on_cmd_vel, queue_size=1)

        rospy.loginfo("hardware_bridge: transport=%s wheel_sep=%.3f r=%.4f tpr=%.1f",
                      self.transport, self.wheel_separation, self.wheel_radius,
                      self.params["ticks_per_rev"])
        self.connect()

    # ------------------------------------------------------------------ link
    def connect(self):
        try:
            self.link = make_link(self.params)
            self.link.connect()
            self.link.send_reset()
            self.odom.reset()
            self.last_rx_time = rospy.Time.now()
            self.last_error = ""
            self.publish_connected(True)
            rospy.loginfo("hardware_bridge: link up (%s)", self.transport)
        except Exception as exc:
            self.last_error = str(exc)
            rospy.logwarn_throttle(5.0, "hardware_bridge: connect failed: %s", exc)
            self.publish_connected(False)

    @property
    def connected(self):
        return self.link is not None and self.link.connected

    def publish_connected(self, value):
        self.connected_pub.publish(Bool(data=bool(value)))

    def maybe_reconnect(self):
        now = rospy.Time.now()
        if (now - self.last_reconnect).to_sec() < 2.0:
            return
        self.last_reconnect = now
        rospy.logwarn_throttle(5.0, "hardware_bridge: reconnecting to ESP32...")
        self.connect()

    # -------------------------------------------------------------- commands
    def on_cmd_vel(self, msg):
        """Clamp and remember. The send happens on a fixed-rate timer so a
        chatty local planner cannot flood a 115200 baud serial link."""
        self.target_linear = max(-self.max_linear, min(self.max_linear, msg.linear.x))
        self.target_angular = max(-self.max_angular, min(self.max_angular, msg.angular.z))
        self.last_cmd_time = rospy.Time.now()

    def send_command(self, _event):
        if not self.connected:
            return
        # Deadman. The firmware has its own watchdog as well - a runaway robot
        # on a dead link is the classic way to destroy a chassis.
        age = (rospy.Time.now() - self.last_cmd_time).to_sec()
        if age > self.cmd_timeout:
            linear = angular = 0.0
        else:
            linear, angular = self.target_linear, self.target_angular
        try:
            self.link.send_velocity(linear, angular)
            self.ping_seq = (self.ping_seq + 1) % 10000
            if self.ping_seq % 20 == 0:
                self.ping_sent_at[self.ping_seq] = rospy.Time.now()
                self.link.send_ping(self.ping_seq)
        except LinkError as exc:
            self.last_error = str(exc)
            self.publish_connected(False)

    # ------------------------------------------------------------- rx + odom
    def poll(self, _event):
        if not self.connected:
            self.maybe_reconnect()
            return
        try:
            lines = self.link.read_lines()
        except LinkError as exc:
            self.last_error = str(exc)
            rospy.logwarn("hardware_bridge: link lost: %s", exc)
            self.publish_connected(False)
            return

        for line in lines:
            self.handle_line(line)

        now = rospy.Time.now()
        if lines:
            self.last_rx_time = now
        elif (now - self.last_rx_time).to_sec() > self.link_timeout:
            rospy.logwarn_throttle(5.0, "hardware_bridge: no data from ESP32 for %.1fs",
                                   (now - self.last_rx_time).to_sec())
            self.last_error = "no telemetry from ESP32"
            self.publish_connected(False)
            self.link.close()

    def handle_line(self, line):
        parts = line.split(",")
        kind = parts[0]
        try:
            if kind == "ENC" and len(parts) >= 4:
                self.handle_encoders(int(parts[1]), int(parts[2]), int(parts[3]))
            elif kind == "BAT" and len(parts) >= 2:
                self.battery_voltage = float(parts[1])
                self.check_battery()
            elif kind == "DIST" and len(parts) >= 2:
                self.handle_range(float(parts[1]) / 100.0)
            elif kind == "PONG" and len(parts) >= 2:
                sent = self.ping_sent_at.pop(int(parts[1]), None)
                if sent is not None:
                    self.link_latency_ms = (rospy.Time.now() - sent).to_sec() * 1000.0
            elif kind == "VER" and len(parts) >= 2:
                self.firmware_version = parts[1]
                rospy.loginfo("hardware_bridge: ESP32 firmware %s", parts[1])
            elif kind == "ERR":
                self.last_error = ",".join(parts[1:])
                rospy.logerr("ESP32 error: %s", self.last_error)
            elif kind == "LOG":
                rospy.loginfo("ESP32: %s", ",".join(parts[1:]))
            else:
                rospy.logdebug("hardware_bridge: ignoring %r", line)
        except ValueError:
            rospy.logwarn_throttle(5.0, "hardware_bridge: malformed line %r", line)

    def handle_encoders(self, left, right, millis):
        if self.invert_left:
            left = -left
        if self.invert_right:
            right = -right
        self.left_ticks, self.right_ticks = left, right

        # Timestamped by the ESP32 itself, so Wi-Fi jitter cannot distort the
        # velocity estimate.
        if not self.odom.update(left, right, millis / 1000.0):
            return

        now = rospy.Time.now()
        self.publish_odometry(now)
        self.publish_joint_states(now)

    def publish_odometry(self, stamp):
        x, y, theta = self.odom.pose
        quat = yaw_to_quaternion(theta)

        msg = Odometry()
        msg.header.stamp = stamp
        msg.header.frame_id = self.odom_frame
        msg.child_frame_id = self.base_frame
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation = quat
        msg.twist.twist.linear.x = self.odom.linear_velocity
        msg.twist.twist.angular.z = self.odom.angular_velocity
        for i in range(6):
            msg.pose.covariance[i * 7] = self.pose_covariance[i]
            msg.twist.covariance[i * 7] = self.twist_covariance[i]
        self.odom_pub.publish(msg)

        if self.publish_tf:
            tf_msg = TransformStamped()
            tf_msg.header.stamp = stamp
            tf_msg.header.frame_id = self.odom_frame
            tf_msg.child_frame_id = self.base_frame
            tf_msg.transform.translation.x = x
            tf_msg.transform.translation.y = y
            tf_msg.transform.rotation = quat
            self.tf_broadcaster.sendTransform(tf_msg)

    def publish_joint_states(self, stamp):
        """Spins the wheels in RViz. Cosmetic, but it is also the fastest way
        to spot an inverted encoder: a wheel turning backwards in RViz while
        the robot drives forward means invert_*_encoder is set wrong."""
        dt = 1.0 / max(self.cmd_rate, 1.0)
        self.left_wheel_angle += self.odom.left_wheel_rps * 2.0 * math.pi * dt
        self.right_wheel_angle += self.odom.right_wheel_rps * 2.0 * math.pi * dt

        js = JointState()
        js.header.stamp = stamp
        js.name = ["left_wheel_joint", "right_wheel_joint"]
        js.position = [self.left_wheel_angle, self.right_wheel_angle]
        js.velocity = [self.odom.left_wheel_rps * 2.0 * math.pi,
                       self.odom.right_wheel_rps * 2.0 * math.pi]
        self.joint_pub.publish(js)

    def handle_range(self, metres):
        self.front_distance = metres
        msg = Range()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = "base_link"
        msg.radiation_type = Range.ULTRASOUND
        msg.field_of_view = 0.26
        msg.min_range = 0.02
        msg.max_range = 4.0
        msg.range = metres
        self.range_pub.publish(msg)

    # ------------------------------------------------------------- telemetry
    def battery_percent(self):
        if math.isnan(self.battery_voltage):
            return float("nan")
        span = self.battery_full - self.battery_empty
        pct = 100.0 * (self.battery_voltage - self.battery_empty) / span
        return max(0.0, min(100.0, pct))

    def check_battery(self):
        pct = self.battery_percent()
        if math.isnan(pct):
            return
        if pct < self.battery_warn and not self.low_battery_warned:
            self.low_battery_warned = True
            rospy.logwarn("hardware_bridge: LOW BATTERY %.0f%% (%.2f V)",
                          pct, self.battery_voltage)
        elif pct > self.battery_warn + 5.0:
            self.low_battery_warned = False

    def publish_telemetry(self, _event):
        msg = RobotTelemetry()
        msg.header.stamp = rospy.Time.now()
        msg.connected = self.connected
        msg.battery_voltage = self.battery_voltage
        msg.battery_percent = self.battery_percent()
        msg.left_ticks = self.left_ticks
        msg.right_ticks = self.right_ticks
        msg.left_wheel_rps = self.odom.left_wheel_rps
        msg.right_wheel_rps = self.odom.right_wheel_rps
        msg.front_distance = self.front_distance
        msg.link_latency_ms = self.link_latency_ms
        msg.firmware_version = self.firmware_version
        msg.last_error = self.last_error
        self.telemetry_pub.publish(msg)
        self.publish_connected(self.connected)

    # ------------------------------------------------------------------ main
    def spin(self):
        rospy.Timer(rospy.Duration(1.0 / self.cmd_rate), self.send_command)
        rospy.Timer(rospy.Duration(0.01), self.poll)            # 100 Hz drain
        rospy.Timer(rospy.Duration(0.2), self.publish_telemetry)
        rospy.on_shutdown(self.shutdown)
        rospy.spin()

    def shutdown(self):
        """Always leave the robot stopped - a Ctrl-C must never drive it away."""
        rospy.loginfo("hardware_bridge: stopping motors and closing link")
        try:
            if self.connected:
                for _ in range(3):
                    self.link.send_velocity(0.0, 0.0)
                    rospy.sleep(0.02)
                self.link.close()
        except Exception:
            pass
        self.publish_connected(False)


if __name__ == "__main__":
    rospy.init_node("hardware_bridge")
    HardwareBridge().spin()
