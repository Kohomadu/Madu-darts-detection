"""Minimal MJPEG framing helpers (Autodarts ``/api/streams/live``)."""

from __future__ import annotations

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


def extract_jpeg_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Pull complete JPEG payloads from ``buffer``; return (frames, remainder).

    Autodarts uses ``multipart/x-mixed-replace; boundary=advisionmjpg``. We ignore
    MIME headers and key off JPEG SOI/EOI markers so framing stays robust.
    """
    frames: list[bytes] = []
    pos = 0
    while True:
        start = buffer.find(SOI, pos)
        if start < 0:
            return frames, b""
        end = buffer.find(EOI, start + 2)
        if end < 0:
            return frames, buffer[start:]
        frames.append(buffer[start : end + 2])
        pos = end + 2
