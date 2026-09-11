"""
Test fixtures.

Each test gets a fresh in-memory SQLite database and a FakeRosClient, so the
whole API is exercised with no PostgreSQL, no rosbridge and no robot.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.deps import get_ros  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.robot import RobotMode  # noqa: E402
from app.ros.ros_client import FakeRosClient  # noqa: E402


@pytest.fixture
def db_session():
    # StaticPool + a shared in-memory URL means every session in the test
    # sees the same database; without it each connection gets its own empty one.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def ros():
    return FakeRosClient()


@pytest.fixture
def client(db_session, ros):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_ros] = lambda: ros
    # The app's lifespan connects to real ROS; skip it by not using a context
    # manager, since nothing under test needs the startup hooks.
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def robot(client):
    response = client.post("/api/robots", json={
        "code": "RB001", "name": "Delivery Robot", "mode": RobotMode.SIMULATED.value})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def sample_map(client, tmp_path):
    """A real .yaml + .pgm pair, uploaded through the API."""
    yaml_path = tmp_path / "floor1.yaml"
    pgm_path = tmp_path / "floor1.pgm"
    width, height = 40, 30
    pgm_path.write_bytes(b"P5\n# test map\n%d %d\n255\n" % (width, height)
                         + bytes([254] * (width * height)))
    yaml_path.write_text(
        "image: floor1.pgm\nresolution: 0.050\norigin: [-1.0, -2.0, 0.0]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")

    with open(yaml_path, "rb") as yaml_handle, open(pgm_path, "rb") as pgm_handle:
        response = client.post(
            "/api/maps",
            data={"name": "Floor 1", "description": "test floor"},
            files={"yaml_file": ("floor1.yaml", yaml_handle, "text/yaml"),
                   "image_file": ("floor1.pgm", pgm_handle, "image/x-portable-graymap")})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def destination(client, sample_map):
    response = client.post("/api/destinations", json={
        "map_id": sample_map["id"], "name": "AI Lab",
        "x": 3.8, "y": 3.4, "yaw": 1.57})
    assert response.status_code == 201, response.text
    return response.json()
