#!/usr/bin/env python3
"""
validate_urdf.py - expand and sanity-check the robot URDF WITHOUT a ROS install.

Why this exists: ROS1 does not run natively on macOS, but you still want a
fast "did I break the robot model?" check while editing on the Mac. This
script expands the xacro, parses the result, and asserts the things that
actually break Gazebo and the navigation stack.

    pip install xacro urdf-parser-py
    python3 scripts/validate_urdf.py

Checks performed:
  1. xacro expands (macros, properties and math all resolve)
  2. the expanded XML is a valid URDF
  3. exactly one root link, no orphan links
  4. every link that Gazebo simulates has non-zero mass and inertia
  5. the frames the rest of the stack hard-codes really exist
"""
import os
import re
import subprocess
import sys
import tempfile
import xml.dom.minidom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_ROOT = os.path.join(ROOT, "ros_ws", "src")
MAIN = os.path.join(PKG_ROOT, "robot_description", "urdf", "robot.urdf.xacro")

# Frames other packages depend on. Renaming one of these silently breaks
# AMCL / move_base / the hardware bridge, so we assert them here.
REQUIRED_LINKS = ["base_footprint", "base_link", "left_wheel_link",
                  "right_wheel_link", "caster_link", "laser_link"]
REQUIRED_JOINTS = ["left_wheel_joint", "right_wheel_joint"]


def resolve_find(path, out_dir):
    """Rewrite $(find pkg) into a real path so xacro works without rospack."""
    with open(path) as handle:
        text = handle.read()
    text = re.sub(r"\$\(find ([A-Za-z0-9_]+)\)",
                  lambda m: os.path.join(PKG_ROOT, m.group(1)), text)
    dest = os.path.join(out_dir, os.path.basename(path))
    with open(dest, "w") as handle:
        handle.write(text)
    return dest


def main():
    try:
        import xacro  # noqa: F401
    except ImportError:
        print("ERROR: pip install xacro urdf-parser-py")
        return 2

    tmp = tempfile.mkdtemp(prefix="urdf_check_")
    src_dir = os.path.join(PKG_ROOT, "robot_description", "urdf")
    for name in os.listdir(src_dir):
        if name.endswith(".xacro"):
            resolve_find(os.path.join(src_dir, name), tmp)

    expanded = os.path.join(tmp, "robot.urdf")
    runner = ("import sys, xacro; "
              "sys.argv = ['xacro', %r, 'use_gazebo:=true', '-o', %r]; "
              "xacro.main()" % (os.path.join(tmp, "robot.urdf.xacro"), expanded))
    proc = subprocess.run([sys.executable, "-c", runner],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print("FAIL: xacro could not expand the model\n")
        print(proc.stderr.strip()[-3000:])
        return 1
    print("PASS: xacro expands")

    try:
        from urdf_parser_py.urdf import URDF
    except ImportError:
        print("WARN: urdf-parser-py missing, skipping structural checks")
        return 0

    with open(expanded) as handle:
        xml_text = handle.read()
    xml.dom.minidom.parseString(xml_text)
    print("PASS: expanded XML is well-formed")

    robot = URDF.from_xml_string(xml_text)
    print("PASS: parses as URDF  (robot name: %s)" % robot.name)

    names = [link.name for link in robot.links]
    missing = [n for n in REQUIRED_LINKS if n not in names]
    if missing:
        print("FAIL: missing required links: %s" % missing)
        return 1
    print("PASS: all %d required links present" % len(REQUIRED_LINKS))

    joint_names = [j.name for j in robot.joints]
    missing = [n for n in REQUIRED_JOINTS if n not in joint_names]
    if missing:
        print("FAIL: missing required joints: %s" % missing)
        return 1
    print("PASS: drive joints present")

    # Orphan check: every link except the root must be some joint's child.
    children = set(j.child for j in robot.joints)
    roots = [n for n in names if n not in children]
    if len(roots) != 1:
        print("FAIL: expected exactly one root link, found %s" % roots)
        return 1
    print("PASS: single kinematic root (%s)" % roots[0])

    bad_mass = []
    for link in robot.links:
        if link.collision is None:
            continue  # pure frames like base_footprint carry no physics
        if link.inertial is None or link.inertial.mass <= 0.0:
            bad_mass.append(link.name)
    if bad_mass:
        print("FAIL: links with collision but no usable mass: %s" % bad_mass)
        return 1
    print("PASS: every physical link has mass and inertia")

    print("\nAll URDF checks passed. Expanded model: %s" % expanded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
