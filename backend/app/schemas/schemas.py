"""
Pydantic schemas - the API's contract with the frontend.

Kept separate from the ORM models on purpose. The database has columns the
web should never see or set (internal ids, raw file paths), and the API has
computed fields the database does not store. Coupling them means every
schema change becomes a migration.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.mission import MissionStatus
from app.models.robot import RobotMode, RobotStatus

ORM = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------- robots
class RobotCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, examples=["RB001"])
    name: str = Field(min_length=1, max_length=120, examples=["Delivery Robot"])
    mode: RobotMode = RobotMode.SIMULATED


class RobotUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    mode: RobotMode | None = None


class RobotOut(BaseModel):
    model_config = ORM

    id: int
    code: str
    name: str
    status: RobotStatus
    mode: RobotMode
    battery_percent: float | None
    battery_voltage: float | None
    x: float | None
    y: float | None
    yaw: float | None
    linear_velocity: float | None
    firmware_version: str | None
    last_error: str | None
    last_seen: datetime | None
    created_at: datetime


# ------------------------------------------------------------------- maps
class MapCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    resolution: float = Field(gt=0, description="metres per pixel")
    origin_x: float
    origin_y: float
    origin_yaw: float = 0.0
    width_px: int = 0
    height_px: int = 0
    image_path: str
    yaml_path: str


class MapOut(BaseModel):
    model_config = ORM

    id: int
    name: str
    description: str | None
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float
    width_px: int
    height_px: int
    created_at: datetime


# ---------------------------------------------------------- destinations
class DestinationCreate(BaseModel):
    map_id: int
    name: str = Field(min_length=1, max_length=120, examples=["AI Lab"])
    description: str | None = None
    x: float
    y: float
    yaw: float = 0.0


class DestinationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    x: float | None = None
    y: float | None = None
    yaw: float | None = None


class DestinationOut(BaseModel):
    model_config = ORM

    id: int
    map_id: int
    name: str
    description: str | None
    x: float
    y: float
    yaw: float
    created_at: datetime


# --------------------------------------------------------------- missions
class MissionCreate(BaseModel):
    """What the website POSTs when someone clicks Deploy.

    Either a destination_id (the normal case) or a raw pose (for testing and
    for the map's click-to-send feature).
    """
    robot_id: int
    destination_id: int | None = None
    goal_x: float | None = None
    goal_y: float | None = None
    goal_yaw: float = 0.0
    preempt: bool = False


class MissionEventOut(BaseModel):
    model_config = ORM

    id: int
    level: str
    event: str
    detail: str
    created_at: datetime


class MissionOut(BaseModel):
    model_config = ORM

    id: int
    robot_id: int
    destination_id: int | None
    destination_name: str
    goal_x: float
    goal_y: float
    goal_yaw: float
    status: MissionStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    distance_m: float
    duration_s: float
    percent_complete: float
    failure_reason: str | None


class MissionDetailOut(MissionOut):
    events: list[MissionEventOut] = []


# -------------------------------------------------------------- analytics
class MissionCounts(BaseModel):
    total: int
    succeeded: int
    failed: int
    cancelled: int
    active: int
    success_rate: float = Field(description="percent of FINISHED missions")


class RobotUtilisation(BaseModel):
    robot_id: int
    robot_code: str
    missions: int
    total_distance_m: float
    total_duration_s: float
    navigating_seconds: float
    success_rate: float


class FailureBreakdown(BaseModel):
    reason: str
    count: int


class AnalyticsSummary(BaseModel):
    counts: MissionCounts
    average_duration_s: float
    average_distance_m: float
    total_distance_m: float
    robots: list[RobotUtilisation]
    failures: list[FailureBreakdown]
    busiest_destinations: list[dict]


# ------------------------------------------------------------ ROS status
class RosStatus(BaseModel):
    connected: bool
    host: str
    port: int
    detail: str = ""
