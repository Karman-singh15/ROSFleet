"""
Camera endpoints.

The browser talks only to these. It never learns the camera's address, which
means the ESP32-CAM can sit on the robot's own network, can change IP, or can
not exist at all, and the frontend does not change.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_camera_hub, get_db, get_recordings, get_settings
from app.models.robot import RobotMode
from app.schemas.schemas import (CameraStatus, RecordingOut, RecordingStart,
                                 RecordingSummary)
from app.services import robot_service
from app.services.camera_service import CameraHub
from app.services.recording_service import RecordingManager

router = APIRouter(tags=["camera"])

# Any boundary works as long as it cannot occur inside JPEG data; this one is
# the conventional choice and is what browsers are used to seeing.
BOUNDARY = "frame"


def mjpeg_part(frame: bytes, boundary: str = BOUNDARY) -> bytes:
    """Wrap one JPEG as a multipart/x-mixed-replace part.

    A module-level function rather than an inline f-string so it can be
    tested without consuming an endless stream through a test client.
    """
    return (b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
            + frame + b"\r\n")


def _robot_with_camera(robot_id: int, db: Session):
    robot = robot_service.get_robot(db, robot_id)
    if robot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "robot not found")
    if robot.mode is RobotMode.SIMULATED:
        # A simulated robot has no camera and never will: Gazebo's robot
        # carries no camera sensor, and pointing a simulated robot at a real
        # camera would put a physical view behind a fake pose. The camera is
        # a property of real hardware only.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "robot %s is SIMULATED; the camera is only available on real robots"
            % robot.code)
    if not robot.camera_url:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "robot %s has no camera configured; set camera_url on the robot"
            % robot.code)
    return robot


# ------------------------------------------------------------------ status
@router.get("/api/robots/{robot_id}/camera", response_model=CameraStatus)
def camera_status(robot_id: int,
                  db: Session = Depends(get_db),
                  hub: CameraHub = Depends(get_camera_hub),
                  recordings: RecordingManager = Depends(get_recordings)):
    robot = robot_service.get_robot(db, robot_id)
    if robot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "robot not found")

    feed = hub.existing(robot_id)
    active = recordings.active_for(robot_id)
    stale_after = get_settings().camera_stale_after_seconds
    age = feed.latest_age if feed else None
    supported = robot.mode is not RobotMode.SIMULATED

    return CameraStatus(
        robot_id=robot_id,
        supported=supported,
        configured=supported and bool(robot.camera_url),
        streaming=bool(feed and feed.running),
        viewers=feed.subscriber_count if feed else 0,
        last_frame_age_seconds=age,
        # "Streaming" and "healthy" are different questions: the upstream task
        # can be alive while the camera has stopped sending.
        stale=bool(age is not None and age > stale_after),
        error=feed.error if feed else None,
        recording_id=active.recording_id if active else None,
    )


# ------------------------------------------------------------------ stream
@router.get("/api/robots/{robot_id}/camera/stream")
async def camera_stream(robot_id: int,
                        db: Session = Depends(get_db),
                        hub: CameraHub = Depends(get_camera_hub)):
    """MJPEG, straight into an <img src>. No JavaScript needed to display it."""
    robot = _robot_with_camera(robot_id, db)
    feed = hub.feed(robot_id, robot.camera_url)

    async def multipart():
        async for frame in feed.stream():
            yield mjpeg_part(frame)

    return StreamingResponse(
        multipart(),
        media_type="multipart/x-mixed-replace; boundary=%s" % BOUNDARY,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"},
    )


@router.get("/api/robots/{robot_id}/camera/snapshot")
async def camera_snapshot(robot_id: int,
                          db: Session = Depends(get_db),
                          hub: CameraHub = Depends(get_camera_hub)):
    """The most recent frame as a plain JPEG."""
    robot = _robot_with_camera(robot_id, db)
    feed = hub.feed(robot_id, robot.camera_url)

    frame = feed.latest
    if frame is None:
        # Nothing cached: attach briefly and take the first frame that lands.
        async for first in feed.stream():
            frame = first
            break

    if frame is None:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT,
                            feed.error or "no frame available from the camera")

    return Response(content=frame, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------- recording
@router.post("/api/robots/{robot_id}/camera/recording",
             response_model=RecordingOut, status_code=status.HTTP_201_CREATED)
async def start_recording(robot_id: int,
                    payload: RecordingStart | None = None,
                    db: Session = Depends(get_db),
                    hub: CameraHub = Depends(get_camera_hub),
                    recordings: RecordingManager = Depends(get_recordings)):
    robot = _robot_with_camera(robot_id, db)
    feed = hub.feed(robot_id, robot.camera_url)
    mission_id = payload.mission_id if payload else None
    recording = recordings.start(
        robot_id, feed, mission_id=mission_id,
        max_fps=get_settings().recording_max_fps)
    return RecordingOut(**recording.to_dict())


@router.delete("/api/robots/{robot_id}/camera/recording",
               response_model=RecordingOut)
async def stop_recording(robot_id: int,
                   recordings: RecordingManager = Depends(get_recordings)):
    recording = recordings.stop(robot_id)
    if recording is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "no active recording for this robot")
    return RecordingOut(**recording.to_dict())


@router.get("/api/recordings", response_model=list[RecordingSummary])
def list_recordings(robot_id: int | None = Query(default=None),
                    mission_id: int | None = Query(default=None),
                    recordings: RecordingManager = Depends(get_recordings)):
    manifests = recordings.store.list_manifests()
    if robot_id is not None:
        manifests = [m for m in manifests if m.get("robot_id") == robot_id]
    if mission_id is not None:
        manifests = [m for m in manifests if m.get("mission_id") == mission_id]
    return [RecordingSummary(**m) for m in manifests]


@router.get("/api/recordings/{recording_id}", response_model=RecordingOut)
def get_recording(recording_id: str,
                  recordings: RecordingManager = Depends(get_recordings)):
    manifest = recordings.store.read_manifest(recording_id)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recording not found")
    return RecordingOut(**manifest)


@router.get("/api/recordings/{recording_id}/frames/{index}")
def get_recording_frame(recording_id: str, index: int,
                        recordings: RecordingManager = Depends(get_recordings)):
    path = recordings.store.frame_path(recording_id, index)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "frame not found")
    with open(path, "rb") as handle:
        return Response(content=handle.read(), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000"})


@router.delete("/api/recordings/{recording_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_recording(recording_id: str,
                     recordings: RecordingManager = Depends(get_recordings)):
    # Refuse to delete something still being written to; stop it first.
    if recordings.is_active(recording_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "recording is still active; stop it before deleting")
    if not recordings.store.delete(recording_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recording not found")
