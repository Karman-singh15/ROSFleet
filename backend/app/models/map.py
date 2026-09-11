"""A saved occupancy grid: one floor of one building."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.robot import utcnow


class Map(Base):
    __tablename__ = "maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Paths to the saved .pgm and .yaml. Stored as paths rather than blobs
    # because map_server reads them off disk, and ROS needs a real file.
    image_path: Mapped[str] = mapped_column(String(512))
    yaml_path: Mapped[str] = mapped_column(String(512))

    # Copied out of the .yaml so the frontend can convert between pixels and
    # world coordinates WITHOUT parsing the map file itself. This is what
    # makes click-to-place-a-destination work in the browser.
    resolution: Mapped[float] = mapped_column(Float)     # m per pixel
    origin_x: Mapped[float] = mapped_column(Float)       # world coords of the
    origin_y: Mapped[float] = mapped_column(Float)       # bottom-left pixel
    origin_yaw: Mapped[float] = mapped_column(Float, default=0.0)
    width_px: Mapped[int] = mapped_column(Integer, default=0)
    height_px: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)

    destinations = relationship("Destination", back_populates="map",
                                cascade="all, delete-orphan")
