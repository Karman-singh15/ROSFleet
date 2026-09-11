"""
API tests. Every one runs against the real FastAPI app with a fake ROS.

    python3 -m pytest backend/tests -v
"""

import pytest

from app.models.mission import MissionStatus
from app.models.robot import RobotStatus
from app.ros.ros_client import SERVICE_CANCEL_MISSION, SERVICE_START_MISSION


# ------------------------------------------------------------------ health
def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_ros_status_is_reported(client):
    body = client.get("/api/ros/status").json()
    assert "connected" in body and "port" in body


# ------------------------------------------------------------------ robots
def test_create_and_list_robots(client):
    created = client.post("/api/robots",
                          json={"code": "RB001", "name": "Delivery Robot"})
    assert created.status_code == 201
    assert created.json()["status"] == RobotStatus.OFFLINE.value

    robots = client.get("/api/robots").json()
    assert [r["code"] for r in robots] == ["RB001"]


def test_duplicate_robot_code_is_rejected(client, robot):
    again = client.post("/api/robots", json={"code": "RB001", "name": "Clone"})
    assert again.status_code == 409


def test_robot_starts_offline_with_no_telemetry(client, robot):
    assert client.get("/api/robots/%d" % robot["id"]).json()["status"] == "OFFLINE"


def test_unknown_robot_is_404(client):
    assert client.get("/api/robots/999").status_code == 404


def test_robot_can_be_renamed_and_deleted(client, robot):
    patched = client.patch("/api/robots/%d" % robot["id"], json={"name": "Scout"})
    assert patched.json()["name"] == "Scout"
    assert client.delete("/api/robots/%d" % robot["id"]).status_code == 204
    assert client.get("/api/robots/%d" % robot["id"]).status_code == 404


# -------------------------------------------------------------------- maps
def test_map_upload_reads_metadata_from_the_files(client, sample_map):
    # These values must come from the uploaded yaml/pgm, not from defaults -
    # the frontend uses them to convert clicks into world coordinates.
    assert sample_map["resolution"] == pytest.approx(0.05)
    assert sample_map["origin_x"] == pytest.approx(-1.0)
    assert sample_map["origin_y"] == pytest.approx(-2.0)
    assert sample_map["width_px"] == 40
    assert sample_map["height_px"] == 30


def test_map_upload_rejects_a_yaml_missing_resolution(client, tmp_path):
    yaml_path = tmp_path / "bad.yaml"
    pgm_path = tmp_path / "bad.pgm"
    yaml_path.write_text("image: bad.pgm\norigin: [0, 0, 0]\n")
    pgm_path.write_bytes(b"P5\n4 4\n255\n" + bytes([254] * 16))
    with open(yaml_path, "rb") as y, open(pgm_path, "rb") as p:
        response = client.post("/api/maps", data={"name": "Bad"},
                               files={"yaml_file": ("bad.yaml", y),
                                      "image_file": ("bad.pgm", p)})
    assert response.status_code == 400
    assert "resolution" in response.json()["detail"]


def test_map_upload_rejects_a_non_pgm_image(client, tmp_path):
    yaml_path = tmp_path / "m.yaml"
    png_path = tmp_path / "m.pgm"
    yaml_path.write_text("image: m.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n")
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    with open(yaml_path, "rb") as y, open(png_path, "rb") as p:
        response = client.post("/api/maps", data={"name": "PNG"},
                               files={"yaml_file": ("m.yaml", y),
                                      "image_file": ("m.pgm", p)})
    assert response.status_code == 400
    assert "PGM" in response.json()["detail"]


def test_duplicate_map_name_is_rejected(client, sample_map, tmp_path):
    yaml_path = tmp_path / "d.yaml"
    pgm_path = tmp_path / "d.pgm"
    yaml_path.write_text("image: d.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n")
    pgm_path.write_bytes(b"P5\n4 4\n255\n" + bytes([254] * 16))
    with open(yaml_path, "rb") as y, open(pgm_path, "rb") as p:
        response = client.post("/api/maps", data={"name": "Floor 1"},
                               files={"yaml_file": ("d.yaml", y),
                                      "image_file": ("d.pgm", p)})
    assert response.status_code == 400


# ------------------------------------------------------------ destinations
def test_create_destination(client, sample_map):
    response = client.post("/api/destinations", json={
        "map_id": sample_map["id"], "name": "Reception", "x": 1.0, "y": 2.0})
    assert response.status_code == 201
    assert response.json()["name"] == "Reception"


def test_duplicate_destination_name_on_one_map_is_rejected(client, destination):
    again = client.post("/api/destinations", json={
        "map_id": destination["map_id"], "name": "AI Lab", "x": 0.0, "y": 0.0})
    assert again.status_code == 409


def test_destination_on_a_missing_map_is_404(client):
    response = client.post("/api/destinations", json={
        "map_id": 999, "name": "Nowhere", "x": 0.0, "y": 0.0})
    assert response.status_code == 404


def test_destination_can_be_moved(client, destination):
    patched = client.patch("/api/destinations/%d" % destination["id"],
                           json={"x": 5.5, "y": -1.25})
    assert patched.json()["x"] == pytest.approx(5.5)
    assert patched.json()["y"] == pytest.approx(-1.25)
    # An unspecified field must not be wiped
    assert patched.json()["name"] == "AI Lab"


# ---------------------------------------------------------------- missions
def test_deploying_a_mission_sends_the_resolved_pose_to_ros(client, robot,
                                                            destination, ros):
    """The core flow: the website sends a NAME, ROS receives a POSE."""
    response = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]})
    assert response.status_code == 201, response.text
    mission = response.json()
    assert mission["destination_name"] == "AI Lab"
    assert mission["goal_x"] == pytest.approx(3.8)
    assert mission["goal_y"] == pytest.approx(3.4)

    assert len(ros.service_calls) == 1
    name, request = ros.service_calls[0]
    assert name == SERVICE_START_MISSION
    assert request["mission_id"] == mission["id"]
    assert request["goal_x"] == pytest.approx(3.8)
    assert request["goal_yaw"] == pytest.approx(1.57)


def test_robot_becomes_navigating_when_a_mission_starts(client, robot,
                                                         destination):
    client.post("/api/missions", json={"robot_id": robot["id"],
                                       "destination_id": destination["id"]})
    assert client.get("/api/robots/%d" % robot["id"]).json()["status"] == "NAVIGATING"


def test_mission_with_a_raw_pose_needs_no_destination(client, robot):
    response = client.post("/api/missions", json={
        "robot_id": robot["id"], "goal_x": 1.5, "goal_y": -2.5, "goal_yaw": 0.0})
    assert response.status_code == 201
    assert response.json()["destination_id"] is None


def test_mission_without_a_goal_is_rejected(client, robot):
    response = client.post("/api/missions", json={"robot_id": robot["id"]})
    assert response.status_code == 409
    assert "destination_id" in response.json()["detail"]


def test_mission_for_an_unknown_robot_is_rejected(client, destination):
    response = client.post("/api/missions", json={
        "robot_id": 999, "destination_id": destination["id"]})
    assert response.status_code == 409


def test_mission_for_an_unknown_destination_is_rejected(client, robot):
    response = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": 999})
    assert response.status_code == 409


def test_second_mission_is_refused_while_one_is_active(client, robot, destination):
    client.post("/api/missions", json={"robot_id": robot["id"],
                                       "destination_id": destination["id"]})
    second = client.post("/api/missions", json={"robot_id": robot["id"],
                                                "destination_id": destination["id"]})
    assert second.status_code == 409
    assert "already running" in second.json()["detail"]


def test_preempt_replaces_the_running_mission(client, robot, destination):
    first = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]}).json()
    second = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"],
        "preempt": True})
    assert second.status_code == 201
    assert client.get("/api/missions/%d" % first["id"]).json()["status"] == "CANCELLED"


def test_a_mission_ros_refuses_is_failed_not_left_queued(client, robot,
                                                          destination, ros):
    """If ROS says no, the row must not sit QUEUED forever waiting for a
    robot that never received the goal."""
    ros.service_responses[SERVICE_START_MISSION] = {
        "accepted": False, "message": "robot hardware is not connected"}

    response = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]})
    assert response.status_code == 409
    assert "not connected" in response.json()["detail"]

    missions = client.get("/api/missions").json()
    assert len(missions) == 1
    assert missions[0]["status"] == MissionStatus.FAILED.value
    assert missions[0]["failure_reason"] == "robot hardware is not connected"


def test_mission_can_be_cancelled(client, robot, destination, ros):
    mission = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]}).json()
    cancelled = client.post("/api/missions/%d/cancel" % mission["id"])
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert any(name == SERVICE_CANCEL_MISSION for name, _ in ros.service_calls)
    assert client.get("/api/robots/%d" % robot["id"]).json()["status"] == "IDLE"


def test_cancelling_a_finished_mission_is_rejected(client, robot, destination):
    mission = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]}).json()
    client.post("/api/missions/%d/cancel" % mission["id"])
    again = client.post("/api/missions/%d/cancel" % mission["id"])
    assert again.status_code == 409


def test_cancel_succeeds_even_when_ros_is_unreachable(client, robot,
                                                       destination, ros):
    """A mission left running in the database for a robot that is gone is
    worse than a cancel ROS never heard - the robot's watchdogs stop it."""
    mission = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]}).json()
    ros.set_connected(False)
    cancelled = client.post("/api/missions/%d/cancel" % mission["id"])
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


def test_mission_detail_includes_its_event_log(client, robot, destination):
    mission = client.post("/api/missions", json={
        "robot_id": robot["id"], "destination_id": destination["id"]}).json()
    detail = client.get("/api/missions/%d" % mission["id"]).json()
    events = [event["event"] for event in detail["events"]]
    assert "MISSION_CREATED" in events
    assert "GOAL_SENT" in events


def test_missions_can_be_filtered_by_robot_and_status(client, robot, destination):
    client.post("/api/missions", json={"robot_id": robot["id"],
                                       "destination_id": destination["id"]})
    assert len(client.get("/api/missions?robot_id=%d" % robot["id"]).json()) == 1
    assert client.get("/api/missions?robot_id=999").json() == []
    assert len(client.get("/api/missions?status=QUEUED").json()) == 1
    assert client.get("/api/missions?status=SUCCEEDED").json() == []
