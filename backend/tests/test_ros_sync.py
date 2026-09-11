"""
Tests for the ROS -> database path.

This is where progress reported by the robot becomes rows the website reads.
It is also where a late or duplicated message could rewrite a finished
mission's history, so the guards get explicit tests.
"""

import pytest

from app.models.mission import MissionStatus
from app.models.robot import RobotStatus
from app.services import mission_service, robot_service


def make_mission(client, robot, destination):
    return client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]}).json()


def status_message(mission_id, state, **overrides):
    """A mission_manager/MissionStatus message, as rosbridge delivers it."""
    message = {
        "mission_id": mission_id,
        "destination_name": "AI Lab",
        "state": state,
        "distance_remaining": 5.0,
        "distance_travelled": 9.0,
        "elapsed_seconds": 31.0,
        "percent_complete": 64.0,
        "current_x": 2.5, "current_y": 1.5, "current_yaw": 0.4,
        "goal_x": 3.8, "goal_y": 3.4, "goal_yaw": 1.57,
        "message": "",
    }
    message.update(overrides)
    return message


# ------------------------------------------------------- status -> database
def test_navigating_status_updates_progress(client, db_session, robot, destination):
    mission = make_mission(client, robot, destination)
    mission_service.apply_status_update(db_session,
                                        status_message(mission["id"], "NAVIGATING"))

    updated = client.get("/api/missions/%d" % mission["id"]).json()
    assert updated["status"] == MissionStatus.NAVIGATING.value
    assert updated["percent_complete"] == pytest.approx(64.0)
    assert updated["distance_m"] == pytest.approx(9.0)
    assert updated["duration_s"] == pytest.approx(31.0)


def test_status_update_moves_the_robots_pose(client, db_session, robot, destination):
    mission = make_mission(client, robot, destination)
    mission_service.apply_status_update(db_session,
                                        status_message(mission["id"], "NAVIGATING"))
    body = client.get("/api/robots/%d" % robot["id"]).json()
    assert body["x"] == pytest.approx(2.5)
    assert body["y"] == pytest.approx(1.5)


def test_success_completes_the_mission_and_frees_the_robot(client, db_session,
                                                            robot, destination):
    mission = make_mission(client, robot, destination)
    mission_service.apply_status_update(db_session,
                                        status_message(mission["id"], "NAVIGATING"))
    mission_service.apply_status_update(
        db_session, status_message(mission["id"], "SUCCEEDED",
                                   percent_complete=100.0, distance_remaining=0.0))

    updated = client.get("/api/missions/%d" % mission["id"]).json()
    assert updated["status"] == MissionStatus.SUCCEEDED.value
    assert updated["percent_complete"] == pytest.approx(100.0)
    assert updated["completed_at"] is not None
    assert client.get("/api/robots/%d" % robot["id"]).json()["status"] == "IDLE"


def test_failure_records_the_reason(client, db_session, robot, destination):
    mission = make_mission(client, robot, destination)
    mission_service.apply_status_update(
        db_session, status_message(mission["id"], "FAILED",
                                   message="move_base aborted: no path"))
    updated = client.get("/api/missions/%d" % mission["id"]).json()
    assert updated["status"] == MissionStatus.FAILED.value
    assert "no path" in updated["failure_reason"]


def test_a_late_message_cannot_resurrect_a_finished_mission(client, db_session,
                                                             robot, destination):
    """The guard that protects every analytics number: a status message that
    arrives after the outcome was recorded must be ignored, not applied."""
    mission = make_mission(client, robot, destination)
    mission_service.apply_status_update(db_session,
                                        status_message(mission["id"], "SUCCEEDED"))
    mission_service.apply_status_update(
        db_session, status_message(mission["id"], "NAVIGATING",
                                   percent_complete=12.0))

    updated = client.get("/api/missions/%d" % mission["id"]).json()
    assert updated["status"] == MissionStatus.SUCCEEDED.value
    assert updated["percent_complete"] == pytest.approx(100.0)


def test_status_for_an_unknown_mission_is_ignored(client, db_session):
    assert mission_service.apply_status_update(
        db_session, status_message(4242, "NAVIGATING")) is None


def test_idle_status_message_with_no_mission_is_ignored(client, db_session):
    assert mission_service.apply_status_update(
        db_session, status_message(0, "IDLE")) is None


# ---------------------------------------------------- events -> database
def test_ros_events_are_appended_to_the_mission_log(client, db_session,
                                                     robot, destination):
    mission = make_mission(client, robot, destination)
    mission_service.apply_event_message(db_session, {
        "mission_id": mission["id"], "level": "WARN",
        "event": "REPLANNED", "detail": "obstacle detected"})

    events = client.get("/api/missions/%d" % mission["id"]).json()["events"]
    replanned = [event for event in events if event["event"] == "REPLANNED"]
    assert len(replanned) == 1
    assert replanned[0]["level"] == "WARN"
    assert replanned[0]["detail"] == "obstacle detected"


def test_event_for_an_unknown_mission_is_ignored(client, db_session):
    assert mission_service.apply_event_message(
        db_session, {"mission_id": 999, "event": "X"}) is None


# ------------------------------------------------- telemetry -> database
def telemetry(**overrides):
    message = {"connected": True, "battery_voltage": 7.5, "battery_percent": 50.0,
               "left_ticks": 100, "right_ticks": 100, "left_wheel_rps": 1.0,
               "right_wheel_rps": 1.0, "front_distance": -1.0,
               "link_latency_ms": 4.0, "firmware_version": "esp32-1.0.0",
               "last_error": ""}
    message.update(overrides)
    return message


def test_telemetry_brings_a_robot_online(client, db_session, robot):
    record = robot_service.get_robot(db_session, robot["id"])
    robot_service.apply_telemetry(db_session, record, telemetry())

    body = client.get("/api/robots/%d" % robot["id"]).json()
    assert body["status"] == RobotStatus.IDLE.value
    assert body["battery_percent"] == pytest.approx(50.0)
    assert body["firmware_version"] == "esp32-1.0.0"


def test_telemetry_reporting_disconnected_marks_the_robot_offline(client,
                                                                   db_session, robot):
    record = robot_service.get_robot(db_session, robot["id"])
    robot_service.apply_telemetry(db_session, record, telemetry())
    robot_service.apply_telemetry(db_session, record, telemetry(connected=False))
    assert client.get("/api/robots/%d" % robot["id"]).json()["status"] == "OFFLINE"


def test_a_reported_error_sets_the_error_status(client, db_session, robot):
    record = robot_service.get_robot(db_session, robot["id"])
    robot_service.apply_telemetry(db_session, record,
                                  telemetry(last_error="motor driver fault"))
    body = client.get("/api/robots/%d" % robot["id"]).json()
    assert body["status"] == RobotStatus.ERROR.value
    assert body["last_error"] == "motor driver fault"


def test_nan_telemetry_is_sanitised_to_none():
    """The bridge publishes NaN until the first BAT line arrives.

    Tested on the function directly, NOT through the database: SQLite
    coerces NaN to NULL on write, so a round-trip test would pass even with
    the guard removed - and then fail in production against PostgreSQL,
    where NaN survives and json.dumps emits invalid JSON.
    """
    assert robot_service.clean_float(float("nan")) is None
    assert robot_service.clean_float(float("inf")) is None
    assert robot_service.clean_float(float("-inf")) is None
    assert robot_service.clean_float(None) is None
    assert robot_service.clean_float("not a number") is None
    assert robot_service.clean_float(50.0) == 50.0
    assert robot_service.clean_float(0.0) == 0.0


def test_nan_battery_does_not_reach_the_robot_record(client, db_session, robot):
    record = robot_service.get_robot(db_session, robot["id"])
    robot_service.apply_telemetry(db_session, record,
                                  telemetry(battery_percent=float("nan"),
                                            battery_voltage=float("nan")))
    body = client.get("/api/robots/%d" % robot["id"]).json()
    assert body["battery_percent"] is None
    assert body["battery_voltage"] is None


def test_a_robot_that_stops_reporting_goes_offline(client, db_session, robot):
    """Absence of telemetry is the only reliable offline signal - a robot
    whose battery died cannot send a goodbye."""
    record = robot_service.get_robot(db_session, robot["id"])
    robot_service.apply_telemetry(db_session, record, telemetry())
    assert not robot_service.is_stale(record, timeout_seconds=5.0)
    # Same robot, judged against a timeout it cannot satisfy
    assert robot_service.is_stale(record, timeout_seconds=0.0)

    robot_service.refresh_statuses(db_session, timeout_seconds=0.0)
    assert client.get("/api/robots/%d" % robot["id"]).json()["status"] == "OFFLINE"


def test_a_robot_that_never_reported_is_stale(db_session, client, robot):
    record = robot_service.get_robot(db_session, robot["id"])
    assert record.last_seen is None
    assert robot_service.is_stale(record, timeout_seconds=99999.0)
