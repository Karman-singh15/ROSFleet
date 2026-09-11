"""
Convert a ROS occupancy grid (binary PGM) into a PNG the browser can display.

Browsers cannot render PGM, so the map page would show a broken image without
this. Written as a minimal encoder rather than pulling in Pillow: the whole
job is one zlib stream and four chunks, and it keeps the backend's dependency
list short enough to install anywhere.

PNG structure produced here:

    signature  8 bytes
    IHDR       width, height, bit depth 8, colour type 0 (greyscale)
    IDAT       zlib(each row prefixed with filter byte 0)
    IEND

Colour mapping, matching how RViz draws a map:
    0   (occupied) -> black
    205 (unknown)  -> mid grey
    254 (free)     -> near white
which is already what the PGM stores, so the values pass through unchanged.
"""

from __future__ import annotations

import struct
import zlib


class PgmError(Exception):
    pass


def read_pgm(path: str) -> tuple[int, int, bytes]:
    """Return (width, height, pixels) from a binary PGM (P5)."""
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(b"P5"):
        raise PgmError("not a binary PGM (P5)")

    fields: list[int] = []
    index = 2
    while len(fields) < 3:
        if index >= len(data):
            raise PgmError("truncated PGM header")
        if data[index : index + 1].isspace():
            index += 1
            continue
        if data[index : index + 1] == b"#":
            newline = data.find(b"\n", index)
            if newline < 0:
                raise PgmError("unterminated PGM comment")
            index = newline + 1
            continue
        start = index
        while index < len(data) and not data[index : index + 1].isspace():
            index += 1
        try:
            fields.append(int(data[start:index]))
        except ValueError:
            raise PgmError("malformed PGM header")
    index += 1  # exactly one whitespace byte separates header and data

    width, height, maxval = fields
    if maxval != 255:
        raise PgmError("only 8-bit PGM files are supported (maxval=%d)" % maxval)

    pixels = data[index : index + width * height]
    if len(pixels) != width * height:
        raise PgmError("PGM pixel data is %d bytes, expected %d"
                       % (len(pixels), width * height))
    return width, height, pixels


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def encode_png(width: int, height: int, pixels: bytes) -> bytes:
    """8-bit greyscale PNG."""
    if len(pixels) != width * height:
        raise PgmError("pixel buffer does not match the given dimensions")

    # Every scanline is prefixed with its filter type. 0 means "no filter",
    # which compresses fine for a map that is mostly flat runs of one value.
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw.extend(pixels[row * width : (row + 1) * width])

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def pgm_file_to_png(path: str) -> bytes:
    width, height, pixels = read_pgm(path)
    return encode_png(width, height, pixels)
