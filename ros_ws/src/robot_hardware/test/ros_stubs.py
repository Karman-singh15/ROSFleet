"""
ros_stubs.py - a miniature fake ROS, just big enough to run hardware_bridge.py.

WHY: ROS1 will not install on macOS, but hardware_bridge.py is the riskiest
file in the project - it is where /cmd_vel becomes motor commands and encoder
ticks become /odom. Rather than leave it untested until the robot exists, we
inject these stubs into sys.modules so the real node file can be imported and
exercised on a laptop.

The stubs are deliberately dumb: publishers record what was published, timers
do not fire on their own (tests call the callbacks directly), and time is a
value the test controls. That makes every test deterministic.
"""

import sys
import types


# --------------------------------------------------------------- time
class Time(object):
    _now = 0.0

    def __init__(self, secs=0.0):
        self.secs = float(secs)

    @classmethod
    def now(cls):
        return Time(cls._now)

    @classmethod
    def set_now(cls, value):
        cls._now = float(value)

    def to_sec(self):
        return self.secs

    def __sub__(self, other):
        return Duration(self.secs - other.secs)

    def __add__(self, other):
        return Time(self.secs + other.to_sec())


class Duration(object):
    def __init__(self, secs=0.0):
        self.secs = float(secs)

    def to_sec(self):
        return self.secs


# --------------------------------------------------------- pub / sub
class Publisher(object):
    registry = {}

    def __init__(self, topic, msg_type, queue_size=1, latch=False):
        self.topic = topic
        self.msg_type = msg_type
        self.messages = []
        Publisher.registry.setdefault(topic, self)

    def publish(self, msg):
        self.messages.append(msg)

    @property
    def last(self):
        return self.messages[-1] if self.messages else None

    @classmethod
    def reset_all(cls):
        cls.registry = {}


class Subscriber(object):
    registry = {}

    def __init__(self, topic, msg_type, callback, queue_size=1):
        self.topic = topic
        self.callback = callback
        Subscriber.registry[topic] = self


class Timer(object):
    """Records the callback instead of running it; tests drive it by hand."""
    registry = []

    def __init__(self, period, callback, oneshot=False):
        self.period = period
        self.callback = callback
        Timer.registry.append(self)


# ------------------------------------------------------------- module
def build_rospy(params=None):
    params = dict(params or {})
    mod = types.ModuleType("rospy")

    def get_param(name, default=None):
        return params.get(name.lstrip("~"), default)

    mod.get_param = get_param
    mod.set_param = lambda name, value: params.__setitem__(name.lstrip("~"), value)
    mod.Publisher = Publisher
    mod.Subscriber = Subscriber
    mod.Timer = Timer
    mod.Time = Time
    mod.Duration = Duration
    mod.init_node = lambda *a, **k: None
    mod.spin = lambda: None
    mod.sleep = lambda secs: None
    mod.on_shutdown = lambda cb: None
    mod.is_shutdown = lambda: False
    for level in ("loginfo", "logwarn", "logerr", "logdebug",
                  "loginfo_throttle", "logwarn_throttle", "logerr_throttle",
                  "logdebug_throttle"):
        setattr(mod, level, lambda *a, **k: None)
    mod._params = params
    return mod


def _msg_class(name, fields):
    """Build a message class whose constructor mirrors genpy's kwargs style."""
    def __init__(self, **kwargs):
        for key, factory in fields.items():
            setattr(self, key, factory() if callable(factory) else factory)
        for key, value in kwargs.items():
            setattr(self, key, value)
    return type(name, (object,), {"__init__": __init__})


def install(params=None):
    """Put the stubs into sys.modules. Call BEFORE importing the node."""
    Publisher.reset_all()
    Subscriber.registry = {}
    Timer.registry = []
    Time.set_now(0.0)

    rospy = build_rospy(params)
    sys.modules["rospy"] = rospy

    Header = _msg_class("Header", {"stamp": None, "frame_id": ""})
    Vector3 = _msg_class("Vector3", {"x": 0.0, "y": 0.0, "z": 0.0})
    Quaternion = _msg_class("Quaternion", {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})
    Point = _msg_class("Point", {"x": 0.0, "y": 0.0, "z": 0.0})
    Pose = _msg_class("Pose", {"position": Point, "orientation": Quaternion})
    PoseWithCovariance = _msg_class("PoseWithCovariance",
                                    {"pose": Pose, "covariance": lambda: [0.0] * 36})
    Twist = _msg_class("Twist", {"linear": Vector3, "angular": Vector3})
    TwistWithCovariance = _msg_class("TwistWithCovariance",
                                     {"twist": Twist, "covariance": lambda: [0.0] * 36})
    Transform = _msg_class("Transform",
                           {"translation": Vector3, "rotation": Quaternion})
    TransformStamped = _msg_class("TransformStamped",
                                  {"header": Header, "child_frame_id": "",
                                   "transform": Transform})
    Odometry = _msg_class("Odometry", {"header": Header, "child_frame_id": "",
                                       "pose": PoseWithCovariance,
                                       "twist": TwistWithCovariance})
    JointState = _msg_class("JointState", {"header": Header, "name": list,
                                           "position": list, "velocity": list,
                                           "effort": list})
    Range = _msg_class("Range", {"header": Header, "radiation_type": 0,
                                 "field_of_view": 0.0, "min_range": 0.0,
                                 "max_range": 0.0, "range": 0.0})
    Range.ULTRASOUND = 0
    Range.INFRARED = 1
    Bool = _msg_class("Bool", {"data": False})
    RobotTelemetry = _msg_class("RobotTelemetry", {
        "header": Header, "connected": False, "battery_voltage": 0.0,
        "battery_percent": 0.0, "left_ticks": 0, "right_ticks": 0,
        "left_wheel_rps": 0.0, "right_wheel_rps": 0.0, "front_distance": 0.0,
        "link_latency_ms": 0.0, "firmware_version": "", "last_error": ""})

    def _pkg(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    _pkg("geometry_msgs")
    _pkg("geometry_msgs.msg", Twist=Twist, Quaternion=Quaternion, Vector3=Vector3,
         Point=Point, Pose=Pose, Transform=Transform,
         TransformStamped=TransformStamped)
    _pkg("nav_msgs")
    _pkg("nav_msgs.msg", Odometry=Odometry)
    _pkg("sensor_msgs")
    _pkg("sensor_msgs.msg", JointState=JointState, Range=Range)
    _pkg("std_msgs")
    _pkg("std_msgs.msg", Bool=Bool, Header=Header)

    class TransformBroadcaster(object):
        def __init__(self):
            self.sent = []

        def sendTransform(self, msg):
            self.sent.append(msg)

    _pkg("tf2_ros", TransformBroadcaster=TransformBroadcaster)

    # robot_hardware.msg is generated by catkin at build time; fake it.
    import robot_hardware
    msg_mod = types.ModuleType("robot_hardware.msg")
    msg_mod.RobotTelemetry = RobotTelemetry
    sys.modules["robot_hardware.msg"] = msg_mod
    robot_hardware.msg = msg_mod

    return rospy


def load_node(path, name="hardware_bridge_under_test"):
    """Import a ROS node .py file by path, after install() has run."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
