"""Robot queries and the online/offline rule."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.robot import Robot, RobotStatus, utcnow


def list_robots(db: Session) -> list[Robot]:
    return list(db.scalars(select(Robot).order_by(Robot.code)))


def get_robot(db: Session, robot_id: int) -> Robot | None:
    return db.get(Robot, robot_id)


def get_robot_by_code(db: Session, code: str) -> Robot | None:
    return db.scalar(select(Robot).where(Robot.code == code))


def create_robot(db: Session, code: str, name: str, mode) -> Robot:
    robot = Robot(code=code, name=name, mode=mode, status=RobotStatus.OFFLINE)
    db.add(robot)
    db.commit()
    db.refresh(robot)
    return robot


def delete_robot(db: Session, robot: Robot) -> None:
    db.delete(robot)
    db.commit()


def is_stale(robot: Robot, timeout_seconds: float, now: datetime | None = None) -> bool:
    """A robot that has not reported within the timeout is presumed offline.

    Absence of telemetry is the ONLY reliable offline signal: a robot whose
    Wi-Fi dropped, whose battery died, or that was switched off mid-mission
    cannot send a goodbye message. Anything that waits to be told is wrong.
    """
    if robot.last_seen is None:
        return True
    now = now or utcnow()
    last_seen = robot.last_seen
    # SQLite drops timezone information on round trip; treat naive as UTC
    # rather than crashing on a naive/aware comparison.
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return now - last_seen > timedelta(seconds=timeout_seconds)


def refresh_statuses(db: Session, timeout_seconds: float) -> int:
    """Mark stale robots OFFLINE. Returns how many changed."""
    changed = 0
    for robot in list_robots(db):
        if is_stale(robot, timeout_seconds) and robot.status != RobotStatus.OFFLINE:
            robot.status = RobotStatus.OFFLINE
            changed += 1
    if changed:
        db.commit()
    return changed


def clean_float(value) -> float | None:
    """Turn a possibly-NaN telemetry number into a float or None.

    The hardware bridge publishes NaN for the battery until the first BAT
    line arrives. NaN must not reach the database or the API:

      * PostgreSQL stores NaN in a float column quite happily
      * `json.dumps(float("nan"))` emits the bare token NaN, which is NOT
        valid JSON, so the dashboard's fetch fails outright

    SQLite happens to coerce NaN to NULL on write, which is exactly why this
    needs its own test rather than being checked through a round trip - the
    bug would only appear in production against PostgreSQL.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def apply_telemetry(db: Session, robot: Robot, message: dict) -> Robot:
    """Update a robot from a robot_hardware/RobotTelemetry message."""
    if message.get("battery_percent") is not None:
        robot.battery_percent = clean_float(message["battery_percent"])
    if message.get("battery_voltage") is not None:
        robot.battery_voltage = clean_float(message["battery_voltage"])

    robot.firmware_version = message.get("firmware_version") or robot.firmware_version
    error = message.get("last_error") or ""
    robot.last_error = error or None

    connected = bool(message.get("connected", False))
    if not connected:
        robot.status = RobotStatus.OFFLINE
    elif error:
        robot.status = RobotStatus.ERROR
    elif robot.status in (RobotStatus.OFFLINE, RobotStatus.ERROR):
        # Coming back online with no mission running: IDLE. A mission update
        # will move it to NAVIGATING on its own.
        robot.status = RobotStatus.IDLE

    robot.last_seen = utcnow()
    db.commit()
    db.refresh(robot)
    return robot


def apply_pose(db: Session, robot: Robot, x: float, y: float, yaw: float,
               linear_velocity: float | None = None) -> Robot:
    robot.x = x
    robot.y = y
    robot.yaw = yaw
    if linear_velocity is not None:
        robot.linear_velocity = linear_velocity
    robot.last_seen = utcnow()
    db.commit()
    return robot
