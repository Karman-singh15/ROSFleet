"""
Analytics - computed from the missions table on demand.

No pre-aggregation, no summary tables. At this project's scale (thousands of
missions, not millions) the queries are instant, and a stale cache that
disagrees with the mission list is far more confusing to a user than a
query that takes 5 ms.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.mission import Mission, MissionStatus
from app.models.robot import Robot

FINISHED = (MissionStatus.SUCCEEDED, MissionStatus.FAILED, MissionStatus.CANCELLED)
ACTIVE = (MissionStatus.QUEUED, MissionStatus.NAVIGATING)


def _counts(db: Session, robot_id: int | None = None) -> dict:
    query = select(Mission.status, func.count(Mission.id)).group_by(Mission.status)
    if robot_id is not None:
        query = query.where(Mission.robot_id == robot_id)
    by_status = {status: count for status, count in db.execute(query)}

    succeeded = by_status.get(MissionStatus.SUCCEEDED, 0)
    failed = by_status.get(MissionStatus.FAILED, 0)
    cancelled = by_status.get(MissionStatus.CANCELLED, 0)
    active = sum(by_status.get(state, 0) for state in ACTIVE)

    # Success rate is over FINISHED missions only. Including in-flight ones
    # would make the number sag every time a robot sets off, which looks like
    # the fleet getting worse when nothing has happened yet.
    finished = succeeded + failed + cancelled
    success_rate = (100.0 * succeeded / finished) if finished else 0.0

    return {
        "total": succeeded + failed + cancelled + active,
        "succeeded": succeeded,
        "failed": failed,
        "cancelled": cancelled,
        "active": active,
        "success_rate": round(success_rate, 1),
    }


def _averages(db: Session) -> tuple[float, float, float]:
    """Averages over SUCCEEDED missions only.

    A mission that failed after 3 seconds because the goal was unreachable
    would otherwise drag the "average mission time" down and make the fleet
    look faster than it is.
    """
    row = db.execute(
        select(func.avg(Mission.duration_s), func.avg(Mission.distance_m),
               func.sum(Mission.distance_m))
        .where(Mission.status == MissionStatus.SUCCEEDED)).one()
    average_duration = float(row[0] or 0.0)
    average_distance = float(row[1] or 0.0)

    # Total distance counts EVERY mission: the robot really drove those
    # metres, even on the ones that failed.
    total = db.scalar(select(func.sum(Mission.distance_m))) or 0.0
    return round(average_duration, 1), round(average_distance, 2), round(float(total), 2)


def _robot_utilisation(db: Session) -> list[dict]:
    rows = []
    for robot in db.scalars(select(Robot).order_by(Robot.code)):
        stats = db.execute(
            select(func.count(Mission.id), func.sum(Mission.distance_m),
                   func.sum(Mission.duration_s))
            .where(Mission.robot_id == robot.id)).one()
        missions = int(stats[0] or 0)
        counts = _counts(db, robot_id=robot.id)
        navigating = db.scalar(
            select(func.sum(Mission.duration_s))
            .where(Mission.robot_id == robot.id,
                   Mission.status == MissionStatus.SUCCEEDED)) or 0.0
        rows.append({
            "robot_id": robot.id,
            "robot_code": robot.code,
            "missions": missions,
            "total_distance_m": round(float(stats[1] or 0.0), 2),
            "total_duration_s": round(float(stats[2] or 0.0), 1),
            "navigating_seconds": round(float(navigating), 1),
            "success_rate": counts["success_rate"],
        })
    return rows


def _failures(db: Session) -> list[dict]:
    """Group failures by reason so the common ones are obvious.

    Reasons are free text from move_base, so they are bucketed by keyword
    rather than exact string - otherwise every failure is its own category
    and the breakdown tells you nothing.
    """
    reasons = db.scalars(
        select(Mission.failure_reason).where(Mission.status == MissionStatus.FAILED))

    buckets: Counter[str] = Counter()
    for reason in reasons:
        text = (reason or "").lower()
        if not text:
            bucket = "Unknown"
        elif "disconnect" in text or "not connected" in text or "offline" in text:
            bucket = "Robot disconnected"
        elif "timed out" in text or "timeout" in text:
            bucket = "Mission timeout"
        elif "no path" in text or "unreachable" in text or "rejected" in text:
            bucket = "No path to goal"
        elif "abort" in text or "stuck" in text or "recovery" in text:
            bucket = "Stuck / obstacle"
        elif "battery" in text:
            bucket = "Low battery"
        else:
            bucket = "Other"
        buckets[bucket] += 1

    return [{"reason": reason, "count": count}
            for reason, count in buckets.most_common()]


def _busiest_destinations(db: Session, limit: int = 5) -> list[dict]:
    rows = db.execute(
        select(Mission.destination_name, func.count(Mission.id).label("count"))
        .group_by(Mission.destination_name)
        .order_by(func.count(Mission.id).desc())
        .limit(limit)).all()
    return [{"destination": name, "count": count} for name, count in rows]


def summary(db: Session) -> dict:
    average_duration, average_distance, total_distance = _averages(db)
    return {
        "counts": _counts(db),
        "average_duration_s": average_duration,
        "average_distance_m": average_distance,
        "total_distance_m": total_distance,
        "robots": _robot_utilisation(db),
        "failures": _failures(db),
        "busiest_destinations": _busiest_destinations(db),
    }
