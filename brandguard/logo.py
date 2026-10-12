"""Logo / avatar / app-icon similarity using perceptual hashes (dHash + aHash).

Cheap, offline, and robust to resizing, recompression and mild colour changes.
Verdicts: 'match' (very likely a copy), 'near' (similar, review), 'none'.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


def _load(src) -> Image.Image:
    if isinstance(src, Image.Image):
        return src
    if isinstance(src, (bytes, bytearray)):
        return Image.open(io.BytesIO(src))
    return Image.open(Path(src))


def _gray(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        img = bg
    return img.convert("L")


def _dhash(g: Image.Image, size: int = 8) -> int:
    px = list(g.resize((size + 1, size), Image.LANCZOS).tobytes())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | (1 if px[r * (size + 1) + c] > px[r * (size + 1) + c + 1] else 0)
    return bits


def _ahash(g: Image.Image, size: int = 8) -> int:
    px = list(g.resize((size, size), Image.LANCZOS).tobytes())
    avg = sum(px) / len(px)
    bits = 0
    for p in px:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


def hash_image(src) -> tuple[int, int] | None:
    """Return (dhash, ahash) or None when the image is missing / unreadable."""
    try:
        g = _gray(_load(src))
        return _dhash(g), _ahash(g)
    except Exception:
        return None


def _ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


@dataclass
class LogoMatch:
    verdict: str = "none"        # match | near | none
    similarity: float = 0.0      # 0..1
    d_dist: int = 64
    a_dist: int = 64


def compare(h1: tuple[int, int] | None, h2: tuple[int, int] | None) -> LogoMatch:
    if not h1 or not h2:
        return LogoMatch()
    dd, ad = _ham(h1[0], h2[0]), _ham(h1[1], h2[1])
    sim = 1 - (dd + ad) / 128
    if dd <= 10 and ad <= 12:
        verdict = "match"
    elif dd <= 20 and ad <= 18:
        verdict = "near"
    else:
        verdict = "none"
    return LogoMatch(verdict, round(sim, 3), dd, ad)
