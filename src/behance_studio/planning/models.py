"""Narrative plan: which sections a presentation has and what each shows."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from behance_studio.projects.models import new_id


@dataclass
class SectionPlan:
    type: str
    title: str = ""
    subtitle: str = ""
    eyebrow: str = ""
    body: str = ""
    asset_ids: list[str] = field(default_factory=list)
    captions: dict[str, str] = field(default_factory=dict)  # asset id -> caption
    layout_hint: str | None = None
    background: str | None = None
    source: str = "auto"  # auto | script
    exact_text: bool = False  # title/subtitle/body are verbatim user text
    locked: bool = False  # content and position fixed by the script
    meta: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionPlan":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class PresentationPlan:
    sections: list[SectionPlan]
    language: str
    project_title: str
    category: str
    category_label: str
    hero_asset_id: str | None = None
    logo_asset_id: str | None = None
    unused_asset_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    script_driven: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresentationPlan":
        d = dict(data)
        d["sections"] = [SectionPlan.from_dict(s) for s in d.get("sections", [])]
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def used_asset_ids(self) -> list[str]:
        seen: list[str] = []
        for s in self.sections:
            for aid in s.asset_ids:
                if aid not in seen:
                    seen.append(aid)
        return seen
