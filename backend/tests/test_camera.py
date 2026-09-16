"""
Camera and recording tests.

Every one of these runs with no camera, no network and no robot: the hub is
built with a factory that returns FakeCameraSource, exactly as the ROS tests
inject FakeRosClient. If any test here opens a socket, that is the bug.
"""

import asyncio
import json
import os

import pytest

from app.api.camera import mjpeg_part
from app.api.deps import get_camera_hub, get_recordings
from app.main import app
from app.services.camera_service import (CameraFeed, CameraHub, FakeCameraSource,
                                         HttpMjpegSource)
from app.services.recording_service import RecordingManager, RecordingStore

# Two frames that are valid JPEG only in the ways this code cares about:
# they start with SOI and end with EOI.
FRAME_A = b"\xff\xd8" + b"first-frame-payload" + b"\xff\xd9"
FRAME_B = b"\xff\xd8" + b"second-frame-payload" + b"\xff\xd9"


@pytest.fixture
def camera_hub():
    hub = CameraHub(source_factory=lambda url: FakeCameraSource(
        [FRAME_A, FRAME_B], delay=0.001))
    app.dependency_overrides[get_camera_hub] = lambda: hub
    yield hub
    app.dependency_overrides.pop(get_camera_hub, None)


@pytest.fixture
def recordings(tmp_path):
    manager = RecordingManager(RecordingStore(str(tmp_path / "recordings")))
    os.makedirs(manager.store.root, exist_ok=True)
    app.dependency_overrides[get_recordings] = lambda: manager
    yield manager
    manager.stop_all()
    app.dependency_overrides.pop(get_recordings, None)


@pytest.fixture
def real_robot(client):
    """Cameras exist only on real robots, so most tests need one."""
    response = client.post("/api/robots", json={
        "code": "RB002", "name": "Field Robot", "mode": "REAL"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def camera_robot(client, real_robot):
    response = client.patch("/api/robots/%d" % real_robot["id"],
                            json={"camera_url": "http://192.168.1.51:81/stream"})
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ config
def test_robot_starts_with_no_camera(robot):
    assert robot["camera_url"] is None


def test_camera_url_can_be_set_and_cleared(client, real_robot):
    url = "http://192.168.1.51:81/stream"
    robot_id = real_robot["id"]
    response = client.patch("/api/robots/%d" % robot_id, json={"camera_url": url})
    assert response.status_code == 200
    assert response.json()["camera_url"] == url

    # An empty string clears it; omitting the field must leave it alone.
    response = client.patch("/api/robots/%d" % robot_id, json={"name": "Renamed"})
    assert response.json()["camera_url"] == url

    response = client.patch("/api/robots/%d" % robot_id, json={"camera_url": ""})
    assert response.json()["camera_url"] is None


# ------------------------------------------------- simulated robots opt out
def test_simulated_robot_cannot_be_given_a_camera(client, robot):
    response = client.patch("/api/robots/%d" % robot["id"],
                            json={"camera_url": "http://192.168.1.51:81/stream"})
    assert response.status_code == 409
    assert "SIMULATED" in response.json()["detail"]


def test_simulated_robot_cannot_be_created_with_a_camera(client):
    response = client.post("/api/robots", json={
        "code": "SIM9", "name": "Sim", "mode": "SIMULATED",
        "camera_url": "http://192.168.1.51:81/stream"})
    assert response.status_code == 409


def test_switching_to_simulated_drops_the_camera(client, camera_robot):
    response = client.patch("/api/robots/%d" % camera_robot["id"],
                            json={"mode": "SIMULATED"})
    assert response.status_code == 200
    assert response.json()["camera_url"] is None


def test_camera_endpoints_refuse_simulated_robots(client, robot, camera_hub,
                                                  recordings):
    robot_id = robot["id"]
    for path in ("/camera/stream", "/camera/snapshot"):
        response = client.get("/api/robots/%d%s" % (robot_id, path))
        assert response.status_code == 409, path
        assert "SIMULATED" in response.json()["detail"]

    response = client.post("/api/robots/%d/camera/recording" % robot_id)
    assert response.status_code == 409


def test_status_reports_simulated_as_unsupported(client, robot, camera_hub,
                                                 recordings):
    body = client.get("/api/robots/%d/camera" % robot["id"]).json()
    assert body["supported"] is False
    assert body["configured"] is False


def test_status_reports_real_robot_as_supported(client, camera_robot, camera_hub,
                                                recordings):
    body = client.get("/api/robots/%d/camera" % camera_robot["id"]).json()
    assert body["supported"] is True
    assert body["configured"] is True


def test_status_reports_unconfigured_camera(client, real_robot, camera_hub,
                                            recordings):
    response = client.get("/api/robots/%d/camera" % real_robot["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["streaming"] is False
    assert body["recording_id"] is None


def test_stream_without_a_camera_is_a_clear_error(client, real_robot, camera_hub):
    response = client.get("/api/robots/%d/camera/stream" % real_robot["id"])
    assert response.status_code == 409
    # The message has to say what to do about it, not just "conflict".
    assert "camera_url" in response.json()["detail"]


def test_camera_endpoints_404_for_unknown_robot(client, camera_hub, recordings):
    assert client.get("/api/robots/999/camera").status_code == 404
    assert client.get("/api/robots/999/camera/stream").status_code == 404


# ------------------------------------------------------------------ frames
def test_snapshot_returns_a_jpeg(client, camera_robot, camera_hub):
    response = client.get("/api/robots/%d/camera/snapshot" % camera_robot["id"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content in (FRAME_A, FRAME_B)
    assert response.headers["cache-control"] == "no-store"


def test_mjpeg_part_frames_a_jpeg_correctly():
    """The stream endpoint is an endless response by design, so its framing
    is tested here rather than by reading a response that never ends."""
    part = mjpeg_part(FRAME_A)
    assert part.startswith(b"--frame\r\n")
    assert b"Content-Type: image/jpeg\r\n" in part
    assert b"Content-Length: %d\r\n" % len(FRAME_A) in part
    # Headers and payload must be separated by exactly one blank line, or
    # browsers render nothing and give no error.
    head, _, body = part.partition(b"\r\n\r\n")
    assert body == FRAME_A + b"\r\n"


# --------------------------------------------------------------- recording
def test_recording_start_and_stop_writes_a_manifest(client, camera_robot,
                                                    camera_hub, recordings):
    robot_id = camera_robot["id"]
    response = client.post("/api/robots/%d/camera/recording" % robot_id,
                           json={"mission_id": 104})
    assert response.status_code == 201, response.text
    recording_id = response.json()["recording_id"]
    assert response.json()["mission_id"] == 104

    response = client.delete("/api/robots/%d/camera/recording" % robot_id)
    assert response.status_code == 200
    assert response.json()["stopped_at"] is not None

    manifest_path = os.path.join(recordings.store.root, recording_id,
                                 "manifest.json")
    with open(manifest_path) as handle:
        manifest = json.load(handle)
    assert manifest["mission_id"] == 104
    assert manifest["robot_id"] == robot_id
    assert len(manifest["frames"]) == manifest["frame_count"]


def test_recording_writes_frames_to_disk(tmp_path):
    """Frame writing, throttling and the manifest, at the service level."""
    store = RecordingStore(str(tmp_path))
    recording = store.create(robot_id=1, mission_id=104, max_fps=0)

    assert recording.accept(FRAME_A) is True
    assert recording.accept(FRAME_B) is True
    recording.stop()

    assert recording.frame_count_on_disk() == 2
    manifest = store.read_manifest(recording.recording_id)
    assert manifest["frame_count"] == 2
    assert manifest["total_bytes"] == len(FRAME_A) + len(FRAME_B)

    first = store.frame_path(recording.recording_id, 0)
    with open(first, "rb") as handle:
        assert handle.read() == FRAME_A

    # A stopped recording accepts nothing more.
    assert recording.accept(FRAME_A) is False


def test_recording_throttles_to_max_fps(tmp_path):
    store = RecordingStore(str(tmp_path))
    recording = store.create(robot_id=1, mission_id=None, max_fps=1.0)
    assert recording.accept(FRAME_A) is True
    # The second frame arrives immediately, well inside the 1 s gap.
    assert recording.accept(FRAME_B) is False
    recording.stop()
    assert len(recording.frames) == 1


def test_recording_manager_taps_and_untaps_the_feed(tmp_path):
    """Starting a recording must not open a second camera connection."""
    class FakeFeed:
        def __init__(self):
            self.taps = []

        def add_tap(self, tap):
            self.taps.append(tap)

        def remove_tap(self, tap):
            self.taps.remove(tap)

    feed = FakeFeed()
    manager = RecordingManager(RecordingStore(str(tmp_path)))
    recording = manager.start(robot_id=1, feed=feed, mission_id=9)
    assert len(feed.taps) == 1

    feed.taps[0](FRAME_A)
    assert len(recording.frames) == 1

    stopped = manager.stop(robot_id=1)
    assert stopped.recording_id == recording.recording_id
    assert feed.taps == []
    assert manager.active_for(1) is None


def test_stopping_without_a_recording_is_404(client, camera_robot, recordings):
    response = client.delete("/api/robots/%d/camera/recording" % camera_robot["id"])
    assert response.status_code == 404


def test_recordings_can_be_listed_and_filtered(client, camera_robot,
                                               camera_hub, recordings):
    robot_id = camera_robot["id"]
    client.post("/api/robots/%d/camera/recording" % robot_id,
                json={"mission_id": 7})
    client.delete("/api/robots/%d/camera/recording" % robot_id)

    listed = client.get("/api/recordings").json()
    assert len(listed) == 1
    # The listing must not carry every frame; that is what makes it a listing.
    assert "frames" not in listed[0]

    assert len(client.get("/api/recordings?mission_id=7").json()) == 1
    assert len(client.get("/api/recordings?mission_id=8").json()) == 0
    assert len(client.get("/api/recordings?robot_id=%d" % robot_id).json()) == 1


def test_active_recording_cannot_be_deleted(client, camera_robot, camera_hub,
                                            recordings):
    robot_id = camera_robot["id"]
    recording_id = client.post(
        "/api/robots/%d/camera/recording" % robot_id).json()["recording_id"]

    response = client.delete("/api/recordings/%s" % recording_id)
    assert response.status_code == 409

    client.delete("/api/robots/%d/camera/recording" % robot_id)
    assert client.delete("/api/recordings/%s" % recording_id).status_code == 204


def test_starting_twice_returns_the_same_recording(client, camera_robot,
                                                   camera_hub, recordings):
    robot_id = camera_robot["id"]
    first = client.post("/api/robots/%d/camera/recording" % robot_id).json()
    second = client.post("/api/robots/%d/camera/recording" % robot_id).json()
    assert first["recording_id"] == second["recording_id"]


def test_unknown_recording_is_404(client, recordings):
    assert client.get("/api/recordings/nope").status_code == 404
    assert client.get("/api/recordings/nope/frames/0").status_code == 404


# ----------------------------------------------------- MJPEG frame splitting
def test_feed_fans_out_to_two_subscribers():
    asyncio.run(_feed_fans_out())


async def _feed_fans_out():
    """The whole reason the hub exists: one upstream, many consumers."""
    feed = CameraFeed(FakeCameraSource([FRAME_A, FRAME_B], delay=0.001))

    async def take_one(stream):
        async for frame in stream:
            return frame

    first = feed.stream()
    second = feed.stream()
    frame_one = await take_one(first)
    frame_two = await take_one(second)

    assert frame_one in (FRAME_A, FRAME_B)
    assert frame_two in (FRAME_A, FRAME_B)
    await first.aclose()
    await second.aclose()
    await feed.aclose()


def test_feed_reports_upstream_failure_as_text():
    asyncio.run(_feed_reports_failure())


async def _feed_reports_failure():
    class Failing:
        async def frames(self):
            raise RuntimeError("camera unplugged")
            yield b""  # pragma: no cover - makes this an async generator

    feed = CameraFeed(Failing())
    feed.start()
    # Let the pump run and fail.
    for _ in range(10):
        await asyncio.sleep(0)
        if feed.error:
            break
    assert feed.error is not None
    assert "camera unplugged" in feed.error
    await feed.aclose()


def test_mjpeg_splitting_handles_frames_split_across_chunks():
    asyncio.run(_mjpeg_splitting())


async def _mjpeg_splitting():
    """A frame boundary rarely lines up with a TCP chunk boundary."""
    source = HttpMjpegSource("http://example.invalid/stream")

    class FakeResponse:
        def raise_for_status(self):
            pass

        async def aiter_bytes(self):
            # One frame arrives in three pieces, with multipart headers
            # interleaved the way the ESP32-CAM actually sends them.
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8first"
            yield b"-frame-payload\xff\xd9\r\n--frame\r\n"
            yield b"Content-Type: image/jpeg\r\n\r\n" + FRAME_B + b"\r\n"

    class FakeStream:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *a):
            return False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            return FakeStream()

    import app.services.camera_service as module
    original = module.httpx.AsyncClient
    module.httpx.AsyncClient = lambda *a, **k: FakeClient()
    try:
        frames = [frame async for frame in source.frames()]
    finally:
        module.httpx.AsyncClient = original

    assert frames == [FRAME_A, FRAME_B]
