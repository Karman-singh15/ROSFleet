"""A named place on a map.

This table is the reason the website can say "AI Lab" instead of
"x=3.8, y=3.4, yaw=1.57". ROS never sees the name; the backend resolves it
to a pose before calling /start_mission.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.robot import utcnow


class Destination(Base):
    __tablename__ = "destinations"
    # Two "Reception"s on the same floor would make the dropdown ambiguous;
    # the same name on a different floor is fine.
    __table_args__ = (UniqueConstraint("map_id", "name", name="uq_map_destination"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("maps.id", ondelete="CASCADE"),
                                        index=True)

    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Pose in the MAP frame - exactly what move_base expects.
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    yaw: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)

    map = relationship("Map", back_populates="destinations")
