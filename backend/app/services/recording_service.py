"""
Mission recording.

A recording is a directory of JPEG frames plus a manifest.json. Deliberately
not an mp4: encoding one needs ffmpeg on the host, and the single thing this
is for - "show me what the robot saw when mission 104 failed" - is served
better by frames you can step through one at a time than by a video file you
have to scrub. Frames also survive an interrupted recording; a half-written
mp4 does not.

The recorder is a TAP on the existing CameraFeed, not a second connection to
the camera. The ESP32-CAM could not survive a second one.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"


@dataclass
class RecordingFrame:
    index: int
    filename: str
    offset_seconds: float
    bytes: int


@dataclass
class Recording:
    """One recording session, on disk under <root>/<recording_id>/."""

    recording_id: str
    robot_id: int
    mission_id: int | None
    directory: str
    started_at: float
    # Cap the frame rate written to disk. The camera may push 25 fps; storing
    # every frame fills a laptop quickly and adds nothing to a review of a
    # mission. 5 fps is enough to see what happened. Zero means unthrottled.
    max_fps: float = 5.0
    frames: list[RecordingFrame] = field(default_factory=list)
    stopped_at: float | None = None
    _last_write: float = 0.0

    # ------------------------------------------------------------ writing
    def accept(self, frame: bytes) -> bool:
        """Called for every frame off the feed. Returns True if written."""
        if self.stopped_at is not None:
            return False

        now = time.monotonic()
        min_gap = 1.0 / self.max_fps if self.max_fps > 0 else 0.0
        if self._last_write and (now - self._last_write) < min_gap:
            return False
        self._last_write = now

        index = len(self.frames)
        filename = "frame_%05d.jpg" % index
        try:
            with open(os.path.join(self.directory, filename), "wb") as handle:
                handle.write(frame)
        except OSError:
            # A full disk must stop the recording, not take down the stream
            # every browser tab is also watching.
            log.exception("recording %s: write failed, stopping", self.recording_id)
            self.stopped_at = time.time()
            return False

        self.frames.append(RecordingFrame(
            index=index,
            filename=filename,
            offset_seconds=round(now - self._started_monotonic, 3),
            bytes=len(frame),
        ))
        return True

    # ----------------------------------------------------------- lifecycle
    def __post_init__(self) -> None:
        self._started_monotonic = time.monotonic()

    def stop(self) -> None:
        if self.stopped_at is None:
            self.stopped_at = time.time()
        self.write_manifest()

    @property
    def active(self) -> bool:
        return self.stopped_at is None

    @property
    def duration_seconds(self) -> float:
        end = self.stopped_at if self.stopped_at is not None else time.time()
        return round(max(0.0, end - self.started_at), 3)

    @property
    def total_bytes(self) -> int:
        return sum(frame.bytes for frame in self.frames)

    def frame_count_on_disk(self) -> int:
        """What actually landed, as opposed to what the manifest claims."""
        try:
            return len([name for name in os.listdir(self.directory)
                        if name.endswith(".jpg")])
        except OSError:
            return 0

    # ------------------------------------------------------------ manifest
    def to_dict(self) -> dict:
        return {
            "recording_id": self.recording_id,
            "robot_id": self.robot_id,
            "mission_id": self.mission_id,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "duration_seconds": self.duration_seconds,
            "frame_count": len(self.frames),
            "total_bytes": self.total_bytes,
            "max_fps": self.max_fps,
            "frames": [
                {"index": f.index, "filename": f.filename,
                 "offset_seconds": f.offset_seconds, "bytes": f.bytes}
                for f in self.frames
            ],
        }

    def write_manifest(self) -> None:
        path = os.path.join(self.directory, MANIFEST_NAME)
        # Write-then-rename: a crash mid-write leaves the previous manifest
        # intact rather than a truncated one that will not parse.
        temporary = path + ".tmp"
        try:
            with open(temporary, "w") as handle:
                json.dump(self.to_dict(), handle, indent=2)
            os.replace(temporary, path)
        except OSError:
            log.exception("recording %s: manifest write failed", self.recording_id)


class RecordingStore:
    """Creates, tracks and reads back recordings under one root directory."""

    def __init__(self, root: str) -> None:
        self.root = root

    # -------------------------------------------------------------- paths
    def _directory(self, recording_id: str) -> str:
        return os.path.join(self.root, recording_id)

    @staticmethod
    def make_id(robot_id: int, mission_id: int | None) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        suffix = "m%d" % mission_id if mission_id is not None else "adhoc"
        return "r%d-%s-%s" % (robot_id, stamp, suffix)

    # ------------------------------------------------------------ writing
    def create(self, robot_id: int, mission_id: int | None,
               max_fps: float = 5.0) -> Recording:
        recording_id = self.make_id(robot_id, mission_id)
        directory = self._directory(recording_id)
        os.makedirs(directory, exist_ok=True)
        recording = Recording(
            recording_id=recording_id,
            robot_id=robot_id,
            mission_id=mission_id,
            directory=directory,
            started_at=time.time(),
            max_fps=max_fps,
        )
        recording.write_manifest()
        return recording

    # ------------------------------------------------------------ reading
    def read_manifest(self, recording_id: str) -> dict | None:
        path = os.path.join(self._directory(recording_id), MANIFEST_NAME)
        try:
            with open(path) as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None

    def list_manifests(self) -> list[dict]:
        try:
            entries = sorted(os.listdir(self.root), reverse=True)
        except OSError:
            return []
        manifests = []
        for entry in entries:
            manifest = self.read_manifest(entry)
            if manifest is not None:
                # The frame list is long and useless in a listing.
                summary = {k: v for k, v in manifest.items() if k != "frames"}
                manifests.append(summary)
        return manifests

    def frame_path(self, recording_id: str, index: int) -> str | None:
        manifest = self.read_manifest(recording_id)
        if manifest is None:
            return None
        for frame in manifest.get("frames", []):
            if frame["index"] == index:
                candidate = os.path.join(self._directory(recording_id),
                                         frame["filename"])
                return candidate if os.path.exists(candidate) else None
        return None

    def delete(self, recording_id: str) -> bool:
        directory = self._directory(recording_id)
        if not os.path.isdir(directory):
            return False
        for name in os.listdir(directory):
            with_suppressed_errors(os.remove, os.path.join(directory, name))
        with_suppressed_errors(os.rmdir, directory)
        return True


def with_suppressed_errors(function, *args) -> None:
    try:
        function(*args)
    except OSError:
        log.warning("could not remove %s", args, exc_info=True)


class RecordingManager:
    """At most one active recording per robot, tapping that robot's feed."""

    def __init__(self, store: RecordingStore) -> None:
        self.store = store
        self._active: dict[int, Recording] = {}
        self._taps: dict[int, object] = {}

    def active_for(self, robot_id: int) -> Recording | None:
        return self._active.get(robot_id)

    def is_active(self, recording_id: str) -> bool:
        return any(r.recording_id == recording_id for r in self._active.values())

    def start(self, robot_id: int, feed, mission_id: int | None = None,
              max_fps: float = 5.0) -> Recording:
        existing = self._active.get(robot_id)
        if existing is not None and existing.active:
            return existing

        recording = self.store.create(robot_id, mission_id, max_fps=max_fps)

        def tap(frame: bytes) -> None:
            recording.accept(frame)

        feed.add_tap(tap)
        self._active[robot_id] = recording
        self._taps[robot_id] = (feed, tap)
        return recording

    def stop(self, robot_id: int) -> Recording | None:
        recording = self._active.pop(robot_id, None)
        pair = self._taps.pop(robot_id, None)
        if pair is not None:
            feed, tap = pair
            feed.remove_tap(tap)
        if recording is not None:
            recording.stop()
        return recording

    def stop_all(self) -> None:
        for robot_id in list(self._active):
            self.stop(robot_id)
