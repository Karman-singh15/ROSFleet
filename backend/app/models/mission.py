"""Missions and their event log.

The mission table is the project's most valuable data: it is what every
analytics number is computed from. The states here MIRROR the ROS-side state
machine in mission_manager/state.py deliberately, so there is no translation
layer to get wrong.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.robot import utcnow


class MissionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    NAVIGATING = "NAVIGATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (MissionStatus.SUCCEEDED, MissionStatus.FAILED,
                        MissionStatus.CANCELLED)


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id", ondelete="CASCADE"),
                                          index=True)
    # Destinations can be deleted or renamed; a finished mission must keep
    # meaning anyway, so the name and pose are COPIED here at creation time
    # rather than only referenced.
    destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="SET NULL"), nullable=True)
    destination_name: Mapped[str] = mapped_column(String(120))

    goal_x: Mapped[float] = mapped_column(Float)
    goal_y: Mapped[float] = mapped_column(Float)
    goal_yaw: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[MissionStatus] = mapped_column(
        Enum(MissionStatus), default=MissionStatus.QUEUED, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)

    distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    percent_complete: Mapped[float] = mapped_column(Float, default=0.0)

    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    robot = relationship("Robot", back_populates="missions")
    events = relationship("MissionEvent", back_populates="mission",
                          cascade="all, delete-orphan",
                          order_by="MissionEvent.created_at")


class MissionEvent(Base):
    """One line of a mission's log, mirroring mission_manager/MissionEvent."""

    __tablename__ = "mission_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), index=True)

    level: Mapped[str] = mapped_column(String(16), default="INFO")
    event: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow, index=True)

    mission = relationship("Mission", back_populates="events")
