"""
state.py - the mission state machine, with no ROS in it.

Kept ROS-free so the rules that decide whether a mission may start, when it
counts as finished, and how far along it is can be tested exhaustively on a
laptop. Mission bookkeeping is exactly the kind of logic where an edge case
(a cancel arriving one tick after arrival, say) quietly corrupts your
analytics and nobody notices for weeks.

STATES

    IDLE
      |  start()
      v
    QUEUED  --------- accepted by move_base --------> NAVIGATING
      |                                                 |    |
      | cancel()                                        |    | arrive()
      v                                                 |    v
    CANCELLED <------------- cancel() -----------------+   SUCCEEDED
                                                        |
                                                        | fail()
                                                        v
                                                      FAILED

SUCCEEDED / FAILED / CANCELLED are terminal. The tracker stays in a
terminal state until a new mission starts, so the dashboard keeps showing
the outcome instead of blanking to IDLE the instant a robot arrives.
"""

import math

IDLE = "IDLE"
QUEUED = "QUEUED"
NAVIGATING = "NAVIGATING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

TERMINAL_STATES = (SUCCEEDED, FAILED, CANCELLED)
ACTIVE_STATES = (QUEUED, NAVIGATING)


class MissionTracker(object):
    """Owns everything about the mission currently in progress."""

    def __init__(self, arrival_tolerance=0.15):
        self.arrival_tolerance = arrival_tolerance
        self._reset()

    def _reset(self):
        self.state = IDLE
        self.mission_id = 0
        self.destination_name = ""
        self.goal = None                # (x, y, yaw)
        self.message = ""
        self.start_time = None
        self.end_time = None
        self.distance_travelled = 0.0
        self.distance_remaining = 0.0
        self.initial_distance = 0.0
        self.current_pose = (0.0, 0.0, 0.0)
        self._last_pose = None
        self.events = []

    # ------------------------------------------------------------ queries
    @property
    def is_active(self):
        return self.state in ACTIVE_STATES

    @property
    def is_terminal(self):
        return self.state in TERMINAL_STATES

    def elapsed(self, now):
        if self.start_time is None:
            return 0.0
        end = self.end_time if self.end_time is not None else now
        return max(0.0, end - self.start_time)

    def percent_complete(self):
        """By distance along the plan, not by time.

        Returns 100 for a finished mission and 0 before the first plan
        arrives. Clamped, because move_base's remaining distance can briefly
        exceed the initial estimate when it replans around an obstacle - and
        a progress bar that jumps backwards past 0% looks broken.
        """
        if self.state == SUCCEEDED:
            return 100.0
        if self.initial_distance <= 1e-6:
            return 0.0
        travelled_fraction = 1.0 - (self.distance_remaining / self.initial_distance)
        return max(0.0, min(100.0, travelled_fraction * 100.0))

    def distance_to_goal(self):
        if self.goal is None:
            return float("inf")
        dx = self.goal[0] - self.current_pose[0]
        dy = self.goal[1] - self.current_pose[1]
        return math.hypot(dx, dy)

    # ----------------------------------------------------------- mutation
    def start(self, mission_id, destination_name, goal, now, preempt=False):
        """Begin a mission. Returns (accepted, message).

        Refusing to start while another mission is running is deliberate:
        two goals in flight means the robot's reported mission and its actual
        destination diverge, and the mission log becomes fiction.
        """
        if self.is_active and not preempt:
            return False, ("robot is busy with mission %d (%s)" %
                           (self.mission_id, self.state))

        preempted_id = self.mission_id if self.is_active else None
        self._reset()
        self.state = QUEUED
        self.mission_id = mission_id
        self.destination_name = destination_name
        self.goal = tuple(goal)
        self.start_time = now
        self.message = "queued"
        if preempted_id is not None:
            self.log("MISSION_CREATED", "preempted mission %d" % preempted_id,
                     level="WARN")
        else:
            self.log("MISSION_CREATED", "destination %s" % destination_name)
        return True, "accepted"

    def mark_navigating(self, now=None):
        if self.state != QUEUED:
            return False
        self.state = NAVIGATING
        self.message = "navigating"
        self.log("NAVIGATING", "move_base accepted the goal")
        return True

    def update_pose(self, x, y, yaw):
        """Feed the robot's current map-frame pose; integrates path length."""
        self.current_pose = (x, y, yaw)
        if self._last_pose is not None and self.is_active:
            dx = x - self._last_pose[0]
            dy = y - self._last_pose[1]
            step = math.hypot(dx, dy)
            # Reject teleports: AMCL relocalising can jump the pose by metres
            # in one update, and counting that as travel inflates every
            # distance statistic on the analytics page.
            if step < 0.5:
                self.distance_travelled += step
        self._last_pose = (x, y)

    def update_plan(self, distance_remaining):
        """Feed the length of the remaining global path."""
        self.distance_remaining = max(0.0, distance_remaining)
        # The first plan defines 100%. Later replans may be longer; keeping
        # the original denominator stops the progress bar from rewinding.
        if self.initial_distance <= 1e-6 and distance_remaining > 0.0:
            self.initial_distance = distance_remaining

    def succeed(self, now, message="arrived"):
        if not self.is_active:
            return False
        self.state = SUCCEEDED
        self.end_time = now
        self.distance_remaining = 0.0
        self.message = message
        self.log("ARRIVED", message)
        return True

    def fail(self, now, message="navigation failed"):
        if not self.is_active:
            return False
        self.state = FAILED
        self.end_time = now
        self.message = message
        self.log("FAILED", message, level="ERROR")
        return True

    def cancel(self, now, reason="cancelled by operator"):
        if not self.is_active:
            return False
        self.state = CANCELLED
        self.end_time = now
        self.message = reason
        self.log("CANCELLED", reason, level="WARN")
        return True

    # -------------------------------------------------------------- events
    def log(self, event, detail="", level="INFO"):
        entry = {"mission_id": self.mission_id, "event": event,
                 "detail": detail, "level": level}
        self.events.append(entry)
        # Bound the buffer: a robot stuck replanning for an hour would
        # otherwise grow this without limit.
        if len(self.events) > 500:
            self.events = self.events[-500:]
        return entry

    def drain_events(self):
        """Hand over pending events; the node publishes them exactly once."""
        pending, self.events = self.events, []
        return pending
