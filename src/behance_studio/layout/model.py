"""Geometric presentation model.

A presentation is a vertical stack of sections; each section has an exact
height and absolutely positioned blocks (images, video, text, shapes). All
geometry is computed in Python at the design width, so previews, PDF and
image exports render the *same* composition, and layout quality can be
validated deterministically without a browser.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from behance_studio.projects.models import new_id


@dataclass
class TextStyle:
    family: str
    size: float
    weight: int = 400
    line_height: float = 1.3  # multiple of size
    tracking: float = 0.0  # em
    color: str = "#111111"
    italic: bool = False
    uppercase: bool = False
    stretch: int = 100  # font-stretch % (variable width axis)
    stroke: str | None = None  # outlined type: stroke colour (fill transparent)
    opacity: float = 1.0

    @property
    def line_px(self) -> float:
        return round(self.size * self.line_height, 2)

    def with_(self, **changes: Any) -> "TextStyle":
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextStyle":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Block:
    kind: str  # image | video | text | shape
    x: float
    y: float
    w: float
    h: float
    z: int = 1
    id: str = field(default_factory=lambda: new_id()[:8])
    # media
    asset_id: str | None = None
    fit: str = "cover"  # cover | contain
    focal: tuple[float, float] = (50.0, 50.0)  # object-position in %
    pad: float = 0.0  # inner padding (contain on a mat)
    mat: str | None = None  # background behind a contained image
    radius: float = 0.0
    crop: float = 0.0  # fraction of the image hidden by cover fitting
    edge: str | None = None  # None | outline | soft — separation from a similar background
    edge_color: str | None = None
    # text
    text: str = ""  # exact source text (before typographic case transforms)
    lines: list[str] = field(default_factory=list)
    style: TextStyle | None = None
    align: str = "left"
    role: str = ""  # display | title | subtitle | eyebrow | body | caption | label | numeral | quote | marquee
    para_gap: float = 0.0  # extra height of blank lines (paragraph breaks)
    # shape
    fill: str | None = None  # colour or CSS gradient
    shape: str = "rect"  # rect | circle | line | ring
    stroke: str | None = None
    stroke_width: float = 0.0
    opacity: float = 1.0
    # semantics
    overlay: bool = False  # deliberately placed over an image (contrast-checked)
    decorative: bool = False  # may overlap other blocks (background graphics)
    editable: str | None = None  # plan field this text comes from: title | subtitle | body | eyebrow | caption:<asset>
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["focal"] = list(self.focal)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Block":
        names = {f.name for f in dataclasses.fields(cls)}
        d = {k: v for k, v in data.items() if k in names}
        if d.get("style"):
            d["style"] = TextStyle.from_dict(d["style"])
        if "focal" in d:
            d["focal"] = tuple(d["focal"])
        return cls(**d)


@dataclass
class Section:
    type: str
    height: float
    background: str
    blocks: list[Block] = field(default_factory=list)
    plan_id: str = ""
    title: str = ""
    theme: str = "light"  # light | dark (text colour family)
    pattern: str = ""  # composition pattern id (for rhythm and diversity checks)
    breaks: list[float] = field(default_factory=list)  # y positions safe for page splits
    gradient: str | None = None  # optional CSS background gradient
    id: str = field(default_factory=lambda: new_id()[:10])
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["blocks"] = [b.to_dict() for b in self.blocks]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Section":
        names = {f.name for f in dataclasses.fields(cls)}
        d = {k: v for k, v in data.items() if k in names}
        d["blocks"] = [Block.from_dict(b) for b in d.get("blocks", [])]
        return cls(**d)

    def asset_ids(self) -> list[str]:
        return [b.asset_id for b in self.blocks if b.asset_id]


@dataclass
class Presentation:
    family: str
    seed: int
    width: int
    sections: list[Section]
    title: str = ""
    language: str = "en"
    page_background: str = "#FFFFFF"
    fonts: list[str] = field(default_factory=list)
    variant: dict[str, Any] = field(default_factory=dict)  # stored art-direction parameters
    id: str = field(default_factory=new_id)

    @property
    def height(self) -> float:
        return sum(s.height for s in self.sections)

    def section_offsets(self) -> list[float]:
        y, out = 0.0, []
        for s in self.sections:
            out.append(y)
            y += s.height
        return out

    def asset_ids(self) -> list[str]:
        out: list[str] = []
        for s in self.sections:
            for aid in s.asset_ids():
                if aid not in out:
                    out.append(aid)
        return out

    def all_text(self) -> list[tuple[str, str, str]]:
        """(section title, role, text) for every text block in order."""
        rows = []
        for s in self.sections:
            for b in s.blocks:
                if b.kind == "text" and b.text.strip() and b.role not in ("marquee",):
                    rows.append((s.title, b.role, b.text))
        return rows

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["sections"] = [s.to_dict() for s in self.sections]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Presentation":
        names = {f.name for f in dataclasses.fields(cls)}
        d = {k: v for k, v in data.items() if k in names}
        d["sections"] = [Section.from_dict(s) for s in d.get("sections", [])]
        return cls(**d)
