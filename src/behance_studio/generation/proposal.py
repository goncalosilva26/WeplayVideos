"""A stored proposal: everything needed to reproduce, edit and export it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from behance_studio import __version__
from behance_studio.design.direction import CreativeDirection
from behance_studio.layout.engine import ProposalSpec
from behance_studio.layout.model import Presentation
from behance_studio.layout.validate import QualityReport
from behance_studio.planning.models import PresentationPlan
from behance_studio.projects.models import now_iso

PROPOSAL_FORMAT = 1


@dataclass
class ProposalData:
    spec: ProposalSpec
    plan: PresentationPlan
    direction: CreativeDirection
    presentation: Presentation
    quality: QualityReport
    notes: list[str] = field(default_factory=list)
    sources: dict[str, Any] = field(default_factory=dict)  # brief/script hashes, ai usage
    generated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": PROPOSAL_FORMAT,
            "app_version": __version__,
            "generated_at": self.generated_at,
            "spec": {
                "family": self.spec.family,
                "seed": self.spec.seed,
                "creativity": self.spec.creativity,
                "width": self.spec.width,
                "overrides": self.spec.overrides,
            },
            "plan": self.plan.to_dict(),
            "direction": self.direction.to_dict(),
            "presentation": self.presentation.to_dict(),
            "quality": self.quality.to_dict(),
            "notes": self.notes,
            "sources": self.sources,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProposalData":
        spec = data.get("spec", {})
        return cls(
            spec=ProposalSpec(
                family=spec.get("family", "editorial"),
                seed=int(spec.get("seed", 0)),
                creativity=float(spec.get("creativity", 0.5)),
                width=int(spec.get("width", 1400)),
                overrides=dict(spec.get("overrides") or {}),
            ),
            plan=PresentationPlan.from_dict(data["plan"]),
            direction=CreativeDirection.from_dict(data["direction"]),
            presentation=Presentation.from_dict(data["presentation"]),
            quality=QualityReport.from_dict(data.get("quality", {})),
            notes=list(data.get("notes", [])),
            sources=dict(data.get("sources", {})),
            generated_at=data.get("generated_at", now_iso()),
        )
