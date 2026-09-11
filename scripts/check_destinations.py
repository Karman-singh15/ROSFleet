#!/usr/bin/env python3
"""
check_destinations.py - verify every named destination is somewhere the
robot can actually stand.

A goal placed inside a wall, inside a table, or in unmapped space is
rejected by move_base with "goal is off the map" or aborted after the robot
crawls up to it and gives up. From the website it looks like the robot is
broken; the real fault is a coordinate typed in by hand.

This checks the goal AND a disc the size of the robot around it, because a
point in free space 5 cm from a wall is still unreachable for a 22 cm robot.

    python3 scripts/check_destinations.py
    python3 scripts/check_destinations.py --map maps/floor1.yaml \
        --destinations ros_ws/src/mission_manager/config/destinations.yaml
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FREE, OCCUPIED, UNKNOWN = 254, 0, 205


def read_pgm(path):
    """Minimal binary PGM (P5) reader - avoids depending on Pillow."""
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(b"P5"):
        raise ValueError("%s is not a binary PGM (P5)" % path)

    fields, index = [], 2
    while len(fields) < 3:
        while index < len(data) and data[index:index + 1].isspace():
            index += 1
        if data[index:index + 1] == b"#":                 # comment line
            index = data.index(b"\n", index) + 1
            continue
        start = index
        while index < len(data) and not data[index:index + 1].isspace():
            index += 1
        fields.append(int(data[start:index]))
    index += 1                                            # single whitespace
    width, height, _maxval = fields
    return width, height, data[index:index + width * height]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", default=os.path.join(ROOT, "maps/lab.yaml"))
    parser.add_argument("--destinations",
                        default=os.path.join(
                            ROOT, "ros_ws/src/mission_manager/config/destinations.yaml"))
    parser.add_argument("--radius", type=float, default=0.15,
                        help="robot clearance radius in metres")
    args = parser.parse_args()

    try:
        import yaml
    except ImportError:
        print("ERROR: pip install pyyaml")
        return 2

    map_meta = yaml.safe_load(open(args.map))
    pgm_path = os.path.join(os.path.dirname(os.path.abspath(args.map)),
                            map_meta["image"])
    resolution = float(map_meta["resolution"])
    origin_x, origin_y = float(map_meta["origin"][0]), float(map_meta["origin"][1])
    width, height, pixels = read_pgm(pgm_path)

    def sample(x, y):
        col = int((x - origin_x) / resolution)
        row = int((y - origin_y) / resolution)
        if not (0 <= col < width and 0 <= row < height):
            return None                                   # outside the map
        return pixels[(height - 1 - row) * width + col]    # PGM is top-down

    def status(x, y):
        steps = max(1, int(args.radius / resolution))
        worst = FREE
        for d_col in range(-steps, steps + 1):
            for d_row in range(-steps, steps + 1):
                if d_col ** 2 + d_row ** 2 > steps ** 2:
                    continue                              # keep it a disc
                value = sample(x + d_col * resolution, y + d_row * resolution)
                if value is None:
                    return "OFF MAP"
                if value == OCCUPIED:
                    return "BLOCKED"
                if value == UNKNOWN:
                    worst = UNKNOWN
        return "UNKNOWN SPACE" if worst == UNKNOWN else "ok"

    destinations = yaml.safe_load(open(args.destinations))["destinations"]
    print("map: %s  (%d x %d px @ %.3f m/px)" %
          (os.path.basename(args.map), width, height, resolution))
    print("robot clearance radius: %.2f m\n" % args.radius)

    failures = 0
    for destination in destinations:
        verdict = status(destination["x"], destination["y"])
        mark = "PASS" if verdict == "ok" else "FAIL"
        if verdict != "ok":
            failures += 1
        print("%-4s %-20s (%6.2f, %6.2f)  %s" %
              (mark, destination["name"], destination["x"], destination["y"],
               "" if verdict == "ok" else verdict))

    print()
    if failures:
        print("FAIL: %d destination(s) the robot cannot reach." % failures)
        print("Fix the coordinates, or move the destination. To read a real")
        print("pose off the robot:  rosrun tf tf_echo map base_footprint")
        return 1
    print("PASS: every destination is in reachable free space.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
