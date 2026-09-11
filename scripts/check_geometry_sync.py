#!/usr/bin/env python3
"""
check_geometry_sync.py - the robot's dimensions are written down in THREE
places, and if they ever disagree the robot misbehaves in a way that looks
like a software bug:

  1. ros_ws/src/robot_description/urdf/common_properties.xacro
         -> what Gazebo simulates and what TF/RViz draw
  2. ros_ws/src/robot_hardware/config/hardware.yaml
         -> what the host uses to turn encoder ticks into /odom
  3. firmware/esp32_robot/src/config.h
         -> what the ESP32 uses to turn /cmd_vel into wheel speeds

Symptom of a mismatch: the robot consistently over- or under-turns, AMCL
keeps losing its pose, and no amount of PID tuning helps - because nothing
is wrong with the control loop at all.

    python3 scripts/check_geometry_sync.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

XACRO = os.path.join(ROOT, "ros_ws/src/robot_description/urdf/common_properties.xacro")
YAML = os.path.join(ROOT, "ros_ws/src/robot_hardware/config/hardware.yaml")
HEADER = os.path.join(ROOT, "firmware/esp32_robot/src/config.h")

TOLERANCE = 1e-6


def read_xacro(path):
    text = open(path).read()
    out = {}
    for name, value in re.findall(
            r'<xacro:property\s+name="([^"]+)"\s+value="([^"]+)"', text):
        try:
            out[name] = float(value)
        except ValueError:
            pass
    return out


def read_yaml(path):
    """Minimal scalar parser - avoids making PyYAML a hard dependency."""
    out = {}
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line or line.startswith("-"):
            continue
        key, _, value = line.partition(":")
        try:
            out[key.strip()] = float(value.strip())
        except ValueError:
            pass
    return out


def read_header(path):
    text = open(path).read()
    out = {}
    for name, value in re.findall(
            r'^#define\s+([A-Z0-9_]+)\s+([-0-9.]+)f?\s*$', text, re.M):
        try:
            out[name] = float(value)
        except ValueError:
            pass
    return out


# (human label, xacro key, yaml key, header key)
COUPLED = [
    ("wheel radius",       "wheel_radius",           "wheel_radius",           "WHEEL_RADIUS_M"),
    ("wheel separation",   "wheel_separation",       "wheel_separation",       "WHEEL_SEPARATION_M"),
    ("max linear speed",   "max_linear_velocity",    "max_linear_velocity",    "MAX_LINEAR_MPS"),
    ("max angular speed",  "max_angular_velocity",   "max_angular_velocity",   "MAX_ANGULAR_RPS"),
]

# Not in the URDF (Gazebo has no encoders), but host and firmware must agree.
HOST_FIRMWARE_ONLY = [
    ("ticks per rev", "ticks_per_rev", "TICKS_PER_REV"),
]


def main():
    xacro = read_xacro(XACRO)
    yaml_values = read_yaml(YAML)
    header = read_header(HEADER)

    problems = []
    print("%-20s %12s %12s %12s" % ("QUANTITY", "URDF", "hardware.yaml", "config.h"))
    print("-" * 60)

    for label, xkey, ykey, hkey in COUPLED:
        values = [xacro.get(xkey), yaml_values.get(ykey), header.get(hkey)]
        missing = [k for k, v in zip((xkey, ykey, hkey), values) if v is None]
        if missing:
            problems.append("%s: not found as %s" % (label, ", ".join(missing)))
            shown = ["MISSING" if v is None else "%.4f" % v for v in values]
        else:
            shown = ["%.4f" % v for v in values]
            if max(values) - min(values) > TOLERANCE:
                problems.append("%s disagrees: %s" % (label, shown))
        print("%-20s %12s %12s %12s" % (label, shown[0], shown[1], shown[2]))

    for label, ykey, hkey in HOST_FIRMWARE_ONLY:
        y, h = yaml_values.get(ykey), header.get(hkey)
        shown = ["-", "MISSING" if y is None else "%.1f" % y,
                 "MISSING" if h is None else "%.1f" % h]
        if y is None or h is None:
            problems.append("%s: missing value" % label)
        elif abs(y - h) > TOLERANCE:
            problems.append("%s disagrees: yaml=%.1f header=%.1f" % (label, y, h))
        print("%-20s %12s %12s %12s" % (label, shown[0], shown[1], shown[2]))

    print()
    if problems:
        print("FAIL - the robot's geometry is inconsistent:")
        for problem in problems:
            print("  * %s" % problem)
        print("\nFix all three files, then re-run. A mismatch here makes the")
        print("robot turn the wrong amount and looks like a navigation bug.")
        return 1

    print("PASS: URDF, hardware.yaml and firmware config.h all agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
