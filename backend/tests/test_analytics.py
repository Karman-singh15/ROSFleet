"""
Analytics tests.

Every number on the analytics page is derived, so a wrong denominator here
silently misreports the fleet for as long as nobody checks by hand.
"""

import pytest

from app.models.mission import Mission, MissionStatus
from app.models.robot import Robot, RobotMode, utcnow
from app.services import analytics_service


def add_mission(db, robot_id, status, distance=10.0, duration=40.0,
                destination="AI Lab", failure_reason=None):
    mission = Mission(robot_id=robot_id, destination_name=destination,
                      goal_x=1.0, goal_y=2.0, goal_yaw=0.0, status=status,
                      distance_m=distance, duration_s=duration,
                      failure_reason=failure_reason,
                      started_at=utcnow(),
                      completed_at=utcnow() if status.is_terminal else None)
    db.add(mission)
    db.commit()
    return mission


@pytest.fixture
def fleet(db_session):
    first = Robot(code="RB001", name="One", mode=RobotMode.SIMULATED)
    second = Robot(code="RB002", name="Two", mode=RobotMode.SIMULATED)
    db_session.add_all([first, second])
    db_session.commit()
    return first, second


def test_empty_fleet_reports_zeroes_not_a_crash(db_session):
    summary = analytics_service.summary(db_session)
    assert summary["counts"]["total"] == 0
    assert summary["counts"]["success_rate"] == 0.0
    assert summary["average_duration_s"] == 0.0
    assert summary["robots"] == []


def test_counts_by_status(db_session, fleet):
    first, _ = fleet
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED)
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED)
    add_mission(db_session, first.id, MissionStatus.FAILED)
    add_mission(db_session, first.id, MissionStatus.CANCELLED)
    add_mission(db_session, first.id, MissionStatus.NAVIGATING)

    counts = analytics_service.summary(db_session)["counts"]
    assert counts["succeeded"] == 2
    assert counts["failed"] == 1
    assert counts["cancelled"] == 1
    assert counts["active"] == 1
    assert counts["total"] == 5


def test_success_rate_excludes_in_flight_missions(db_session, fleet):
    """Counting active missions in the denominator would make the rate sag
    every time a robot sets off, which looks like a fleet getting worse when
    nothing has happened yet."""
    first, _ = fleet
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED)
    add_mission(db_session, first.id, MissionStatus.FAILED)
    add_mission(db_session, first.id, MissionStatus.NAVIGATING)

    # 1 of 2 FINISHED missions succeeded
    assert analytics_service.summary(db_session)["counts"]["success_rate"] == 50.0


def test_average_duration_ignores_failed_missions(db_session, fleet):
    """A mission that failed after 3 s because the goal was unreachable would
    otherwise drag the average down and make the fleet look faster."""
    first, _ = fleet
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED, duration=40.0)
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED, duration=60.0)
    add_mission(db_session, first.id, MissionStatus.FAILED, duration=3.0)

    assert analytics_service.summary(db_session)["average_duration_s"] == 50.0


def test_total_distance_includes_failed_missions(db_session, fleet):
    """The robot really drove those metres, even on the missions that failed."""
    first, _ = fleet
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED, distance=10.0)
    add_mission(db_session, first.id, MissionStatus.FAILED, distance=4.0)

    summary = analytics_service.summary(db_session)
    assert summary["total_distance_m"] == pytest.approx(14.0)
    assert summary["average_distance_m"] == pytest.approx(10.0)


def test_per_robot_utilisation_is_separated(db_session, fleet):
    first, second = fleet
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED, distance=10.0)
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED, distance=15.0)
    add_mission(db_session, second.id, MissionStatus.FAILED, distance=3.0)

    robots = {row["robot_code"]: row
              for row in analytics_service.summary(db_session)["robots"]}
    assert robots["RB001"]["missions"] == 2
    assert robots["RB001"]["total_distance_m"] == pytest.approx(25.0)
    assert robots["RB001"]["success_rate"] == 100.0
    assert robots["RB002"]["missions"] == 1
    assert robots["RB002"]["success_rate"] == 0.0


def test_failures_are_bucketed_by_cause(db_session, fleet):
    """Raw move_base strings are free text; without bucketing every failure
    is its own category and the breakdown says nothing."""
    first, _ = fleet
    add_mission(db_session, first.id, MissionStatus.FAILED,
                failure_reason="move_base aborted: no path, or stuck")
    add_mission(db_session, first.id, MissionStatus.FAILED,
                failure_reason="move_base rejected the goal (unreachable)")
    add_mission(db_session, first.id, MissionStatus.FAILED,
                failure_reason="robot disconnected during navigation")
    add_mission(db_session, first.id, MissionStatus.FAILED,
                failure_reason="mission timed out after 300 s")

    failures = {row["reason"]: row["count"]
                for row in analytics_service.summary(db_session)["failures"]}
    assert failures["No path to goal"] == 2
    assert failures["Robot disconnected"] == 1
    assert failures["Mission timeout"] == 1


def test_failure_with_no_reason_is_bucketed_as_unknown(db_session, fleet):
    first, _ = fleet
    add_mission(db_session, first.id, MissionStatus.FAILED, failure_reason=None)
    failures = analytics_service.summary(db_session)["failures"]
    assert failures == [{"reason": "Unknown", "count": 1}]


def test_busiest_destinations_are_ranked(db_session, fleet):
    first, _ = fleet
    for _ in range(3):
        add_mission(db_session, first.id, MissionStatus.SUCCEEDED,
                    destination="AI Lab")
    add_mission(db_session, first.id, MissionStatus.SUCCEEDED,
                destination="Reception")

    busiest = analytics_service.summary(db_session)["busiest_destinations"]
    assert busiest[0] == {"destination": "AI Lab", "count": 3}
    assert busiest[1] == {"destination": "Reception", "count": 1}


def test_analytics_endpoint_serialises(client, robot, destination):
    client.post("/api/missions", json={"robot_id": robot["id"],
                                       "destination_id": destination["id"]})
    response = client.get("/api/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["active"] == 1
    assert body["robots"][0]["robot_code"] == "RB001"
