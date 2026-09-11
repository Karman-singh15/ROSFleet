#!/usr/bin/env python3
"""
generate_sim_map.py - build a ground-truth occupancy grid from lab.world.

WHY: navigation needs a map, and normally you get one by driving the robot
around with gmapping. That is a real step you WILL do on the physical robot
(and in sim, for practice), but it should not block you from testing AMCL
and move_base on day one. This script derives a perfect map directly from
the Gazebo world geometry so simulation has a map immediately.

The real robot's map comes from gmapping + map_saver instead - see
docs/HOW_IT_WORKS.md, "Making a map".

    python3 scripts/generate_sim_map.py
"""
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- MUST MATCH ros_ws/src/robot_gazebo/worlds/lab.world ----
WALL_THICKNESS = 0.15
WALLS = [  # (x, y, yaw, length)
    (0.0, 4.0, 0.0, 10.0),          # north
    (0.0, -4.0, 0.0, 10.0),         # south
    (5.0, 0.0, math.pi / 2, 8.0),   # east
    (-5.0, 0.0, math.pi / 2, 8.0),  # west
    (-1.5, 1.8, 0.0, 5.0),          # partition 1
    (1.5, -1.0, math.pi / 2, 4.0),  # partition 2
    (-3.0, -1.5, math.pi / 2, 3.0), # partition 3
]
BOXES = [  # (x, y, size_x, size_y)
    (3.0, 2.5, 1.2, 0.8),     # table 1
    (-3.5, 3.0, 1.0, 0.6),    # table 2
    (0.5, -2.5, 0.5, 0.5),    # crate 1
    (-1.0, -0.5, 0.4, 0.4),   # crate 2
    (2.0, 0.0, 0.3, 0.3),     # pillar
]

RESOLUTION = 0.05        # m per pixel; matches gmapping's `delta`
ORIGIN_X, ORIGIN_Y = -5.6, -4.6
WIDTH = int(round(11.2 / RESOLUTION))
HEIGHT = int(round(9.2 / RESOLUTION))

FREE, OCCUPIED, UNKNOWN = 254, 0, 205


def build_grid():
    grid = [[UNKNOWN] * WIDTH for _ in range(HEIGHT)]

    def fill(cx, cy, size_x, size_y, yaw, value):
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        half_x = (abs(size_x * cos_y) + abs(size_y * sin_y)) / 2.0
        half_y = (abs(size_x * sin_y) + abs(size_y * cos_y)) / 2.0
        col0 = int((cx - half_x - ORIGIN_X) / RESOLUTION)
        col1 = int((cx + half_x - ORIGIN_X) / RESOLUTION)
        row0 = int((cy - half_y - ORIGIN_Y) / RESOLUTION)
        row1 = int((cy + half_y - ORIGIN_Y) / RESOLUTION)
        for row in range(max(0, row0), min(HEIGHT, row1 + 1)):
            for col in range(max(0, col0), min(WIDTH, col1 + 1)):
                wx = ORIGIN_X + (col + 0.5) * RESOLUTION
                wy = ORIGIN_Y + (row + 0.5) * RESOLUTION
                dx, dy = wx - cx, wy - cy
                local_x = dx * cos_y + dy * sin_y
                local_y = -dx * sin_y + dy * cos_y
                if abs(local_x) <= size_x / 2 and abs(local_y) <= size_y / 2:
                    grid[row][col] = value

    # Interior first, then stamp obstacles on top of it.
    fill(0.0, 0.0, 10.0 - WALL_THICKNESS, 8.0 - WALL_THICKNESS, 0.0, FREE)
    for x, y, yaw, length in WALLS:
        fill(x, y, length, WALL_THICKNESS, yaw, OCCUPIED)
    for x, y, size_x, size_y in BOXES:
        fill(x, y, size_x, size_y, 0.0, OCCUPIED)
    return grid


def write_map(grid, directory):
    if not os.path.isdir(directory):
        os.makedirs(directory)
    pgm_path = os.path.join(directory, "lab.pgm")
    # ROS grids are bottom-row-first; PGM is top-row-first.
    with open(pgm_path, "wb") as handle:
        handle.write(b"P5\n# ROSFleet ground-truth map of "
                     b"robot_gazebo/worlds/lab.world\n")
        handle.write(("%d %d\n255\n" % (WIDTH, HEIGHT)).encode())
        for row in reversed(grid):
            handle.write(bytes(row))

    with open(os.path.join(directory, "lab.yaml"), "w") as handle:
        handle.write(
            "# Occupancy grid for the simulated lab.\n"
            "# Generated from robot_gazebo/worlds/lab.world by\n"
            "# scripts/generate_sim_map.py, so simulation has a correct map\n"
            "# WITHOUT running SLAM first. The map you use on the real robot\n"
            "# comes from gmapping + map_saver instead.\n"
            "image: lab.pgm\n"
            "resolution: %.3f\n"
            "# [x, y, yaw] of the BOTTOM-LEFT pixel, in the map frame.\n"
            "origin: [%.3f, %.3f, 0.0]\n"
            "negate: 0\n"
            "# Darker than occupied_thresh*255 is an obstacle; lighter than\n"
            "# free_thresh*255 is free; anything between is unknown.\n"
            "occupied_thresh: 0.65\n"
            "free_thresh: 0.196\n" % (RESOLUTION, ORIGIN_X, ORIGIN_Y))
    return pgm_path


def main():
    grid = build_grid()
    for directory in (os.path.join(ROOT, "maps"),
                      os.path.join(ROOT, "ros_ws/src/robot_navigation/maps")):
        path = write_map(grid, directory)
        print("wrote %s" % path)

    occupied = sum(row.count(OCCUPIED) for row in grid)
    free = sum(row.count(FREE) for row in grid)
    print("%dx%d px = %.1f x %.1f m at %.2f m/px" %
          (WIDTH, HEIGHT, WIDTH * RESOLUTION, HEIGHT * RESOLUTION, RESOLUTION))
    print("occupied=%d free=%d unknown=%d" %
          (occupied, free, WIDTH * HEIGHT - occupied - free))


if __name__ == "__main__":
    main()
