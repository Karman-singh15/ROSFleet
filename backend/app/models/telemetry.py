"""Periodic robot telemetry samples - the raw material for analytics.

Written at a low rate (not at ROS rates). A robot publishing telemetry at
5 Hz would produce 400k rows a day per robot, which is pointless for charts
that are drawn per minute. The service layer downsamples before inserting.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.robot import utcnow


class TelemetrySample(Base):
    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    robot_id: Mapped[int] = mapped_column(ForeignKey("robots.id", ondelete="CASCADE"),
                                          index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=utcnow, index=True)

    battery_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    linear_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
