"""CSS colours and gradients used by the Design Spec, as scene values."""

from __future__ import annotations

import re

from behance_studio.canva.model import Gradient, Solid, Stop
from behance_studio.design.color import parse_color, parse_hex, to_hex

_RGBA = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+%?)\s*)?\)", re.I)


def parse_rgba(value: str | None) -> tuple[str, float] | None:
    """``#hex``, ``#RRGGBBAA``, ``rgb()``, ``rgba()``, ``transparent`` or a colour name → (hex, alpha)."""
    if not value:
        return None
    v = value.strip()
    if v.lower() == "transparent":
        return "#000000", 0.0
    m = _RGBA.fullmatch(v)
    if m:
        r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        a = m.group(4)
        alpha = 1.0 if a is None else (float(a[:-1]) / 100 if a.endswith("%") else float(a))
        return to_hex((r, g, b)), max(0.0, min(1.0, alpha))
    h = v.lstrip("#")
    if v.startswith("#") and re.fullmatch(r"[0-9a-fA-F]{8}", h):
        return to_hex(parse_hex(h[:6])), int(h[6:], 16) / 255  # type: ignore[arg-type]
    c = parse_color(v)
    return (c, 1.0) if c else None


def lerp_color(a: str, b: str, t: float) -> str:
    ra, rb = parse_hex(a) or (0, 0, 0), parse_hex(b) or (0, 0, 0)
    return to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def _split_args(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


_DIRECTIONS = {"to top": 0.0, "to right": 90.0, "to bottom": 180.0, "to left": 270.0,
               "to top right": 45.0, "to right top": 45.0, "to bottom right": 135.0, "to right bottom": 135.0,
               "to bottom left": 225.0, "to left bottom": 225.0, "to top left": 315.0, "to left top": 315.0}


def _stops(parts: list[str]) -> list[Stop] | None:
    raw: list[tuple[str, float, float | None]] = []
    for part in parts:
        m = re.match(r"^(.*?)(?:\s+(-?[\d.]+)%)?$", part.strip())
        if not m:
            return None
        color = parse_rgba(m.group(1).strip())
        if color is None:
            return None
        raw.append((color[0], color[1], float(m.group(2)) / 100 if m.group(2) else None))
    if len(raw) < 2:
        return None
    positions = [p for _, _, p in raw]
    if positions[0] is None:
        positions[0] = 0.0
    if positions[-1] is None:
        positions[-1] = 1.0
    # Missing positions are spread evenly between their neighbours (CSS rule).
    i = 0
    while i < len(positions):
        if positions[i] is None:
            j = i
            while positions[j] is None:
                j += 1
            a, b = positions[i - 1], positions[j]
            for k in range(i, j):
                positions[k] = a + (b - a) * (k - i + 1) / (j - i + 1)  # type: ignore[operator]
            i = j
        i += 1
    out, last = [], 0.0
    for (c, a, _), p in zip(raw, positions):
        last = max(last, float(p))  # type: ignore[arg-type]
        out.append(Stop(max(0.0, min(1.0, last)), c, a))
    return out


def parse_gradient(value: str | None) -> Gradient | None:
    if not value:
        return None
    v = value.strip()
    m = re.fullmatch(r"(linear|radial)-gradient\((.*)\)", v, re.S | re.I)
    if not m:
        return None
    kind, args = m.group(1).lower(), _split_args(m.group(2))
    if not args:
        return None
    if kind == "linear":
        head = args[0].lower()
        angle = 180.0
        if head in _DIRECTIONS:
            angle, args = _DIRECTIONS[head], args[1:]
        elif re.fullmatch(r"-?[\d.]+deg", head):
            angle, args = float(head[:-3]) % 360, args[1:]
        stops = _stops(args)
        return Gradient("linear", stops, angle=angle) if stops else None
    head = args[0].lower()
    g = Gradient("radial", [], cx=0.5, cy=0.5, rx=0.5, ry=0.5)
    if "at " in head or head.startswith(("ellipse", "circle")):
        shape = re.match(r"^(ellipse|circle)?\s*(?:([\d.]+)%\s+([\d.]+)%)?\s*(?:at\s+([\d.]+)%\s+([\d.]+)%)?$", head)
        if not shape:
            return None
        if shape.group(2):
            g.rx, g.ry = float(shape.group(2)) / 100, float(shape.group(3)) / 100
        else:  # farthest-corner: half-diagonal, as a fraction of each side
            g.rx = g.ry = 0.7071
        if shape.group(4):
            g.cx, g.cy = float(shape.group(4)) / 100, float(shape.group(5)) / 100
        args = args[1:]
    stops = _stops(args)
    if not stops:
        return None
    g.stops = stops
    return g


def parse_fill(value: str | None) -> Solid | Gradient | None:
    if not value:
        return None
    if "gradient(" in value:
        return parse_gradient(value)
    c = parse_rgba(value)
    return Solid(c[0], c[1]) if c else None


def solid_color(value: str | None, default: str = "#FFFFFF") -> str:
    """A representative solid colour for any fill (gradients: their last stop)."""
    fill = parse_fill(value)
    if isinstance(fill, Solid):
        return fill.color
    if fill is not None:
        return fill.stops[-1].color
    return default
