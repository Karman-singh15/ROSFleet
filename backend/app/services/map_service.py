"""
Map upload and parsing.

A ROS map is two files: a .yaml of metadata and a .pgm image. The website
uploads both; this module reads the metadata out of the YAML and the
dimensions out of the PGM header, and stores them as columns.

Why copy the metadata into the database: the frontend needs `resolution` and
`origin` to convert a click on the map image into world coordinates. Without
these columns the browser would have to fetch and parse the YAML itself, and
every map view would depend on ROS file formats.

    world_x = origin_x + pixel_col * resolution
    world_y = origin_y + (height_px - pixel_row) * resolution
"""

from __future__ import annotations

import os
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.map import Map


class MapError(Exception):
    """Invalid or unparseable map upload."""


def read_pgm_size(path: str) -> tuple[int, int]:
    """Width and height from a binary PGM header, without Pillow.

    Only the header is read; the pixel data can be megabytes and is never
    needed here.
    """
    with open(path, "rb") as handle:
        head = handle.read(256)
    if not head.startswith(b"P5"):
        raise MapError("map image is not a binary PGM (P5); map_saver "
                       "produces P5 files")

    fields: list[int] = []
    index = 2
    while len(fields) < 3 and index < len(head):
        while index < len(head) and head[index:index + 1].isspace():
            index += 1
        if head[index:index + 1] == b"#":               # comment line
            newline = head.find(b"\n", index)
            if newline < 0:
                break
            index = newline + 1
            continue
        start = index
        while index < len(head) and not head[index:index + 1].isspace():
            index += 1
        try:
            fields.append(int(head[start:index]))
        except ValueError:
            raise MapError("malformed PGM header")
    if len(fields) < 3:
        raise MapError("could not read the PGM header")
    return fields[0], fields[1]


def parse_map_yaml(text: str) -> dict:
    """Read the fields map_server cares about out of a map .yaml.

    Hand-parsed rather than pulled in via PyYAML so the backend has no hard
    dependency on it, and so the error messages can name the missing field.
    """
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()

    if "image" not in data:
        raise MapError("map yaml has no 'image' field")
    if "resolution" not in data:
        raise MapError("map yaml has no 'resolution' field")
    if "origin" not in data:
        raise MapError("map yaml has no 'origin' field")

    numbers = re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", data["origin"])
    if len(numbers) < 2:
        raise MapError("map yaml 'origin' must be [x, y, yaw]")

    try:
        resolution = float(data["resolution"])
    except ValueError:
        raise MapError("map yaml 'resolution' is not a number")
    if resolution <= 0:
        raise MapError("map yaml 'resolution' must be positive")

    return {
        "image": data["image"],
        "resolution": resolution,
        "origin_x": float(numbers[0]),
        "origin_y": float(numbers[1]),
        "origin_yaw": float(numbers[2]) if len(numbers) > 2 else 0.0,
    }


def list_maps(db: Session) -> list[Map]:
    return list(db.scalars(select(Map).order_by(Map.name)))


def get_map(db: Session, map_id: int) -> Map | None:
    return db.get(Map, map_id)


def create_map(db: Session, name: str, description: str | None,
               yaml_path: str, image_path: str) -> Map:
    if db.scalar(select(Map).where(Map.name == name)) is not None:
        raise MapError("a map called %r already exists" % name)
    if not os.path.exists(yaml_path):
        raise MapError("yaml file not found: %s" % yaml_path)
    if not os.path.exists(image_path):
        raise MapError("image file not found: %s" % image_path)

    with open(yaml_path) as handle:
        meta = parse_map_yaml(handle.read())
    width, height = read_pgm_size(image_path)

    record = Map(
        name=name, description=description,
        yaml_path=os.path.abspath(yaml_path),
        image_path=os.path.abspath(image_path),
        resolution=meta["resolution"],
        origin_x=meta["origin_x"], origin_y=meta["origin_y"],
        origin_yaw=meta["origin_yaw"],
        width_px=width, height_px=height,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def pixel_to_world(record: Map, col: float, row: float) -> tuple[float, float]:
    """Convert a click on the map image into map-frame coordinates.

    The row flip is the part people get wrong: image rows count DOWN from the
    top, ROS grid rows count UP from the bottom.
    """
    world_x = record.origin_x + col * record.resolution
    world_y = record.origin_y + (record.height_px - row) * record.resolution
    return world_x, world_y


def world_to_pixel(record: Map, x: float, y: float) -> tuple[float, float]:
    col = (x - record.origin_x) / record.resolution
    row = record.height_px - (y - record.origin_y) / record.resolution
    return col, row
