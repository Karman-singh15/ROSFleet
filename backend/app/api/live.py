"""
Live updates to the browser.

    ROS ──rosbridge──> backend ──WebSocket──> browser

One broadcast hub. Every connected browser gets every fleet update, which is
right for a dashboard where all clients look at the same fleet; per-client
filtering would be premature here.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])


class ConnectionManager:
    """Tracks connected browsers and broadcasts to them."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the server's event loop.

        ROS callbacks arrive on roslibpy's own thread, which has no event
        loop. Broadcasting from there needs this reference to hand the work
        back to the right loop.
        """
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        message = json.dumps(payload, default=str)
        async with self._lock:
            targets = list(self._connections)
        dead = []
        for websocket in targets:
            try:
                await websocket.send_text(message)
            except Exception:
                # A browser that closed a laptop lid looks exactly like this.
                dead.append(websocket)
        if dead:
            async with self._lock:
                for websocket in dead:
                    self._connections.discard(websocket)

    def broadcast_threadsafe(self, payload: dict) -> None:
        """Broadcast from a non-async thread (i.e. from a ROS callback)."""
        if self._loop is None or self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(payload), self._loop)

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/ws")
async def live_updates(websocket: WebSocket):
    """Push fleet updates to the browser.

    Messages are {"type": ..., "data": {...}} with type one of:
        robot_update | mission_update | mission_event | ros_status
    """
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps(
            {"type": "hello", "data": {"clients": manager.count}}))
        while True:
            # The browser sends nothing meaningful; this receive exists to
            # notice the disconnect. Without it the socket lingers.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("websocket closed unexpectedly", exc_info=True)
    finally:
        await manager.disconnect(websocket)
