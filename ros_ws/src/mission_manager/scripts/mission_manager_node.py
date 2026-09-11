#!/usr/bin/env python
"""
mission_manager_node.py - the seam between the web application and ROS.

    Website  ->  Backend  ->  [ /start_mission service ]  ->  THIS NODE
                                                                 |
                                                      actionlib goal
                                                                 v
                                                             move_base
                                                                 |
                                                             /cmd_vel
                                                                 v
                                                    Gazebo  or  ESP32

WHY A SEPARATE NODE INSTEAD OF THE BACKEND TALKING TO move_base DIRECTLY:

  * actionlib is a ROS-native protocol. Keeping it on the ROS side means the
    backend needs only a plain service call, and the website needs nothing
    at all beyond REST.
  * Mission bookkeeping (progress, distance, event log) needs /odom,
    /move_base/status and the global plan at ROS rates. Doing that over a
    bridge would be slow and lossy.
  * If the backend crashes mid-mission, the robot still finishes safely and
    the mission state survives, because it lives here.

WHAT IT PUBLISHES
    /mission_status  (latched, 2 Hz)  current mission state and progress
    /mission_events                    one message per notable moment
"""

import math

import actionlib
import rospy
import tf2_ros
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import Quaternion
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from nav_msgs.msg import Odometry, Path
from std_msgs.msg import Bool

from mission_manager.msg import MissionEvent, MissionStatus
from mission_manager.srv import (CancelMission, CancelMissionResponse,
                                 StartMission, StartMissionResponse)
from mission_manager.state import (FAILED, MissionTracker, NAVIGATING,
                                   SUCCEEDED)


def yaw_to_quaternion(yaw):
    return Quaternion(x=0.0, y=0.0, z=math.sin(yaw / 2.0), w=math.cos(yaw / 2.0))


def quaternion_to_yaw(q):
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def path_length(path_msg):
    """Total length of a nav_msgs/Path in metres."""
    total = 0.0
    poses = path_msg.poses
    for i in range(1, len(poses)):
        a = poses[i - 1].pose.position
        b = poses[i].pose.position
        total += math.hypot(b.x - a.x, b.y - a.y)
    return total


class MissionManagerNode(object):

    def __init__(self):
        self.map_frame = rospy.get_param("~map_frame", "map")
        self.base_frame = rospy.get_param("~base_frame", "base_footprint")
        self.goal_timeout = rospy.get_param("~goal_timeout", 300.0)   # s
        self.require_hardware = rospy.get_param("~require_hardware", True)
        self.server_wait = rospy.get_param("~move_base_wait", 30.0)

        self.tracker = MissionTracker(
            arrival_tolerance=rospy.get_param("~arrival_tolerance", 0.15))
        self.hardware_connected = not self.require_hardware

        self.status_pub = rospy.Publisher("mission_status", MissionStatus,
                                          queue_size=5, latch=True)
        self.event_pub = rospy.Publisher("mission_events", MissionEvent,
                                         queue_size=50)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)

        rospy.Subscriber("odom", Odometry, self.on_odom, queue_size=5)
        rospy.Subscriber("move_base/DWAPlannerROS/global_plan", Path,
                         self.on_plan, queue_size=1)
        rospy.Subscriber("hardware_connected", Bool, self.on_hardware,
                         queue_size=1)

        rospy.loginfo("mission_manager: waiting for move_base...")
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        if not self.client.wait_for_server(rospy.Duration(self.server_wait)):
            # Not fatal: the node stays up and refuses missions, which is far
            # more useful to the dashboard than the node simply dying.
            rospy.logerr("mission_manager: move_base did not appear within %.0fs; "
                         "missions will be refused until it does", self.server_wait)
            self.move_base_ready = False
        else:
            rospy.loginfo("mission_manager: connected to move_base")
            self.move_base_ready = True

        rospy.Service("start_mission", StartMission, self.handle_start)
        rospy.Service("cancel_mission", CancelMission, self.handle_cancel)

        self.goal_sent_at = None
        self.publish_status(None)

    # -------------------------------------------------------- subscriptions
    def on_odom(self, msg):
        """Odometry gives smooth motion; the map-frame pose comes from TF.
        We prefer TF because that is the pose the goal is expressed in."""
        pose = self.lookup_map_pose()
        if pose is None:
            p = msg.pose.pose
            pose = (p.position.x, p.position.y, quaternion_to_yaw(p.orientation))
        self.tracker.update_pose(*pose)

    def lookup_map_pose(self):
        try:
            tf = self.tf_buffer.lookup_transform(self.map_frame, self.base_frame,
                                                 rospy.Time(0),
                                                 rospy.Duration(0.1))
        except Exception:
            return None
        t = tf.transform.translation
        return (t.x, t.y, quaternion_to_yaw(tf.transform.rotation))

    def on_plan(self, msg):
        if self.tracker.is_active:
            self.tracker.update_plan(path_length(msg))

    def on_hardware(self, msg):
        was_connected = self.hardware_connected
        self.hardware_connected = msg.data or not self.require_hardware
        # Losing the robot mid-mission must abort it, not leave the dashboard
        # showing a mission that is quietly going nowhere.
        if was_connected and not self.hardware_connected and self.tracker.is_active:
            rospy.logerr("mission_manager: hardware disconnected mid-mission")
            self.client.cancel_all_goals()
            self.tracker.fail(rospy.Time.now().to_sec(),
                              "robot disconnected during navigation")
            self.flush_events()

    # ------------------------------------------------------------- services
    def handle_start(self, request):
        now = rospy.Time.now().to_sec()

        if not self.move_base_ready:
            if self.client.wait_for_server(rospy.Duration(1.0)):
                self.move_base_ready = True
            else:
                return StartMissionResponse(False, "move_base is not running")

        if not self.hardware_connected:
            return StartMissionResponse(False, "robot hardware is not connected")

        accepted, message = self.tracker.start(
            request.mission_id, request.destination_name,
            (request.goal_x, request.goal_y, request.goal_yaw),
            now, preempt=request.preempt)

        if not accepted:
            return StartMissionResponse(False, message)

        if request.preempt:
            self.client.cancel_all_goals()

        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = self.map_frame
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = request.goal_x
        goal.target_pose.pose.position.y = request.goal_y
        goal.target_pose.pose.orientation = yaw_to_quaternion(request.goal_yaw)

        self.client.send_goal(goal, done_cb=self.on_goal_done,
                              active_cb=self.on_goal_active,
                              feedback_cb=self.on_goal_feedback)
        self.goal_sent_at = now
        self.tracker.log("GOAL_SENT", "goal (%.2f, %.2f) sent to move_base"
                         % (request.goal_x, request.goal_y))
        self.flush_events()
        rospy.loginfo("mission_manager: mission %d -> %s (%.2f, %.2f)",
                      request.mission_id, request.destination_name,
                      request.goal_x, request.goal_y)
        return StartMissionResponse(True, "mission %d accepted" % request.mission_id)

    def handle_cancel(self, request):
        if not self.tracker.is_active:
            return CancelMissionResponse(False, "no mission is running")
        if request.mission_id not in (0, self.tracker.mission_id):
            return CancelMissionResponse(
                False, "mission %d is not the running mission (%d)" %
                (request.mission_id, self.tracker.mission_id))

        self.client.cancel_all_goals()
        self.tracker.cancel(rospy.Time.now().to_sec(),
                            request.reason or "cancelled by operator")
        self.flush_events()
        self.publish_status(None)
        return CancelMissionResponse(True, "mission cancelled")

    # ------------------------------------------------------ action callbacks
    def on_goal_active(self):
        if self.tracker.mark_navigating():
            self.flush_events()

    def on_goal_feedback(self, _feedback):
        pass   # pose already tracked from /odom + TF

    def on_goal_done(self, status, _result):
        now = rospy.Time.now().to_sec()
        if status == GoalStatus.SUCCEEDED:
            self.tracker.succeed(now, "arrived at %s" % self.tracker.destination_name)
        elif status == GoalStatus.PREEMPTED:
            # A preempt we caused ourselves already set CANCELLED/QUEUED;
            # only report it if the tracker is still active.
            self.tracker.cancel(now, "goal preempted")
        elif status == GoalStatus.ABORTED:
            self.tracker.fail(now, "move_base aborted: no path, or stuck after "
                                   "recovery behaviours")
        elif status == GoalStatus.REJECTED:
            self.tracker.fail(now, "move_base rejected the goal (unreachable "
                                   "or outside the map)")
        else:
            self.tracker.fail(now, "navigation ended with status %d" % status)
        self.flush_events()
        self.publish_status(None)

    # ------------------------------------------------------------ publishing
    def flush_events(self):
        for entry in self.tracker.drain_events():
            msg = MissionEvent()
            msg.header.stamp = rospy.Time.now()
            msg.mission_id = entry["mission_id"]
            msg.level = entry["level"]
            msg.event = entry["event"]
            msg.detail = entry["detail"]
            self.event_pub.publish(msg)

    def publish_status(self, _event):
        now = rospy.Time.now().to_sec()
        tracker = self.tracker

        # Independent timeout. move_base has its own patience settings, but a
        # goal that is neither succeeding nor aborting leaves the dashboard
        # stuck on "NAVIGATING" forever.
        if (tracker.state == NAVIGATING and self.goal_sent_at is not None
                and now - self.goal_sent_at > self.goal_timeout):
            rospy.logerr("mission_manager: mission %d exceeded %.0fs, cancelling",
                         tracker.mission_id, self.goal_timeout)
            self.client.cancel_all_goals()
            tracker.fail(now, "mission timed out after %.0f s" % self.goal_timeout)

        msg = MissionStatus()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = self.map_frame
        msg.mission_id = tracker.mission_id
        msg.destination_name = tracker.destination_name
        msg.state = tracker.state
        msg.distance_remaining = tracker.distance_remaining
        msg.distance_travelled = tracker.distance_travelled
        msg.elapsed_seconds = tracker.elapsed(now)
        msg.percent_complete = tracker.percent_complete()
        msg.current_x, msg.current_y, msg.current_yaw = tracker.current_pose
        if tracker.goal is not None:
            msg.goal_x, msg.goal_y, msg.goal_yaw = tracker.goal
        msg.message = tracker.message
        self.status_pub.publish(msg)
        self.flush_events()

    def spin(self):
        rospy.Timer(rospy.Duration(0.5), self.publish_status)
        rospy.on_shutdown(self.shutdown)
        rospy.spin()

    def shutdown(self):
        if self.tracker.is_active:
            rospy.logwarn("mission_manager: shutting down with mission %d active",
                          self.tracker.mission_id)
            try:
                self.client.cancel_all_goals()
            except Exception:
                pass
            self.tracker.cancel(rospy.Time.now().to_sec(),
                                "mission manager shut down")
            self.flush_events()


if __name__ == "__main__":
    rospy.init_node("mission_manager")
    MissionManagerNode().spin()
