"""
Mission creation and lifecycle - the backend half of the mission flow.

The division of responsibility, which is the important part:

    BACKEND (here)          knows names, owns history, decides what is legal
    ROS (mission_manager)   knows poses, owns execution, reports progress

So this module resolves "AI Lab" to a pose, writes the row, calls the ROS
service, and then keeps the row in step with whatever ROS reports.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.destination import Destination
from app.models.mission import Mission, MissionEvent, MissionStatus
from app.models.robot import Robot, RobotStatus, utcnow
from app.ros.ros_client import (SERVICE_CANCEL_MISSION, SERVICE_START_MISSION,
                                TYPE_CANCEL_MISSION, TYPE_START_MISSION,
                                RosClient)

logger = logging.getLogger(__name__)


class MissionError(Exception):
    """Raised for a request that is invalid or cannot be honoured.

    The API layer turns this into a 400/409 with the message intact, so the
    website can show the actual reason rather than "something went wrong".
    """


def list_missions(db: Session, robot_id: int | None = None,
                  status: MissionStatus | None = None,
                  limit: int = 100) -> list[Mission]:
    query = select(Mission).order_by(Mission.created_at.desc()).limit(limit)
    if robot_id is not None:
        query = query.where(Mission.robot_id == robot_id)
    if status is not None:
        query = query.where(Mission.status == status)
    return list(db.scalars(query))


def get_mission(db: Session, mission_id: int) -> Mission | None:
    return db.get(Mission, mission_id)


def active_mission_for_robot(db: Session, robot_id: int) -> Mission | None:
    return db.scalar(
        select(Mission)
        .where(Mission.robot_id == robot_id,
               Mission.status.in_([MissionStatus.QUEUED, MissionStatus.NAVIGATING]))
        .order_by(Mission.created_at.desc()))


def create_mission(db: Session, ros: RosClient, robot_id: int,
                   destination_id: int | None = None,
                   goal_x: float | None = None, goal_y: float | None = None,
                   goal_yaw: float = 0.0, preempt: bool = False) -> Mission:
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise MissionError("robot %d does not exist" % robot_id)

    # Resolve the destination to a pose. Name -> coordinates happens HERE and
    # nowhere else; ROS only ever deals in poses.
    destination: Destination | None = None
    if destination_id is not None:
        destination = db.get(Destination, destination_id)
        if destination is None:
            raise MissionError("destination %d does not exist" % destination_id)
        goal_x, goal_y, goal_yaw = destination.x, destination.y, destination.yaw
        destination_name = destination.name
    else:
        if goal_x is None or goal_y is None:
            raise MissionError(
                "provide either a destination_id or both goal_x and goal_y")
        destination_name = "(%.2f, %.2f)" % (goal_x, goal_y)

    existing = active_mission_for_robot(db, robot_id)
    if existing is not None and not preempt:
        raise MissionError(
            "robot %s is already running mission %d (%s); pass preempt=true "
            "to replace it" % (robot.code, existing.id, existing.status.value))

    # Write the row BEFORE calling ROS, so its id can be passed along and the
    # two sides share one identifier for the mission.
    mission = Mission(
        robot_id=robot_id,
        destination_id=destination.id if destination else None,
        destination_name=destination_name,
        goal_x=float(goal_x), goal_y=float(goal_y), goal_yaw=float(goal_yaw),
        status=MissionStatus.QUEUED,
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    add_event(db, mission, "MISSION_CREATED",
              "destination %s" % destination_name)

    if existing is not None and preempt:
        cancel_mission(db, ros, existing,
                       reason="preempted by mission %d" % mission.id)

    response = ros.call_service(SERVICE_START_MISSION, TYPE_START_MISSION, {
        "mission_id": mission.id,
        "destination_name": destination_name,
        "goal_x": float(goal_x),
        "goal_y": float(goal_y),
        "goal_yaw": float(goal_yaw),
        "preempt": bool(preempt),
    })

    if not response.get("accepted", False):
        # ROS refused. Fail the row immediately rather than leaving a mission
        # QUEUED forever waiting for a robot that never got the message.
        mission.status = MissionStatus.FAILED
        mission.failure_reason = response.get("message", "ROS refused the mission")
        mission.completed_at = utcnow()
        db.commit()
        add_event(db, mission, "FAILED", mission.failure_reason, level="ERROR")
        raise MissionError(mission.failure_reason)

    mission.started_at = utcnow()
    robot.status = RobotStatus.NAVIGATING
    db.commit()
    db.refresh(mission)
    add_event(db, mission, "GOAL_SENT",
              "goal (%.2f, %.2f) accepted by ROS" % (goal_x, goal_y))
    return mission


def cancel_mission(db: Session, ros: RosClient, mission: Mission,
                   reason: str = "cancelled by operator") -> Mission:
    if mission.status.is_terminal:
        raise MissionError("mission %d is already %s" %
                           (mission.id, mission.status.value))

    response = ros.call_service(SERVICE_CANCEL_MISSION, TYPE_CANCEL_MISSION, {
        "mission_id": mission.id,
        "reason": reason,
    })

    # Cancel locally even if ROS could not be reached. A mission left running
    # in the database for a robot that is gone is worse than a cancel that
    # ROS never heard: the robot's own watchdogs stop it regardless.
    mission.status = MissionStatus.CANCELLED
    mission.completed_at = utcnow()
    mission.duration_s = _duration(mission)
    mission.failure_reason = reason
    robot = db.get(Robot, mission.robot_id)
    if robot is not None and robot.status == RobotStatus.NAVIGATING:
        robot.status = RobotStatus.IDLE
    db.commit()

    detail = reason if response.get("cancelled") else \
        "%s (ROS: %s)" % (reason, response.get("message", "unreachable"))
    add_event(db, mission, "CANCELLED", detail, level="WARN")
    db.refresh(mission)
    return mission


def apply_status_update(db: Session, message: dict) -> Mission | None:
    """Apply a mission_manager/MissionStatus message to the database.

    This is the ONE place ROS-reported progress enters the database, which is
    why it is also where the terminal-state guard lives.
    """
    mission_id = int(message.get("mission_id", 0) or 0)
    if mission_id <= 0:
        return None
    mission = db.get(Mission, mission_id)
    if mission is None:
        return None

    state = str(message.get("state", "")).upper()

    # Never resurrect a finished mission. A late status message arriving after
    # the outcome was recorded would otherwise rewrite history, and every
    # analytics number computed from it.
    if mission.status.is_terminal:
        return mission

    mission.percent_complete = float(message.get("percent_complete", 0.0) or 0.0)
    mission.distance_m = float(message.get("distance_travelled", 0.0) or 0.0)
    mission.duration_s = float(message.get("elapsed_seconds", 0.0) or 0.0)

    robot = db.get(Robot, mission.robot_id)

    if state == "NAVIGATING":
        mission.status = MissionStatus.NAVIGATING
        if mission.started_at is None:
            mission.started_at = utcnow()
        if robot is not None:
            robot.status = RobotStatus.NAVIGATING
    elif state == "SUCCEEDED":
        mission.status = MissionStatus.SUCCEEDED
        mission.completed_at = utcnow()
        mission.percent_complete = 100.0
        if robot is not None:
            robot.status = RobotStatus.IDLE
    elif state in ("FAILED", "CANCELLED"):
        mission.status = (MissionStatus.FAILED if state == "FAILED"
                          else MissionStatus.CANCELLED)
        mission.completed_at = utcnow()
        mission.failure_reason = message.get("message") or state
        if robot is not None:
            robot.status = RobotStatus.IDLE

    if robot is not None:
        robot.x = float(message.get("current_x", robot.x or 0.0) or 0.0)
        robot.y = float(message.get("current_y", robot.y or 0.0) or 0.0)
        robot.yaw = float(message.get("current_yaw", robot.yaw or 0.0) or 0.0)
        robot.last_seen = utcnow()

    db.commit()
    db.refresh(mission)
    return mission


def add_event(db: Session, mission: Mission, event: str, detail: str = "",
              level: str = "INFO") -> MissionEvent:
    entry = MissionEvent(mission_id=mission.id, event=event, detail=detail,
                         level=level)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def apply_event_message(db: Session, message: dict) -> MissionEvent | None:
    """Store a mission_manager/MissionEvent coming from ROS."""
    mission_id = int(message.get("mission_id", 0) or 0)
    mission = db.get(Mission, mission_id) if mission_id > 0 else None
    if mission is None:
        return None
    return add_event(db, mission,
                     str(message.get("event", "EVENT")),
                     str(message.get("detail", "")),
                     str(message.get("level", "INFO")))


def _duration(mission: Mission) -> float:
    if mission.started_at is None or mission.completed_at is None:
        return mission.duration_s
    started, completed = mission.started_at, mission.completed_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=completed.tzinfo)
    return max(0.0, (completed - started).total_seconds())
