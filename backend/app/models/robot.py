"""A robot in the fleet."""

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RobotStatus(str, enum.Enum):
    OFFLINE = "OFFLINE"        # no telemetry recently
    IDLE = "IDLE"              # online, no mission
    NAVIGATING = "NAVIGATING"  # executing a mission
    ERROR = "ERROR"            # reporting a fault
    CHARGING = "CHARGING"


class RobotMode(str, enum.Enum):
    """Whether this robot is physical or a simulation.

    Stored because the dashboard should say so plainly - a demo where the
    audience cannot tell which robots are real is a worse demo.
    """
    REAL = "REAL"
    SIMULATED = "SIMULATED"


def utcnow() -> datetime:
    """Timezone-aware UTC. datetime.utcnow() is deprecated and returns a
    naive datetime, which then compares incorrectly against aware ones."""
    return datetime.now(timezone.utc)


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-facing identifier, e.g. "RB001". Unique because the website and
    # the ROS side both refer to robots by this, not by the row id.
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))

    status: Mapped[RobotStatus] = mapped_column(
        Enum(RobotStatus), default=RobotStatus.OFFLINE, index=True)
    mode: Mapped[RobotMode] = mapped_column(
        Enum(RobotMode), default=RobotMode.SIMULATED)

    battery_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_voltage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Last known pose in the map frame
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    yaw: Mapped[float | None] = mapped_column(Float, nullable=True)
    linear_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)

    firmware_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Drives the OFFLINE decision: see services/robot_service.py
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                       nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)

    missions = relationship("Mission", back_populates="robot",
                            cascade="all, delete-orphan")
