"""
Application settings, read from the environment.

Defaults are chosen so the backend RUNS WITH NO CONFIGURATION AT ALL:
SQLite on disk, rosbridge on localhost. That matters because it means you can
develop the API and the frontend on a train with no Docker, no PostgreSQL and
no robot, and only switch to the real thing when you need it.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ROSFleet"
    debug: bool = True

    # SQLite by default; in Docker this becomes
    #   postgresql+psycopg2://rosfleet:rosfleet@db:5432/rosfleet
    database_url: str = "sqlite:///./rosfleet.db"

    # rosbridge websocket, started by robot_bringup/launch/rosbridge.launch
    ros_bridge_host: str = "localhost"
    ros_bridge_port: int = 9090
    # When false the backend runs fully standalone and reports every robot as
    # offline. Useful for frontend work with no ROS running.
    ros_enabled: bool = True

    # A robot that has not sent telemetry for this long is presumed offline.
    robot_offline_after_seconds: float = 5.0

    # Where uploaded map files are stored
    map_storage_dir: str = "./storage/maps"

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    """Cached so the settings object is a singleton; tests override the
    dependency rather than mutating this."""
    return Settings()
