"""
Tests for the PGM -> PNG conversion that makes maps displayable in a browser.

A hand-written encoder deserves a decoder in its tests: checking only the
header would pass even if every pixel were wrong.
"""

import struct
import zlib

import pytest

from app.services.pgm_to_png import PgmError, encode_png, pgm_file_to_png, read_pgm

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode_png(data: bytes) -> tuple[int, int, bytes]:
    """Minimal PNG reader: unpacks IHDR and the greyscale IDAT scanlines."""
    assert data[:8] == PNG_SIGNATURE, "missing PNG signature"

    index = 8
    width = height = 0
    idat = b""
    saw_iend = False
    while index < len(data):
        length = struct.unpack(">I", data[index:index + 4])[0]
        tag = data[index + 4:index + 8]
        payload = data[index + 8:index + 8 + length]
        stored_crc = struct.unpack(">I", data[index + 8 + length:index + 12 + length])[0]
        assert stored_crc == zlib.crc32(tag + payload) & 0xFFFFFFFF, \
            "chunk %r has a bad CRC" % tag
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", payload[:10])
            assert depth == 8 and colour == 0, "expected 8-bit greyscale"
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            saw_iend = True
        index += 12 + length

    assert saw_iend, "PNG has no IEND chunk"

    raw = zlib.decompress(idat)
    pixels = bytearray()
    stride = width + 1
    for row in range(height):
        assert raw[row * stride] == 0, "expected filter type 0"
        pixels.extend(raw[row * stride + 1:(row + 1) * stride])
    return width, height, bytes(pixels)


def make_pgm(tmp_path, width, height, pixels, comment=b"# test\n"):
    path = tmp_path / "map.pgm"
    path.write_bytes(b"P5\n" + comment + b"%d %d\n255\n" % (width, height)
                     + bytes(pixels))
    return str(path)


# ------------------------------------------------------------- round trip
def test_every_pixel_survives_the_conversion(tmp_path):
    width, height = 7, 5
    pixels = [(row * width + col) * 3 % 256
              for row in range(height) for col in range(width)]
    path = make_pgm(tmp_path, width, height, pixels)

    decoded_w, decoded_h, decoded = decode_png(pgm_file_to_png(path))
    assert (decoded_w, decoded_h) == (width, height)
    assert list(decoded) == pixels


def test_occupancy_values_pass_through_unchanged(tmp_path):
    """0 occupied, 205 unknown, 254 free - these must not be remapped, or the
    map renders with walls and free space the wrong way round."""
    pixels = [0, 205, 254, 0, 205, 254]
    path = make_pgm(tmp_path, 3, 2, pixels)
    _, _, decoded = decode_png(pgm_file_to_png(path))
    assert list(decoded) == pixels


def test_the_real_generated_lab_map_converts(tmp_path):
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    pgm = os.path.join(root, "maps", "lab.pgm")
    if not os.path.exists(pgm):
        pytest.skip("run scripts/generate_sim_map.py first")

    width, height, source = read_pgm(pgm)
    decoded_w, decoded_h, decoded = decode_png(pgm_file_to_png(pgm))
    assert (decoded_w, decoded_h) == (width, height)
    assert decoded == source


def test_single_pixel_image(tmp_path):
    path = make_pgm(tmp_path, 1, 1, [128])
    assert decode_png(pgm_file_to_png(path))[2] == bytes([128])


# ---------------------------------------------------------- header parsing
def test_header_without_a_comment_parses(tmp_path):
    path = make_pgm(tmp_path, 2, 2, [1, 2, 3, 4], comment=b"")
    assert decode_png(pgm_file_to_png(path))[2] == bytes([1, 2, 3, 4])


def test_multiple_comment_lines_parse(tmp_path):
    path = make_pgm(tmp_path, 2, 2, [1, 2, 3, 4],
                    comment=b"# one\n# two\n# three\n")
    assert decode_png(pgm_file_to_png(path))[2] == bytes([1, 2, 3, 4])


# -------------------------------------------------------------- rejections
def test_non_pgm_is_rejected(tmp_path):
    path = tmp_path / "x.pgm"
    path.write_bytes(b"P3\n2 2\n255\n1 2 3 4")
    with pytest.raises(PgmError, match="P5"):
        pgm_file_to_png(str(path))


def test_truncated_pixel_data_is_rejected(tmp_path):
    """A half-written map file must produce a clear error, not a corrupt
    image or a crash inside the encoder."""
    path = tmp_path / "short.pgm"
    path.write_bytes(b"P5\n10 10\n255\n" + bytes([254] * 20))
    with pytest.raises(PgmError, match="expected"):
        pgm_file_to_png(str(path))


def test_16_bit_pgm_is_rejected_clearly(tmp_path):
    path = tmp_path / "deep.pgm"
    path.write_bytes(b"P5\n2 2\n65535\n" + bytes(8))
    with pytest.raises(PgmError, match="8-bit"):
        pgm_file_to_png(str(path))


def test_mismatched_buffer_is_rejected():
    with pytest.raises(PgmError):
        encode_png(4, 4, bytes(3))


# ------------------------------------------------------------- the endpoint
def test_map_image_endpoint_serves_a_png(client, sample_map):
    response = client.get("/api/maps/%d/image" % sample_map["id"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == PNG_SIGNATURE
    width, height, _ = decode_png(response.content)
    assert (width, height) == (sample_map["width_px"], sample_map["height_px"])


def test_map_image_for_an_unknown_map_is_404(client):
    assert client.get("/api/maps/999/image").status_code == 404


def test_map_image_reports_a_missing_file_as_404(client, sample_map, db_session):
    import os
    from app.models.map import Map
    record = db_session.get(Map, sample_map["id"])
    os.remove(record.image_path)
    response = client.get("/api/maps/%d/image" % sample_map["id"])
    assert response.status_code == 404
    assert "missing" in response.json()["detail"]
