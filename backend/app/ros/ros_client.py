"""
The backend's connection to ROS, over the rosbridge WebSocket.

    FastAPI  ──ws://localhost:9090──>  rosbridge  ──>  ROS

DESIGN: everything here is behind the `RosClient` interface, with three
implementations:

    RosBridgeClient  - the real thing, using roslibpy
    NullRosClient    - always disconnected; lets the whole backend and the
                       entire frontend be developed with no ROS running
    FakeRosClient    - records calls and lets tests inject messages

That indirection is what makes the backend testable. Without it, every test
would need a live robot.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Topic and service names. These MUST match the ROS side; they are collected
# here so a rename is a one-file change.
TOPIC_MISSION_STATUS = "/mission_status"
TOPIC_MISSION_EVENTS = "/mission_events"
TOPIC_ROBOT_TELEMETRY = "/robot_telemetry"
TOPIC_ODOM = "/odom"
SERVICE_START_MISSION = "/start_mission"
SERVICE_CANCEL_MISSION = "/cancel_mission"

TYPE_MISSION_STATUS = "mission_manager/MissionStatus"
TYPE_MISSION_EVENT = "mission_manager/MissionEvent"
TYPE_ROBOT_TELEMETRY = "robot_hardware/RobotTelemetry"
TYPE_ODOM = "nav_msgs/Odometry"
TYPE_START_MISSION = "mission_manager/StartMission"
TYPE_CANCEL_MISSION = "mission_manager/CancelMission"


class RosClient(Protocol):
    """What the rest of the backend is allowed to assume about ROS."""

    @property
    def connected(self) -> bool: ...

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def subscribe(self, topic: str, message_type: str,
                  callback: Callable[[dict], None]) -> None: ...

    def call_service(self, name: str, service_type: str,
                     request: dict) -> dict: ...


class NullRosClient:
    """Used when ros_enabled is false, or when nothing is listening.

    Never raises on connect - a missing robot is a normal state, not an
    error, and the dashboard should still load and show everything offline.
    """

    def __init__(self, reason: str = "ROS integration disabled"):
        self.reason = reason
        self.subscriptions: list[tuple[str, str]] = []

    @property
    def connected(self) -> bool:
        return False

    def connect(self) -> None:
        logger.info("ROS client: %s", self.reason)

    def close(self) -> None:
        pass

    def subscribe(self, topic: str, message_type: str,
                  callback: Callable[[dict], None]) -> None:
        self.subscriptions.append((topic, message_type))

    def call_service(self, name: str, service_type: str, request: dict) -> dict:
        # Shaped like a real refusal so callers need no special case.
        return {"accepted": False, "cancelled": False,
                "message": "not connected to ROS (%s)" % self.reason}


class FakeRosClient(NullRosClient):
    """For tests: records service calls, and can push messages to subscribers."""

    def __init__(self) -> None:
        super().__init__("fake client")
        self.service_calls: list[tuple[str, dict]] = []
        self.service_responses: dict[str, dict] = {}
        self._callbacks: dict[str, list[Callable[[dict], None]]] = {}
        self._connected = True

    @property
    def connected(self) -> bool:
        return self._connected

    def set_connected(self, value: bool) -> None:
        self._connected = value

    def subscribe(self, topic: str, message_type: str,
                  callback: Callable[[dict], None]) -> None:
        self.subscriptions.append((topic, message_type))
        self._callbacks.setdefault(topic, []).append(callback)

    def publish_to_subscribers(self, topic: str, message: dict) -> None:
        """Simulate ROS sending a message on `topic`."""
        for callback in self._callbacks.get(topic, []):
            callback(message)

    def call_service(self, name: str, service_type: str, request: dict) -> dict:
        self.service_calls.append((name, request))
        if not self._connected:
            return {"accepted": False, "cancelled": False,
                    "message": "not connected to ROS"}
        return self.service_responses.get(
            name, {"accepted": True, "cancelled": True, "message": "ok"})


class RosBridgeClient:
    """The real client. Wraps roslibpy, which runs its own IO thread."""

    def __init__(self, host: str, port: int, connect_timeout: float = 5.0):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self._ros: Any = None
        self._lock = threading.Lock()
        self._subscriptions: list[tuple[str, str, Callable[[dict], None]]] = []
        self.last_error = ""

    @property
    def connected(self) -> bool:
        return self._ros is not None and self._ros.is_connected

    def connect(self) -> None:
        try:
            import roslibpy
        except ImportError:
            self.last_error = "roslibpy is not installed"
            logger.warning("ROS client: %s", self.last_error)
            return

        with self._lock:
            try:
                self._ros = roslibpy.Ros(host=self.host, port=self.port)
                self._ros.run(timeout=self.connect_timeout)
                logger.info("ROS client: connected to %s:%d", self.host, self.port)
                self.last_error = ""
                # Re-establish subscriptions after a reconnect, otherwise the
                # backend goes silently deaf once rosbridge restarts.
                for topic, message_type, callback in list(self._subscriptions):
                    self._attach(topic, message_type, callback)
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("ROS client: could not connect to %s:%d (%s)",
                               self.host, self.port, exc)

    def close(self) -> None:
        with self._lock:
            if self._ros is not None:
                try:
                    self._ros.terminate()
                except Exception:
                    pass
                self._ros = None

    def _attach(self, topic: str, message_type: str,
                callback: Callable[[dict], None]) -> None:
        import roslibpy
        listener = roslibpy.Topic(self._ros, topic, message_type)

        def guarded(message: dict) -> None:
            # A raised exception inside a roslibpy callback kills its thread
            # and the backend silently stops receiving that topic forever.
            try:
                callback(message)
            except Exception:
                logger.exception("ROS callback failed for %s", topic)

        listener.subscribe(guarded)

    def subscribe(self, topic: str, message_type: str,
                  callback: Callable[[dict], None]) -> None:
        self._subscriptions.append((topic, message_type, callback))
        if self.connected:
            self._attach(topic, message_type, callback)

    def call_service(self, name: str, service_type: str, request: dict) -> dict:
        if not self.connected:
            return {"accepted": False, "cancelled": False,
                    "message": "not connected to ROS at %s:%d" % (self.host, self.port)}
        import roslibpy
        try:
            service = roslibpy.Service(self._ros, name, service_type)
            result = service.call(roslibpy.ServiceRequest(request), timeout=10)
            return dict(result)
        except Exception as exc:
            logger.warning("ROS service %s failed: %s", name, exc)
            return {"accepted": False, "cancelled": False,
                    "message": "service call failed: %s" % exc}


def build_ros_client(settings) -> RosClient:
    if not settings.ros_enabled:
        return NullRosClient("ros_enabled=false")
    return RosBridgeClient(settings.ros_bridge_host, settings.ros_bridge_port)
