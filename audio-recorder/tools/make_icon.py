"""Regenerate recorder/app.ico: a red record dot in a white ring on a dark rounded square.

Pure Python (no Pillow). Run:  python tools/make_icon.py
"""

import math
import struct
import zlib
from pathlib import Path

SIZES = (16, 32, 48, 64, 128, 256)
BACKGROUND, WHITE, RED = (30, 41, 59), (255, 255, 255), (229, 57, 53)


def clamp(x):
    return max(0.0, min(1.0, x))


def blend(base, top, alpha):
    return tuple(b + (t - b) * alpha for b, t in zip(base, top))


def pixel(u, v, size):
    """RGBA of one pixel; u and v run from 0 to 1. Distances are scaled to pixels for soft edges."""
    qx, qy = abs(u - 0.5) - 0.3, abs(v - 0.5) - 0.3
    box = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - 0.2
    alpha = clamp(0.5 - box * size)
    r = math.hypot(u - 0.5, v - 0.5)
    color = blend(BACKGROUND, WHITE, clamp(0.5 - (abs(r - 0.31) - 0.02) * size))
    color = blend(color, RED, clamp(0.5 - (r - 0.21) * size))
    return (*(round(c) for c in color), round(alpha * 255))


def png(size):
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter type: none
        for x in range(size):
            row += bytes(pixel((x + 0.5) / size, (y + 0.5) / size, size))
        rows.append(bytes(row))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))


def ico():
    images = [png(s) for s in SIZES]
    offset = 6 + 16 * len(images)
    out = struct.pack("<HHH", 0, 1, len(images))
    for size, data in zip(SIZES, images):
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(images)


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "recorder" / "app.ico"
    target.write_bytes(ico())
    print(f"wrote {target} ({target.stat().st_size} bytes)")
