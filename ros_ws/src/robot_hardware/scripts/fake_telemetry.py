#!/usr/bin/env python
"""
fake_telemetry.py - publishes /robot_telemetry while running in simulation.

Gazebo simulates motion and sensors but has no notion of a battery or a
serial link. Without this node the dashboard would show "battery: unknown"
in sim, and the frontend would need a special case for simulated robots.
Publishing a plausible draining battery here keeps the simulated robot and
the real robot indistinguishable to everything upstream.
"""

import math

import rospy
from robot_hardware.msg import RobotTelemetry
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool


class FakeTelemetry(object):

    def __init__(self):
        self.start_voltage = rospy.get_param("~start_voltage", 8.20)
        self.drain_per_hour = rospy.get_param("~drain_per_hour", 0.90)  # volts/hour
        self.empty_voltage = rospy.get_param("~battery_empty_voltage", 6.6)
        self.full_voltage = rospy.get_param("~battery_full_voltage", 8.4)
        self.wheel_radius = rospy.get_param("~wheel_radius", 0.0325)
        self.ticks_per_rev = rospy.get_param("~ticks_per_rev", 780.0)

        self.start_time = rospy.Time.now()
        self.left_rps = 0.0
        self.right_rps = 0.0
        self.left_ticks = 0.0
        self.right_ticks = 0.0
        self.last_js = None

        self.pub = rospy.Publisher("robot_telemetry", RobotTelemetry, queue_size=5)
        self.connected_pub = rospy.Publisher("hardware_connected", Bool,
                                             queue_size=1, latch=True)
        rospy.Subscriber("joint_states", JointState, self.on_joint_states, queue_size=5)
        self.connected_pub.publish(Bool(data=True))

    def on_joint_states(self, msg):
        """Derive simulated encoder counts from Gazebo's wheel joint states so
        the telemetry numbers actually track the robot's motion."""
        try:
            li = msg.name.index("left_wheel_joint")
            ri = msg.name.index("right_wheel_joint")
        except ValueError:
            return
        if msg.velocity and len(msg.velocity) > max(li, ri):
            self.left_rps = msg.velocity[li] / (2.0 * math.pi)
            self.right_rps = msg.velocity[ri] / (2.0 * math.pi)
        if msg.position and len(msg.position) > max(li, ri):
            self.left_ticks = msg.position[li] / (2.0 * math.pi) * self.ticks_per_rev
            self.right_ticks = msg.position[ri] / (2.0 * math.pi) * self.ticks_per_rev

    def publish(self, _event):
        hours = (rospy.Time.now() - self.start_time).to_sec() / 3600.0
        voltage = max(self.empty_voltage,
                      self.start_voltage - self.drain_per_hour * hours)
        span = self.full_voltage - self.empty_voltage
        percent = max(0.0, min(100.0, 100.0 * (voltage - self.empty_voltage) / span))

        msg = RobotTelemetry()
        msg.header.stamp = rospy.Time.now()
        msg.connected = True
        msg.battery_voltage = voltage
        msg.battery_percent = percent
        msg.left_ticks = int(self.left_ticks)
        msg.right_ticks = int(self.right_ticks)
        msg.left_wheel_rps = self.left_rps
        msg.right_wheel_rps = self.right_rps
        msg.front_distance = -1.0          # no ultrasonic model in sim
        msg.link_latency_ms = 0.0
        msg.firmware_version = "simulated"
        msg.last_error = ""
        self.pub.publish(msg)
        self.connected_pub.publish(Bool(data=True))


if __name__ == "__main__":
    rospy.init_node("fake_telemetry")
    node = FakeTelemetry()
    rospy.Timer(rospy.Duration(0.2), node.publish)
    rospy.spin()
