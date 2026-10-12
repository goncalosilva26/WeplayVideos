"""Device and frame geometry for presenting artwork in context.

Frames are drawn with CSS (no bitmap mockups), so the original artwork is
shown pixel-exact inside them: a phone for social posts and mobile screens,
a browser window for websites, a tablet, or a picture frame for posters.

Geometry is shared by the composition engine (to fit media to the *screen*)
and the renderer (to draw the frame), so both always agree.
"""

from __future__ import annotations

from dataclasses import dataclass

DEVICES = ("phone", "tablet", "browser", "frame")


@dataclass(frozen=True)
class Screen:
    x: float  # offset of the screen inside the device box
    y: float
    w: float
    h: float
    radius: float  # screen corner radius
    outer_radius: float  # device corner radius


def screen_rect(device: str, w: float, h: float) -> Screen:
    """The media area inside a device box of size w × h."""
    if device == "phone":
        bezel = round(w * 0.045, 2)
        return Screen(bezel, bezel, w - 2 * bezel, h - 2 * bezel, round(w * 0.11, 2), round(w * 0.15, 2))
    if device == "tablet":
        bezel = round(min(w, h) * 0.04, 2)
        return Screen(bezel, bezel, w - 2 * bezel, h - 2 * bezel, round(min(w, h) * 0.02, 2), round(min(w, h) * 0.055, 2))
    if device == "browser":
        bar = browser_bar(w)
        return Screen(0.0, bar, w, h - bar, 0.0, round(max(8.0, w * 0.01), 2))
    if device == "frame":
        border = frame_border(w, h)
        return Screen(border, border, w - 2 * border, h - 2 * border, 0.0, 0.0)
    return Screen(0.0, 0.0, w, h, 0.0, 0.0)


def browser_bar(w: float) -> float:
    return round(max(22.0, w * 0.034), 2)


def frame_border(w: float, h: float) -> float:
    return round(max(6.0, min(w, h) * 0.028), 2)


def device_size(device: str, screen_w: float, screen_h: float) -> tuple[float, float]:
    """Outer device size for a desired screen size."""
    if device == "phone":
        # screen = w * (1 - 0.09)  →  w = screen_w / 0.91
        w = screen_w / 0.91
        return round(w, 2), round(screen_h + 0.09 * w, 2)
    if device == "tablet":
        # bezel = 0.04 · min(W, H) with W = sw + 2·bezel  →  bezel = 0.04·m / 0.92
        bezel = 0.04 * min(screen_w, screen_h) / 0.92
        return round(screen_w + 2 * bezel, 2), round(screen_h + 2 * bezel, 2)
    if device == "browser":
        return round(screen_w, 2), round(screen_h + browser_bar(screen_w), 2)
    if device == "frame":
        border = max(6.0, 0.028 * min(screen_w, screen_h) / 0.944)
        return round(screen_w + 2 * border, 2), round(screen_h + 2 * border, 2)
    return screen_w, screen_h


def media_rect(block) -> tuple[float, float, float, float]:
    """Absolute (x, y, w, h) of the media area of a block (screen for devices)."""
    if not getattr(block, "device", None):
        return block.x, block.y, block.w, block.h
    s = screen_rect(block.device, block.w, block.h)
    return block.x + s.x, block.y + s.y, s.w, s.h
