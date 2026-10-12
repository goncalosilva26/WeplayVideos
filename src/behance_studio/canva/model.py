"""The scene: primitive, individually editable elements with absolute geometry.

Coordinates are CSS pixels of the design (1400 px wide by default). In the
continuous scene ``y`` runs from the top of the presentation; on a
:class:`ScenePage` it runs from the top of that page. Elements are listed
in stacking order (first = bottom).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Solid:
    color: str  # #RRGGBB
    alpha: float = 1.0


@dataclass
class Stop:
    pos: float  # 0..1
    color: str
    alpha: float = 1.0


@dataclass
class Gradient:
    kind: str  # linear | radial
    stops: list[Stop]
    angle: float = 180.0  # CSS angle (0 = to top, 90 = to right, 180 = to bottom)
    cx: float = 0.5  # radial centre (fraction of the box)
    cy: float = 0.5
    rx: float = 0.5  # radial extent (fraction of the box)
    ry: float = 0.5

    def color_at(self, t: float) -> tuple[str, float]:
        """Colour and alpha at position ``t`` (0..1) along the gradient."""
        from behance_studio.canva.css import lerp_color

        stops = self.stops
        if t <= stops[0].pos:
            return stops[0].color, stops[0].alpha
        for a, b in zip(stops, stops[1:]):
            if t <= b.pos:
                k = 0.0 if b.pos <= a.pos else (t - a.pos) / (b.pos - a.pos)
                return lerp_color(a.color, b.color, k), a.alpha + (b.alpha - a.alpha) * k
        return stops[-1].color, stops[-1].alpha


@dataclass
class Line:
    color: str
    width: float  # px
    alpha: float = 1.0


@dataclass
class Shadow:
    kind: str  # outer | glow
    dx: float = 0.0
    dy: float = 0.0
    blur: float = 0.0
    spread: float = 0.0
    color: str = "#000000"
    alpha: float = 0.3


@dataclass
class TextFrame:
    lines: list[str]  # exactly as laid out; "" = paragraph gap
    family: str
    size: float  # px
    weight: int
    italic: bool
    color: str
    alpha: float
    tracking: float  # em
    line_px: float
    gap_px: float  # height of a "" line
    align: str  # left | center | right
    stroke: str | None = None  # outlined type: stroke colour
    stroke_px: float = 0.0
    single_line: bool = False  # marquee: lines continue on one line
    # natural = paragraphs wrap at the box width (body copy, easy to edit);
    # otherwise the designed line breaks are kept and the box never wraps.
    natural: bool = False


@dataclass
class Picture:
    path: str  # prepared image file
    crop: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # left, top, right, bottom (fractions hidden)
    px_w: int = 0  # pixel size of the file
    px_h: int = 0
    asset_id: str | None = None
    baked: list[str] = field(default_factory=list)  # effects drawn into the pixels


@dataclass
class Element:
    kind: str  # rect | ellipse | text | image
    x: float
    y: float
    w: float
    h: float
    name: str = ""
    rotation: float = 0.0  # degrees clockwise
    opacity: float = 1.0
    fill: Solid | Gradient | None = None
    line: Line | None = None
    geometry: str = "rect"  # rect | roundRect | ellipse | round2SameRect
    radius: float = 0.0  # corner radius in px (roundRect / round2SameRect)
    shadow: Shadow | None = None
    text: TextFrame | None = None
    picture: Picture | None = None
    section: int = 0  # index of the presentation section
    block_id: str = ""
    role: str = ""  # background | media | mat | frame | text | shape | filler
    notes: list[str] = field(default_factory=list)  # approximations, for the report

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def bounds(self) -> tuple[float, float, float, float]:
        if not self.rotation:
            return self.x, self.y, self.x + self.w, self.y + self.h
        import math

        a = math.radians(self.rotation)
        cw, sw = abs(math.cos(a)), abs(math.sin(a))
        bw, bh = self.w * cw + self.h * sw, self.w * sw + self.h * cw
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        return cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2

    @property
    def splittable(self) -> bool:
        """Can be cut horizontally into two seamless parts (page breaks)."""
        if self.rotation or self.kind == "text" or self.shadow is not None:
            return False
        if self.kind == "ellipse" or self.geometry != "rect":
            return False
        if isinstance(self.fill, Gradient) and (self.fill.kind != "linear" or self.fill.angle % 90):
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class SceneSection:
    index: int
    id: str
    title: str
    type: str
    y: float
    height: float
    background: str


@dataclass
class Scene:
    width: int
    height: float
    title: str
    elements: list[Element]
    sections: list[SceneSection]
    fonts: dict[str, set[int]] = field(default_factory=dict)  # family -> weights used
    notes: list[str] = field(default_factory=list)


@dataclass
class ScenePage:
    index: int
    y0: float  # range of the continuous scene shown on this page
    y1: float
    elements: list[Element]
    filler: float = 0.0  # px of background added at the bottom (no content cut)
    sections: list[int] = field(default_factory=list)
    label: str = ""  # proposal shown on this page (combined designs)


@dataclass
class PagedScene:
    scene: Scene
    page_height: int
    pages: list[ScenePage]
    split_images: int = 0
    split_shapes: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        s = self.scene
        return {
            "format": "behance-studio-canva-scene",
            "version": 1,
            "title": s.title,
            "width": s.width,
            "page_height": self.page_height,
            "sections": [dataclasses.asdict(x) for x in s.sections],
            "pages": [{"index": p.index, "y0": p.y0, "y1": p.y1, "filler": p.filler, "sections": p.sections,
                       "elements": [e.to_dict() for e in p.elements]} for p in self.pages],
            "fonts": {k: sorted(v) for k, v in s.fonts.items()},
            "notes": list(dict.fromkeys(s.notes + self.notes)),
        }
