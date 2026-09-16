"""
Camera streaming.

The AI-Thinker ESP32-CAM serves MJPEG from a tiny web server that in
practice handles ONE client at a time. Open the dashboard in two tabs and
the second kills the first; add a recorder and it kills both. So the
browser never talks to the camera directly.

Instead the backend holds exactly one upstream connection per robot and
fans frames out to every subscriber - browser tabs, the recorder, a future
vision node. That is the whole reason this module exists, and it is also
why the frontend has no camera host in it anywhere: it asks the API.

    ESP32-CAM  --one connection-->  CameraHub  --> tab 1
                                             \\--> tab 2
                                              \\-> recorder

Nothing here imports ROS or the database. A camera is a URL that yields
JPEGs, which keeps it testable with no hardware - see FakeCameraSource.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import AsyncIterator, Callable, Protocol

import httpx

log = logging.getLogger(__name__)

# JPEG start-of-image and end-of-image markers. Scanning for these is more
# robust than trusting the multipart Content-Length header, which cheap
# camera firmware gets wrong often enough to matter. Inside entropy-coded
# JPEG data a 0xFF byte is always stuffed (followed by 0x00) or is a real
# marker, so 0xFFD9 cannot appear by accident.
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"

# Refuse to buffer more than this while hunting for the end of a frame. A
# camera that starts emitting garbage must not grow the process without
# bound; dropping the buffer costs one frame and recovers on the next SOI.
MAX_FRAME_BYTES = 2 * 1024 * 1024


class CameraSource(Protocol):
    """Anything that yields whole JPEG frames."""

    def frames(self) -> AsyncIterator[bytes]:
        ...


class HttpMjpegSource:
    """Pulls an MJPEG stream over HTTP and yields one JPEG per frame."""

    def __init__(self, url: str, *, connect_timeout: float = 5.0,
                 read_timeout: float = 10.0) -> None:
        self.url = url
        self._timeout = httpx.Timeout(read_timeout, connect=connect_timeout)

    async def frames(self) -> AsyncIterator[bytes]:
        buffer = bytearray()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("GET", self.url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)

                    while True:
                        start = buffer.find(SOI)
                        if start < 0:
                            # No frame beginning yet. Keep only the last byte
                            # in case a marker straddles two chunks.
                            if len(buffer) > 1:
                                del buffer[:-1]
                            break

                        end = buffer.find(EOI, start + 2)
                        if end < 0:
                            del buffer[:start]
                            if len(buffer) > MAX_FRAME_BYTES:
                                log.warning("camera %s: oversized frame, resyncing",
                                            self.url)
                                buffer.clear()
                            break

                        frame = bytes(buffer[start:end + 2])
                        del buffer[:end + 2]
                        yield frame


class FakeCameraSource:
    """A camera made of bytes. Used by the tests and by `mode: SIMULATED`
    robots, so every code path below runs with no hardware present."""

    def __init__(self, frames: list[bytes], *, delay: float = 0.0,
                 repeat: bool = True) -> None:
        self._frames = frames
        self._delay = delay
        self._repeat = repeat

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            for frame in self._frames:
                if self._delay:
                    await asyncio.sleep(self._delay)
                yield frame
            if not self._repeat:
                return


class CameraFeed:
    """One upstream connection, many subscribers.

    The upstream is opened when the first subscriber arrives and closed when
    the last one leaves, so an idle dashboard costs the robot nothing.
    """

    def __init__(self, source: CameraSource, *, name: str = "camera") -> None:
        self._source = source
        self._name = name
        self._subscribers: set[asyncio.Queue[bytes]] = set()
        self._task: asyncio.Task | None = None
        self._latest: bytes | None = None
        self._latest_at: float = 0.0
        self._error: str | None = None
        self._taps: list[Callable[[bytes], None]] = []

    # ------------------------------------------------------------- state
    @property
    def latest(self) -> bytes | None:
        return self._latest

    @property
    def latest_age(self) -> float | None:
        return None if self._latest_at == 0.0 else time.monotonic() - self._latest_at

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -------------------------------------------------------------- taps
    def add_tap(self, tap: Callable[[bytes], None]) -> None:
        """Register a side-channel that sees every frame - the recorder uses
        this. A tap keeps the upstream alive on its own."""
        self._taps.append(tap)
        self._ensure_running()

    def remove_tap(self, tap: Callable[[bytes], None]) -> None:
        with contextlib.suppress(ValueError):
            self._taps.remove(tap)
        self._stop_if_idle()

    # -------------------------------------------------------- subscribing
    async def stream(self) -> AsyncIterator[bytes]:
        """Yield frames for one consumer until it disconnects."""
        # maxsize=1 and drop-oldest: a browser tab on a slow link must fall
        # behind by dropping frames, never by growing a queue. Video is only
        # useful live, so the newest frame is the only one worth keeping.
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        self._ensure_running()

        # Send the cached frame immediately so the <img> paints at once
        # instead of staying blank until the camera's next frame.
        if self._latest is not None:
            queue.put_nowait(self._latest)

        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)
            self._stop_if_idle()

    # ----------------------------------------------------------- plumbing
    def start(self) -> None:
        """Open the upstream connection if it is not already open.

        Public because both subscribing and tapping need it, and because a
        caller that wants frames flowing without consuming them (the
        recorder) has no other way to ask.
        """
        self._ensure_running()

    def _ensure_running(self) -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # FastAPI runs `def` endpoints in a worker thread, which has no
            # event loop. Fail loudly here rather than leave a coroutine that
            # is never awaited and a camera that never starts.
            raise RuntimeError(
                "CameraFeed must be started from the event loop; make the "
                "calling endpoint 'async def'") from None
        self._error = None
        self._task = loop.create_task(self._pump())

    def _stop_if_idle(self) -> None:
        if self._subscribers or self._taps:
            return
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _pump(self) -> None:
        try:
            async for frame in self._source.frames():
                self._latest = frame
                self._latest_at = time.monotonic()

                for tap in list(self._taps):
                    try:
                        tap(frame)
                    except Exception:
                        log.exception("%s: frame tap failed", self._name)

                for queue in list(self._subscribers):
                    if queue.full():
                        # Drop the stale frame this consumer never collected.
                        with contextlib.suppress(asyncio.QueueEmpty):
                            queue.get_nowait()
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as text
            self._error = "%s: %s" % (type(exc).__name__, exc)
            log.warning("%s: stream ended: %s", self._name, self._error)

    async def aclose(self) -> None:
        self._subscribers.clear()
        self._taps.clear()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


class CameraHub:
    """All the feeds, keyed by robot id."""

    def __init__(self,
                 source_factory: Callable[[str], CameraSource] | None = None) -> None:
        # Injectable so the tests never open a socket.
        self._source_factory = source_factory or HttpMjpegSource
        self._feeds: dict[int, CameraFeed] = {}
        self._urls: dict[int, str] = {}

    def feed(self, robot_id: int, url: str) -> CameraFeed:
        # A changed URL means a different camera: drop the old feed rather
        # than quietly keep streaming the previous one.
        if self._urls.get(robot_id) != url:
            old = self._feeds.pop(robot_id, None)
            if old is not None:
                # Best effort: if there is no loop to schedule the close on,
                # dropping the reference is enough - the task is cancelled
                # when the feed is garbage collected.
                try:
                    asyncio.get_running_loop().create_task(old.aclose())
                except RuntimeError:
                    log.debug("no running loop to close the previous feed on")
            self._urls[robot_id] = url

        if robot_id not in self._feeds:
            self._feeds[robot_id] = CameraFeed(
                self._source_factory(url), name="robot %d camera" % robot_id)
        return self._feeds[robot_id]

    def existing(self, robot_id: int) -> CameraFeed | None:
        return self._feeds.get(robot_id)

    async def aclose(self) -> None:
        for feed in list(self._feeds.values()):
            await feed.aclose()
        self._feeds.clear()
        self._urls.clear()
