"""
Tests for the mission state machine.

    python3 -m pytest ros_ws/src/mission_manager/test -v

Mission bookkeeping is where silent corruption hides: a cancel arriving one
tick after arrival, a progress bar that rewinds, a relocalisation jump
counted as distance travelled. Every test below is one of those.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

from mission_manager.state import (CANCELLED, FAILED, IDLE,  # noqa: E402
                                   NAVIGATING, QUEUED, SUCCEEDED,
                                   MissionTracker)


@pytest.fixture
def tracker():
    return MissionTracker()


def start(tracker, mission_id=1, name="AI Lab", goal=(3.0, 4.0, 0.0), now=100.0,
          preempt=False):
    return tracker.start(mission_id, name, goal, now, preempt=preempt)


# ---------------------------------------------------------------- lifecycle
def test_starts_idle(tracker):
    assert tracker.state == IDLE
    assert not tracker.is_active


def test_happy_path(tracker):
    assert start(tracker)[0] is True
    assert tracker.state == QUEUED
    assert tracker.mark_navigating() is True
    assert tracker.state == NAVIGATING
    assert tracker.succeed(150.0) is True
    assert tracker.state == SUCCEEDED
    assert tracker.is_terminal


def test_goal_and_name_are_recorded(tracker):
    start(tracker, mission_id=42, name="Reception", goal=(1.5, -2.5, 1.57))
    assert tracker.mission_id == 42
    assert tracker.destination_name == "Reception"
    assert tracker.goal == (1.5, -2.5, 1.57)


def test_second_mission_is_refused_while_one_runs(tracker):
    start(tracker, mission_id=1)
    accepted, message = start(tracker, mission_id=2)
    assert accepted is False
    assert "busy" in message
    assert tracker.mission_id == 1, "the running mission must not be replaced"


def test_preempt_replaces_the_running_mission(tracker):
    start(tracker, mission_id=1)
    tracker.mark_navigating()
    accepted, _ = start(tracker, mission_id=2, preempt=True)
    assert accepted is True
    assert tracker.mission_id == 2
    assert tracker.state == QUEUED


def test_new_mission_is_accepted_after_a_terminal_state(tracker):
    start(tracker, mission_id=1)
    tracker.succeed(150.0)
    assert start(tracker, mission_id=2, now=200.0)[0] is True
    assert tracker.mission_id == 2


def test_terminal_state_persists_until_a_new_mission(tracker):
    """The dashboard must keep showing SUCCEEDED, not blank to IDLE the
    instant the robot arrives."""
    start(tracker)
    tracker.succeed(150.0)
    tracker.update_pose(9.0, 9.0, 0.0)
    assert tracker.state == SUCCEEDED


# ----------------------------------------------------- illegal transitions
def test_cannot_succeed_a_mission_that_is_not_running(tracker):
    assert tracker.succeed(100.0) is False
    assert tracker.state == IDLE


def test_cannot_cancel_when_nothing_is_running(tracker):
    assert tracker.cancel(100.0) is False


def test_cancel_after_arrival_does_not_overwrite_success(tracker):
    """The race that corrupts analytics: an operator hits Cancel in the same
    instant the robot arrives. Arrival already won; it must stay won."""
    start(tracker)
    tracker.mark_navigating()
    tracker.succeed(150.0)
    assert tracker.cancel(150.1) is False
    assert tracker.state == SUCCEEDED


def test_failure_after_cancel_does_not_overwrite_cancellation(tracker):
    start(tracker)
    tracker.cancel(120.0)
    assert tracker.fail(121.0) is False
    assert tracker.state == CANCELLED


def test_mark_navigating_only_from_queued(tracker):
    assert tracker.mark_navigating() is False       # from IDLE
    start(tracker)
    assert tracker.mark_navigating() is True
    assert tracker.mark_navigating() is False       # already navigating


# -------------------------------------------------------------- progress
def test_percent_complete_is_zero_before_a_plan_arrives(tracker):
    start(tracker)
    assert tracker.percent_complete() == 0.0


def test_percent_complete_tracks_remaining_distance(tracker):
    start(tracker)
    tracker.update_plan(10.0)
    assert tracker.percent_complete() == pytest.approx(0.0)
    tracker.update_plan(5.0)
    assert tracker.percent_complete() == pytest.approx(50.0)
    tracker.update_plan(1.0)
    assert tracker.percent_complete() == pytest.approx(90.0)


def test_progress_never_rewinds_when_a_replan_is_longer(tracker):
    """move_base detours around an obstacle and the remaining distance grows
    past the original estimate. The bar must clamp at 0, not go negative."""
    start(tracker)
    tracker.update_plan(10.0)
    tracker.update_plan(25.0)
    assert tracker.percent_complete() == 0.0
    assert tracker.initial_distance == pytest.approx(10.0)


def test_arrival_forces_one_hundred_percent(tracker):
    start(tracker)
    tracker.update_plan(10.0)
    tracker.update_plan(0.4)          # move_base stops within tolerance
    tracker.succeed(150.0)
    assert tracker.percent_complete() == 100.0


# ------------------------------------------------------------- distances
def test_distance_travelled_integrates_motion(tracker):
    start(tracker)
    tracker.update_pose(0.0, 0.0, 0.0)
    tracker.update_pose(0.3, 0.0, 0.0)
    tracker.update_pose(0.3, 0.4, 0.0)
    assert tracker.distance_travelled == pytest.approx(0.7)


def test_relocalisation_jump_is_not_counted_as_travel(tracker):
    """AMCL correcting the pose by several metres is not the robot driving
    several metres. Counting it inflates every distance statistic."""
    start(tracker)
    tracker.update_pose(0.0, 0.0, 0.0)
    tracker.update_pose(0.1, 0.0, 0.0)
    tracker.update_pose(7.5, 3.2, 0.0)      # AMCL snaps
    tracker.update_pose(7.6, 3.2, 0.0)
    assert tracker.distance_travelled == pytest.approx(0.2)


def test_distance_is_not_accumulated_while_idle(tracker):
    tracker.update_pose(0.0, 0.0, 0.0)
    tracker.update_pose(5.0, 0.0, 0.0)
    assert tracker.distance_travelled == 0.0


def test_distance_resets_for_each_new_mission(tracker):
    start(tracker, mission_id=1)
    tracker.update_pose(0.0, 0.0, 0.0)
    tracker.update_pose(1.0, 0.0, 0.0)
    tracker.succeed(150.0)
    start(tracker, mission_id=2, now=200.0)
    assert tracker.distance_travelled == 0.0


def test_distance_to_goal_is_euclidean(tracker):
    start(tracker, goal=(3.0, 4.0, 0.0))
    tracker.update_pose(0.0, 0.0, 0.0)
    assert tracker.distance_to_goal() == pytest.approx(5.0)


# ------------------------------------------------------------------ timing
def test_elapsed_grows_while_running_and_freezes_when_done(tracker):
    start(tracker, now=100.0)
    assert tracker.elapsed(130.0) == pytest.approx(30.0)
    tracker.succeed(160.0)
    assert tracker.elapsed(999.0) == pytest.approx(60.0), \
        "elapsed must stop at the finish time"


def test_elapsed_is_zero_before_any_mission(tracker):
    assert tracker.elapsed(500.0) == 0.0


# ------------------------------------------------------------------ events
def test_events_are_logged_for_the_lifecycle(tracker):
    start(tracker)
    tracker.mark_navigating()
    tracker.succeed(150.0)
    names = [event["event"] for event in tracker.events]
    assert names == ["MISSION_CREATED", "NAVIGATING", "ARRIVED"]


def test_failure_is_logged_at_error_level(tracker):
    start(tracker)
    tracker.fail(150.0, "no path found")
    last = tracker.events[-1]
    assert last["level"] == "ERROR"
    assert "no path" in last["detail"]


def test_draining_events_yields_each_exactly_once(tracker):
    start(tracker)
    first = tracker.drain_events()
    assert len(first) == 1
    assert tracker.drain_events() == []


def test_event_buffer_is_bounded(tracker):
    """A robot stuck replanning for an hour must not grow this forever."""
    start(tracker)
    for i in range(2000):
        tracker.log("REPLANNED", "attempt %d" % i)
    assert len(tracker.events) <= 500
