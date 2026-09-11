"""Shared FastAPI dependencies."""

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.ros.ros_client import NullRosClient, RosClient

# The live ROS client, set once at startup by main.py's lifespan handler.
# Tests override the get_ros dependency instead of touching this.
_ros_client: RosClient = NullRosClient("not started")


def set_ros_client(client: RosClient) -> None:
    global _ros_client
    _ros_client = client


def get_ros() -> RosClient:
    return _ros_client


__all__ = ["get_db", "get_ros", "set_ros_client", "get_settings", "Settings"]
