"""Splitting long presentations into pages or image segments safely.

Cut points are chosen in this order of preference:

1. section boundaries,
2. break points declared by the composition (between image rows, after
   headers),
3. horizontal gaps where no text block is crossed,
4. a hard cut (only when a single element is taller than a page).

Text is never cut while any alternative exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from behance_studio.layout.model import Presentation, Section


@dataclass
class Slice:
    section: Section
    y0: float  # in section coordinates
    y1: float
    scale: float = 1.0

    @property
    def height(self) -> float:
        return (self.y1 - self.y0) * self.scale


@dataclass
class Page:
    slices: list[Slice]
    width: float
    height: float  # page height in output CSS px (fixed for A4)
    background: str


def free_cuts(section: Section) -> list[float]:
    """Y positions where no text block (and preferably no image) is crossed."""
    text = [(b.y, b.bottom) for b in section.blocks if b.kind == "text"]
    media = [(b.y, b.bottom) for b in section.blocks if b.kind in ("image", "video")]
    candidates = sorted({round(y, 1) for b in section.blocks for y in (b.y - 1, b.bottom + 1)} | set(section.breaks))
    good = []
    for y in candidates:
        if not (0 < y < section.height):
            continue
        if any(a < y < b for a, b in text):
            continue
        penalty = sum(1 for a, b in media if a < y < b)
        good.append((y, penalty))
    return [y for y, p in good if p == 0] or [y for y, _ in good]


def _choose_cut(section: Section, start: float, limit: float, min_progress: float) -> float | None:
    breaks = [b for b in section.breaks if start + min_progress <= b <= limit]
    if breaks:
        return max(breaks)
    frees = [y for y in free_cuts(section) if start + min_progress <= y <= limit]
    if frees:
        return max(frees)
    return None


def paginate_fixed(presentation: Presentation, sections: list[Section], page_w: float, page_h: float, margin: float = 0.0, min_scale_ratio: float = 0.62) -> list[Page]:
    """Fixed-size pages (A4): sections scaled to the page width, stacked,
    split at safe points, or scaled down a little to avoid awkward splits."""
    content_w = page_w - 2 * margin
    content_h = page_h - 2 * margin
    s = content_w / presentation.width
    pages: list[Page] = []
    current: list[Slice] = []
    used = 0.0

    def flush() -> None:
        nonlocal current, used
        if current:
            pages.append(Page(current, page_w, page_h, current[-1].section.background))
        current, used = [], 0.0

    for section in sections:
        y = 0.0
        H = section.height
        while y < H - 0.5:
            remaining = content_h - used
            rest = (H - y) * s
            if rest <= remaining + 0.5:
                current.append(Slice(section, y, H, s))
                used += rest
                y = H
                continue
            # Small leftovers move to a new page rather than splitting.
            if used > 0 and remaining < content_h * 0.28:
                flush()
                continue
            cut = _choose_cut(section, y, y + remaining / s, min_progress=min(160.0, remaining / s * 0.5))
            if cut is not None and (cut - y) * s >= min(remaining * 0.3, 120):
                current.append(Slice(section, y, cut, s))
                y = cut
                flush()
                continue
            if used > 0:
                flush()
                continue
            # Empty page and nothing fits: scale the remainder down if acceptable.
            factor = content_h / rest
            if factor >= min_scale_ratio:
                current.append(Slice(section, y, H, s * factor))
                y = H
                flush()
                continue
            cut = _choose_cut(section, y, y + content_h / s, min_progress=40) or (y + content_h / s)
            current.append(Slice(section, y, cut, s))
            y = cut
            flush()
    flush()
    return pages


def vertical_ranges(presentation: Presentation, sections: list[Section], max_h: float) -> list[list[Slice]]:
    """Variable-height ranges (continuous PDF pages / image segments) of at
    most ``max_h`` CSS px, cut at section boundaries whenever possible."""
    ranges: list[list[Slice]] = []
    current: list[Slice] = []
    used = 0.0
    for section in sections:
        y = 0.0
        H = section.height
        while y < H - 0.5:
            rest = H - y
            if used + rest <= max_h + 0.5:
                current.append(Slice(section, y, H))
                used += rest
                y = H
                continue
            if current and rest <= max_h:
                ranges.append(current)
                current, used = [], 0.0
                continue
            cut = _choose_cut(section, y, y + (max_h - used), min_progress=min(200.0, (max_h - used) * 0.4))
            if cut is None or cut <= y:
                if current:
                    ranges.append(current)
                    current, used = [], 0.0
                    continue
                cut = _choose_cut(section, y, y + max_h, min_progress=40) or y + max_h
            current.append(Slice(section, y, cut))
            ranges.append(current)
            current, used = [], 0.0
            y = cut
    if current:
        ranges.append(current)
    return ranges


def section_ranges(sections: list[Section], max_h: float) -> list[list[Slice]]:
    """One range per section (tall sections split at safe points)."""
    out: list[list[Slice]] = []
    for section in sections:
        y = 0.0
        while y < section.height - 0.5:
            if section.height - y <= max_h:
                out.append([Slice(section, y, section.height)])
                break
            cut = _choose_cut(section, y, y + max_h, min_progress=200) or y + max_h
            out.append([Slice(section, y, cut)])
            y = cut
    return out
