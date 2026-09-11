#!/usr/bin/env python3
"""
Seed the database with the simulated lab: one robot, the lab map, and the
destinations from mission_manager/config/destinations.yaml.

    cd backend && python3 seed.py

Run this once after starting the backend for the first time, so the website
has something to show before any real data exists. Idempotent: running it
again updates rather than duplicating.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal, create_all  # noqa: E402
from app.models.destination import Destination  # noqa: E402
from app.models.map import Map  # noqa: E402
from app.models.robot import Robot, RobotMode  # noqa: E402
from app.services import map_service  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_YAML = os.path.join(ROOT, "maps", "lab.yaml")
MAP_PGM = os.path.join(ROOT, "maps", "lab.pgm")
DESTINATIONS_YAML = os.path.join(
    ROOT, "ros_ws/src/mission_manager/config/destinations.yaml")


def read_destinations(path):
    """Parse the ROS destinations file without requiring PyYAML."""
    entries, current = [], None
    for raw in open(path):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current:
                entries.append(current)
            current = {"name": stripped.split(":", 1)[1].strip()}
        elif current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if key in ("x", "y", "yaw"):
                current[key] = float(value)
            elif key == "description":
                current[key] = value
    if current:
        entries.append(current)
    return [entry for entry in entries if "x" in entry and "y" in entry]


def main():
    create_all()
    db = SessionLocal()
    try:
        robot = db.query(Robot).filter(Robot.code == "RB001").one_or_none()
        if robot is None:
            robot = Robot(code="RB001", name="Delivery Robot",
                          mode=RobotMode.SIMULATED)
            db.add(robot)
            db.commit()
            print("created robot RB001")
        else:
            print("robot RB001 already exists")

        record = db.query(Map).filter(Map.name == "Simulated Lab").one_or_none()
        if record is None:
            if not os.path.exists(MAP_PGM):
                print("map not found - run: python3 scripts/generate_sim_map.py")
                return 1
            record = map_service.create_map(db, "Simulated Lab",
                                            "Generated from lab.world",
                                            MAP_YAML, MAP_PGM)
            print("created map 'Simulated Lab' (%dx%d px)"
                  % (record.width_px, record.height_px))
        else:
            print("map 'Simulated Lab' already exists")

        added = 0
        for entry in read_destinations(DESTINATIONS_YAML):
            existing = db.query(Destination).filter(
                Destination.map_id == record.id,
                Destination.name == entry["name"]).one_or_none()
            if existing is not None:
                # Keep an existing destination in step with the ROS file
                # rather than creating a duplicate.
                existing.x = entry["x"]
                existing.y = entry["y"]
                existing.yaw = entry.get("yaw", 0.0)
                continue
            db.add(Destination(map_id=record.id, name=entry["name"],
                               description=entry.get("description"),
                               x=entry["x"], y=entry["y"],
                               yaw=entry.get("yaw", 0.0)))
            added += 1
        db.commit()
        print("destinations: %d added, %d total" %
              (added, db.query(Destination).count()))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
