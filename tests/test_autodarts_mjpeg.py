"""Parse JPEG payloads out of Autodarts multipart MJPEG buffers."""

from __future__ import annotations

import numpy as np

from madu_darts.record.mjpeg import extract_jpeg_frames


def _minimal_jpeg() -> bytes:
    """Tiny valid-enough JPEG SOI…EOI blob (not decodable, fine for framing)."""
    return b"\xff\xd8" + b"\x00\x01\x02" + b"\xff\xd9"


def test_extract_jpeg_frames_finds_complete_images() -> None:
    first = _minimal_jpeg()
    second = b"\xff\xd8XXXX\xff\xd9"
    buf = b"--advisionmjpg\r\nContent-Type: image/jpeg\r\n\r\n" + first + b"\r\n--advisionmjpg\r\n" + second
    frames, rest = extract_jpeg_frames(buf)
    assert frames == [first, second]
    assert rest == b""


def test_extract_jpeg_frames_keeps_incomplete_tail() -> None:
    partial = b"\xff\xd8incomplete"
    frames, rest = extract_jpeg_frames(b"prefix" + partial)
    assert frames == []
    assert rest == partial


def test_extract_jpeg_frames_real_opencv_roundtrip() -> None:
    import cv2

    img = np.zeros((8, 12, 3), dtype=np.uint8)
    img[:] = (0, 128, 255)
    ok, encoded = cv2.imencode(".jpg", img)
    assert ok
    jpeg = encoded.tobytes()
    frames, rest = extract_jpeg_frames(b"hdr" + jpeg + b"trail\xff\xd8no")
    assert frames == [jpeg]
    assert rest.startswith(b"\xff\xd8")
