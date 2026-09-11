"""
ROSFleet backend.

    uvicorn app.main:app --reload --port 8000

Docs at http://localhost:8000/docs once running.

The backend starts successfully WITH OR WITHOUT ROS. A missing robot is a
normal state, not a startup failure - the dashboard should load and show
everything offline rather than refusing to start.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analytics, live, maps, missions, robots
from app.api.deps import set_ros_client
from app.core.config import get_settings
from app.core.database import create_all
from app.ros.ros_client import build_ros_client
from app.schemas.schemas import RosStatus
from app.services import ros_sync

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger("rosfleet")

settings = get_settings()
ros_client = build_ros_client(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    live.manager.bind_loop(asyncio.get_running_loop())

    set_ros_client(ros_client)
    ros_sync.register(ros_client)
    # Connect in a worker thread: roslibpy's connect blocks, and a robot that
    # is switched off must not delay the API coming up.
    await asyncio.get_running_loop().run_in_executor(None, ros_client.connect)
    if ros_client.connected:
        logger.info("connected to ROS at %s:%d",
                    settings.ros_bridge_host, settings.ros_bridge_port)
    else:
        logger.warning("ROS is not reachable; running in offline mode")

    yield

    ros_client.close()


app = FastAPI(
    title="ROSFleet API",
    description="Fleet management for the ROSFleet autonomous robot.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(robots.router)
app.include_router(maps.router)
app.include_router(missions.router)
app.include_router(analytics.router)
app.include_router(live.router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/ros/status", response_model=RosStatus, tags=["system"])
def ros_status():
    """Whether the backend can currently reach ROS.

    The dashboard shows this directly: "ROS disconnected" is a far more
    useful message than every robot silently reading as offline.
    """
    return RosStatus(
        connected=ros_client.connected,
        host=settings.ros_bridge_host,
        port=settings.ros_bridge_port,
        detail=getattr(ros_client, "last_error", "") or "",
    )
