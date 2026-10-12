"""Presentation generation entry points: plan → composed presentation."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from behance_studio.design.direction import CreativeDirection
from behance_studio.layout.composer import ComposeContext
from behance_studio.layout.families import get_family
from behance_studio.layout.model import Presentation
from behance_studio.planning.models import PresentationPlan
from behance_studio.planning.planner import PlanningContext, PlanPreferences, plan_presentation
from behance_studio.projects.models import AssetRecord


@dataclass
class ProposalSpec:
    family: str
    seed: int
    creativity: float = 0.5
    width: int = 1400
    overrides: dict[str, dict] = field(default_factory=dict)


def family_preferences(spec: ProposalSpec) -> PlanPreferences:
    family = get_family(spec.family)
    rng = random.Random(f"prefs:{spec.family}:{spec.seed}")
    prefs = family.preferences(rng, spec.creativity)
    # Successive seeds explore different hero images within the same family.
    prefs.hero_rank = (prefs.hero_rank + spec.seed // 7) % 3 if spec.seed >= 7 else prefs.hero_rank
    return prefs


def build_plan(ctx: PlanningContext, spec: ProposalSpec) -> PresentationPlan:
    family = get_family(spec.family)
    planner = getattr(family, "plan", None)
    if planner is not None:
        # 2.0 concepts are planned by the Creative Director.
        return planner(ctx, spec)
    return plan_presentation(ctx, family_preferences(spec), spec.seed)


def compose(plan: PresentationPlan, assets: dict[str, AssetRecord], direction: CreativeDirection, spec: ProposalSpec) -> Presentation:
    family = get_family(spec.family)
    ctx = ComposeContext(
        plan=plan,
        assets=assets,
        direction=direction,
        width=spec.width,
        seed=spec.seed,
        creativity=spec.creativity,
        overrides=spec.overrides,
    )
    return family.compose(ctx)
