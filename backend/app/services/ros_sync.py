"""
Wires ROS topics into the database and out to connected browsers.

    /mission_status   -> update the mission row  -> broadcast
    /mission_events   -> append to the log       -> broadcast
    /robot_telemetry  -> update the robot row    -> broadcast

These callbacks run on roslibpy's thread, NOT on the FastAPI event loop, so
each one opens its own database session and broadcasts through the
thread-safe path. Sharing a request session here would be a race.
"""

from __future__ import annotations

import logging

from app.api.live import manager
from app.core.database import SessionLocal
from app.ros.ros_client import (TOPIC_MISSION_EVENTS, TOPIC_MISSION_STATUS,
                                TOPIC_ROBOT_TELEMETRY, TYPE_MISSION_EVENT,
                                TYPE_MISSION_STATUS, TYPE_ROBOT_TELEMETRY,
                                RosClient)
from app.services import mission_service, robot_service

logger = logging.getLogger(__name__)

# Which robot the single-robot ROS stack belongs to. With one robot per ROS
# master this is enough; a multi-robot fleet would namespace the topics per
# robot and carry the code in the message instead.
DEFAULT_ROBOT_CODE = "RB001"


def _resolve_robot(db):
    robot = robot_service.get_robot_by_code(db, DEFAULT_ROBOT_CODE)
    if robot is None:
        robots = robot_service.list_robots(db)
        robot = robots[0] if robots else None
    return robot


def on_mission_status(message: dict) -> None:
    db = SessionLocal()
    try:
        mission = mission_service.apply_status_update(db, message)
        if mission is not None:
            manager.broadcast_threadsafe({
                "type": "mission_update",
                "data": {
                    "id": mission.id,
                    "robot_id": mission.robot_id,
                    "status": mission.status.value,
                    "percent_complete": mission.percent_complete,
                    "distance_m": mission.distance_m,
                    "duration_s": mission.duration_s,
                    "destination_name": mission.destination_name,
                },
            })
    except Exception:
        logger.exception("failed to apply /mission_status")
    finally:
        db.close()


def on_mission_event(message: dict) -> None:
    db = SessionLocal()
    try:
        event = mission_service.apply_event_message(db, message)
        if event is not None:
            manager.broadcast_threadsafe({
                "type": "mission_event",
                "data": {"mission_id": event.mission_id, "level": event.level,
                         "event": event.event, "detail": event.detail},
            })
    except Exception:
        logger.exception("failed to apply /mission_events")
    finally:
        db.close()


def on_robot_telemetry(message: dict) -> None:
    db = SessionLocal()
    try:
        robot = _resolve_robot(db)
        if robot is None:
            return
        robot = robot_service.apply_telemetry(db, robot, message)
        manager.broadcast_threadsafe({
            "type": "robot_update",
            "data": {"id": robot.id, "code": robot.code,
                     "status": robot.status.value,
                     "battery_percent": robot.battery_percent,
                     "x": robot.x, "y": robot.y,
                     "last_error": robot.last_error},
        })
    except Exception:
        logger.exception("failed to apply /robot_telemetry")
    finally:
        db.close()


def register(ros: RosClient) -> None:
    """Attach every subscription. Called once at startup."""
    ros.subscribe(TOPIC_MISSION_STATUS, TYPE_MISSION_STATUS, on_mission_status)
    ros.subscribe(TOPIC_MISSION_EVENTS, TYPE_MISSION_EVENT, on_mission_event)
    ros.subscribe(TOPIC_ROBOT_TELEMETRY, TYPE_ROBOT_TELEMETRY, on_robot_telemetry)
    logger.info("ROS sync: subscribed to mission status, events and telemetry")
