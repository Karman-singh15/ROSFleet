"""Shared FastAPI dependencies."""

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.ros.ros_client import NullRosClient, RosClient
from app.services.camera_service import CameraHub
from app.services.recording_service import RecordingManager, RecordingStore

# The live ROS client, set once at startup by main.py's lifespan handler.
# Tests override the get_ros dependency instead of touching this.
_ros_client: RosClient = NullRosClient("not started")


def set_ros_client(client: RosClient) -> None:
    global _ros_client
    _ros_client = client


def get_ros() -> RosClient:
    return _ros_client


# One hub and one recording manager for the whole process. Both are stateful
# (open sockets, open files), so they are module singletons rather than
# per-request objects - and both are overridable, so the tests inject a hub
# backed by FakeCameraSource and never open a socket.
_camera_hub = CameraHub()
_recordings: RecordingManager | None = None


def set_camera_hub(hub: CameraHub) -> None:
    global _camera_hub
    _camera_hub = hub


def get_camera_hub() -> CameraHub:
    return _camera_hub


def get_recordings() -> RecordingManager:
    global _recordings
    if _recordings is None:
        _recordings = RecordingManager(
            RecordingStore(get_settings().recording_storage_dir))
    return _recordings


def set_recordings(manager: RecordingManager) -> None:
    global _recordings
    _recordings = manager


__all__ = ["get_db", "get_ros", "set_ros_client", "get_settings", "Settings",
           "get_camera_hub", "set_camera_hub", "get_recordings", "set_recordings"]
