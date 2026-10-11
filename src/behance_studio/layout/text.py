"""Text measurement and line breaking with the bundled fonts.

Lines are broken here (not by the browser) and rendered verbatim with
``white-space: pre``. The composition therefore never reflows between the
preview, PDF and image exports, and text heights are exact. A small width
safety margin absorbs metric differences between FreeType and Chromium; the
browser-based quality check verifies there is no horizontal overflow.
"""

from __future__ import annotations

import math
import re
import threading
from functools import lru_cache

from PIL import ImageFont, features

from behance_studio.design.typography import get_font
from behance_studio.layout.model import TextStyle

SAFETY = 0.965  # use 96.5% of the available width when breaking lines

_local = threading.local()
_LAYOUT = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC


def _font_cache() -> dict:
    cache = getattr(_local, "fonts", None)
    if cache is None:
        cache = {}
        _local.fonts = cache
    return cache


def load_font(family: str, weight: int, size: float, italic: bool = False, stretch: int = 100) -> ImageFont.FreeTypeFont:
    """FreeType font configured like the CSS renderer (weight, opsz, width),
    loaded at 4x the CSS size for sub-pixel measurement precision."""
    return font_at(family, weight, max(1, int(round(size * 4))), size, italic, stretch)


def font_at(family: str, weight: int, px: int, css_size: float, italic: bool = False, stretch: int = 100) -> ImageFont.FreeTypeFont:
    """FreeType font at ``px`` pixels whose optical size matches ``css_size``."""
    fam = get_font(family)
    weight = fam.clamp_weight(weight)
    px = max(1, int(px))
    size = css_size
    key = (fam.name, weight, px, italic, stretch, round(css_size, 1))
    cache = _font_cache()
    font = cache.get(key)
    if font is not None:
        return font
    font = ImageFont.truetype(str(fam.path(italic)), px, layout_engine=_LAYOUT)
    try:
        axes = font.get_variation_axes()
    except Exception:  # noqa: BLE001 - static font
        axes = []
    if axes:
        values = []
        for axis in axes:
            name = axis["name"] if isinstance(axis["name"], str) else axis["name"].decode()
            name = name.lower()
            lo, hi, default = axis["minimum"], axis["maximum"], axis["default"]
            if "weight" in name:
                values.append(max(lo, min(hi, weight)))
            elif "optical" in name:
                values.append(max(lo, min(hi, size)))
            elif "width" in name:
                values.append(max(lo, min(hi, stretch)))
            elif "wonky" in name:
                values.append(default)
            else:
                values.append(default)
        try:
            font.set_variation_by_axes(values)
        except Exception:  # noqa: BLE001
            pass
    if len(cache) > 400:
        cache.clear()
    cache[key] = font
    return font


def transform(text: str, style: TextStyle) -> str:
    return text.upper() if style.uppercase else text


def line_width(text: str, style: TextStyle) -> float:
    if not text:
        return 0.0
    font = load_font(style.family, style.weight, style.size, style.italic, style.stretch)
    width = font.getlength(text) / 4.0
    width += style.tracking * style.size * len(text)
    return width


def _break_word(word: str, style: TextStyle, max_width: float) -> list[str]:
    parts: list[str] = []
    current = ""
    for ch in word:
        if current and line_width(current + ch, style) > max_width:
            parts.append(current)
            current = ch
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def wrap(text: str, style: TextStyle, max_width: float) -> list[str]:
    """Break text into lines. Explicit newlines are kept; a blank line
    (paragraph break) becomes an empty string entry."""
    limit = max_width * SAFETY
    text = transform(text, style)
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = re.split(r"(\s+)", paragraph.strip())
        current = ""
        for token in words:
            if not token:
                continue
            if token.isspace():
                if current:
                    current += " "
                continue
            candidate = current + token
            if not current or line_width(candidate.rstrip(), style) <= limit:
                if line_width(token, style) > limit and not current.strip():
                    pieces = _break_word(token, style, limit)
                    lines.extend(pieces[:-1])
                    current = pieces[-1]
                else:
                    current = candidate
            else:
                lines.append(current.rstrip())
                if line_width(token, style) > limit:
                    pieces = _break_word(token, style, limit)
                    lines.extend(pieces[:-1])
                    current = pieces[-1]
                else:
                    current = token
        if current.strip():
            lines.append(current.rstrip())
    # collapse runs of blank lines and trim edges
    out: list[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


def balance(lines_text: str, style: TextStyle, max_width: float) -> list[str]:
    """Like wrap, but evens out line lengths (nicer headlines)."""
    lines = wrap(lines_text, style, max_width)
    if len(lines) < 2 or "" in lines or "\n" in lines_text:
        return lines
    words = [w for w in re.split(r"\s+", transform(lines_text, style)) if w]
    longest = max((line_width(w, style) for w in words), default=0.0)
    lo, hi = max(max_width * 0.45, longest / SAFETY + 1.0), max_width
    if lo >= hi:
        return lines
    best = lines
    for _ in range(12):
        mid = (lo + hi) / 2
        candidate = wrap(lines_text, style, mid)
        if len(candidate) <= len(lines):
            best, hi = candidate, mid
        else:
            lo = mid
    return best


def text_height(lines: list[str], style: TextStyle, para_gap: float = 0.5) -> float:
    """Height of laid-out lines. Blank lines count as ``para_gap`` lines."""
    total = 0.0
    for line in lines:
        total += style.line_px * (para_gap if line == "" else 1.0)
    return round(total, 2)


def widest(lines: list[str], style: TextStyle) -> float:
    return max((line_width(line, style) for line in lines), default=0.0)


def fit_size(text: str, style: TextStyle, max_width: float, max_lines: int, min_size: float, max_size: float, max_height: float | None = None) -> float:
    """Largest font size (≤ max_size) so the text fits in max_lines (and height)."""
    lo, hi = min_size, max_size
    best = min_size
    words = [w for w in re.split(r"\s+", transform(text, style)) if w]
    longest = max(words, key=lambda w: len(w)) if words else ""
    for _ in range(14):
        mid = (lo + hi) / 2
        st = style.with_(size=mid)
        lines = wrap(text, st, max_width)
        ok = len([l for l in lines if l]) <= max_lines
        if ok and max_height is not None:
            ok = text_height(lines, st) <= max_height
        if ok and widest(lines, st) > max_width * SAFETY + 0.5:
            ok = False
        if ok and longest and max(line_width(w, st) for w in words) > max_width * SAFETY:
            ok = False  # a word would have to be broken
        if ok:
            best, lo = mid, mid
        else:
            hi = mid
    return math.floor(best * 10) / 10  # never round up past the verified size


def fit_line_to_width(text: str, style: TextStyle, width: float, max_size: float = 900.0) -> float:
    """Font size at which a single line spans ``width`` exactly (display type)."""
    probe = style.with_(size=100.0)
    w = line_width(transform(text, probe), probe)
    if w <= 0:
        return style.size
    # tracking scales with size, so the relation is linear
    size = 100.0 * (width * SAFETY) / w
    return math.floor(min(max_size, size) * 10) / 10


@lru_cache(maxsize=64)
def cap_height_ratio(family: str) -> float:
    """Approximate cap-height / font-size, used for optical alignment."""
    font = load_font(family, 400, 100)
    bbox = font.getbbox("H")
    return (bbox[3] - bbox[1]) / 400.0
