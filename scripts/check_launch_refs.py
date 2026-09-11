#!/usr/bin/env python3
"""
check_launch_refs.py - resolve every $(find pkg)/path in every launch file
and confirm the target actually exists.

ROS only discovers a broken path at runtime, several seconds into a launch,
usually after Gazebo has already started - so a one-character typo costs a
full restart cycle to find. This finds them all in under a second.

Packages that are not in this workspace (move_base, amcl, gazebo_ros,
rosbridge_server, ...) come from the ROS installation and are reported as
EXTERNAL rather than as errors.

    python3 scripts/check_launch_refs.py
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ros_ws", "src")

# Packages expected to come from the ROS installation, not this repo.
EXTERNAL_PACKAGES = {
    "gazebo_ros", "move_base", "amcl", "map_server", "gmapping", "rviz",
    "robot_state_publisher", "joint_state_publisher_gui", "xacro",
    "teleop_twist_keyboard", "rplidar_ros", "rosbridge_server",
    "tf2_web_republisher", "dwa_local_planner", "global_planner",
}

# node type="..." entries we expect to find as executables in this workspace
WORKSPACE_PACKAGES = {
    os.path.basename(path)
    for path in glob.glob(os.path.join(SRC, "*"))
    if os.path.isdir(path)
}


def workspace_path(package):
    return os.path.join(SRC, package)


def main():
    launch_files = sorted(glob.glob(os.path.join(SRC, "*", "launch", "*.launch")))
    if not launch_files:
        print("no launch files found")
        return 1

    problems = []
    external_seen = set()
    checked = 0

    for launch_file in launch_files:
        text = open(launch_file).read()
        relative = os.path.relpath(launch_file, ROOT)

        # $(find pkg)/some/path  -> the path must exist
        for package, tail in re.findall(r"\$\(find ([A-Za-z0-9_]+)\)([^\"'\s]*)", text):
            if package in EXTERNAL_PACKAGES:
                external_seen.add(package)
                continue
            if package not in WORKSPACE_PACKAGES:
                problems.append("%s: unknown package '%s'" % (relative, package))
                continue
            if not tail:
                continue
            target = os.path.join(workspace_path(package), tail.lstrip("/"))
            checked += 1
            if not os.path.exists(target):
                problems.append("%s: $(find %s)%s does not exist" %
                                (relative, package, tail))

        # <node pkg="x" type="y"> -> y must be an executable in x
        for package, node_type in re.findall(
                r'<node[^>]*pkg="([^"]+)"[^>]*type="([^"]+)"', text):
            if package in EXTERNAL_PACKAGES:
                external_seen.add(package)
                continue
            if package not in WORKSPACE_PACKAGES:
                problems.append("%s: node from unknown package '%s'" %
                                (relative, package))
                continue
            matches = glob.glob(os.path.join(workspace_path(package), "**", node_type),
                                recursive=True)
            checked += 1
            if not matches:
                problems.append("%s: node type '%s' not found in package '%s'" %
                                (relative, node_type, package))
            elif not os.access(matches[0], os.X_OK):
                problems.append("%s: %s is not executable (chmod +x it, or "
                                "roslaunch cannot start it)" %
                                (relative, os.path.relpath(matches[0], ROOT)))

        # <include file="..."> without $(find ...) is a relative path trap
        for included in re.findall(r'<include[^>]*file="([^"]+)"', text):
            if "$(find" not in included:
                problems.append("%s: include uses a bare path %r; use "
                                "$(find pkg)/... so it works after install" %
                                (relative, included))

    print("checked %d launch files, %d references" % (len(launch_files), checked))
    print("external packages referenced (from the ROS install): %s" %
          ", ".join(sorted(external_seen)))
    print()

    if problems:
        print("FAIL - broken launch references:")
        for problem in problems:
            print("  * %s" % problem)
        return 1
    print("PASS: every launch reference resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
