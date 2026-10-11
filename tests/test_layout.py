import itertools

import pytest

from behance_studio.assets.importer import import_paths
from behance_studio.brief.directives import build_directives
from behance_studio.core.qtsupport import ensure_gui_application
from behance_studio.design.direction import build_direction
from behance_studio.layout.engine import ProposalSpec, build_plan, compose
from behance_studio.layout.families import available_families
from behance_studio.layout.validate import layout_distance, signature, signature_distance, validate_presentation
from behance_studio.planning.planner import PlanningContext
from behance_studio.projects.store import Project
from helpers import make_asset

FAMILIES = ["editorial", "cinematic", "split", "posters", "gallery", "modular"]


@pytest.fixture(scope="module")
def demo(tmp_path_factory, demo_assets_dir):
    ensure_gui_application()
    root = tmp_path_factory.mktemp("layout")
    project = Project.create(root, "Butter & Bean")
    import_paths(project, [demo_assets_dir], workers=4)
    assets = project.list_assets()
    return project, assets


def _ctx(assets, brief="", script=""):
    d = build_directives("Butter & Bean", assets, brief_text=brief, script_text=script)
    direction = build_direction(d.brief, assets, d.category)
    return PlanningContext("Butter & Bean", assets, d, direction), direction


def _compose(assets, family, seed=1, brief="", script="", overrides=None):
    ctx, direction = _ctx(assets, brief, script)
    spec = ProposalSpec(family=family, seed=seed, overrides=overrides or {})
    plan = build_plan(ctx, spec)
    pres = compose(plan, {a.id: a for a in assets}, direction, spec)
    return plan, pres


def _geometry(pres):
    return [
        (s.type, round(s.height, 1), [(b.kind, round(b.x, 1), round(b.y, 1), round(b.w, 1), round(b.h, 1), b.asset_id, tuple(b.lines)) for b in s.blocks])
        for s in pres.sections
    ]


def test_six_families_registered():
    assert available_families() == FAMILIES


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_family_composes_complete_valid_presentation(demo, family, seed):
    project, assets = demo
    plan, pres = _compose(assets, family, seed, brief=project.brief_text)
    report = validate_presentation(pres, {a.id: a for a in assets}, plan)
    assert report.passed, [i.message for i in report.errors]
    types = [s.type for s in pres.sections]
    assert types[0] == "cover" and types[-1] == "closing"
    assert len([t for t in types if t not in ("divider",)]) >= 6
    assert not any(s.meta.get("fallback") for s in pres.sections), "no section should need the safe fallback"
    for s in pres.sections:
        assert s.height > 0
        for b in s.blocks:
            if b.kind in ("image", "video"):
                assert b.fit in ("cover", "contain")  # never stretched
    assert report.scores["completeness"] == 1.0


def test_families_are_structurally_different(demo):
    project, assets = demo
    sigs = {}
    presentations = {}
    for family in FAMILIES:
        _plan, pres = _compose(assets, family, 1, brief=project.brief_text)
        sigs[family] = signature(pres)
        presentations[family] = pres
    distances = {}
    for a, b in itertools.combinations(FAMILIES, 2):
        assert signature_distance(sigs[a], sigs[b]) > 0.3, (a, b, sigs[a], sigs[b])
        distances[(a, b)] = layout_distance(presentations[a], presentations[b])
    # Same material: compositions must differ beyond colour (a recolouring of
    # one layout scores at most 0.2 by construction of the metric).
    assert min(distances.values()) > 0.25, sorted(distances.items(), key=lambda kv: kv[1])[:3]
    # Within a family, two seeds are related but not identical.
    _p, other_seed = _compose(assets, "editorial", 2, brief=project.brief_text)
    assert 0.0 < layout_distance(presentations["editorial"], other_seed)


def test_same_seed_is_reproducible_and_seeds_vary(demo):
    project, assets = demo
    _p1, a = _compose(assets, "editorial", 4, brief=project.brief_text)
    _p2, b = _compose(assets, "editorial", 4, brief=project.brief_text)
    assert _geometry(a) == _geometry(b)
    variants = {str(_compose(assets, "editorial", s, brief=project.brief_text)[1].variant) for s in range(1, 7)}
    assert len(variants) >= 3


def test_regenerating_one_section_keeps_the_others(demo):
    project, assets = demo
    plan, base = _compose(assets, "posters", 2, brief=project.brief_text)
    target = next(sp for sp in plan.sections if sp.type == "social")
    _plan2, changed = _compose(assets, "posters", 2, brief=project.brief_text, overrides={target.id: {"variant_seed": 7}})
    base_geo = {s.plan_id: s for s in base.sections}
    for s in changed.sections:
        if s.plan_id == target.id or s.type == "divider":
            continue
        assert _geometry_section(s) == _geometry_section(base_geo[s.plan_id])


def _geometry_section(s):
    return [(b.kind, round(b.x, 1), round(b.y, 1), round(b.w, 1), round(b.h, 1), b.asset_id) for b in s.blocks]


def test_overrides_title_hidden_background(demo):
    project, assets = demo
    plan, _ = _compose(assets, "editorial", 1)
    packaging = next(sp for sp in plan.sections if sp.type == "packaging")
    intro = next(sp for sp in plan.sections if sp.type == "intro")
    overrides = {packaging.id: {"title": "Embalagens novas", "background": "#202020"}, intro.id: {"hidden": True}}
    _, pres = _compose(assets, "editorial", 1, overrides=overrides)
    sec = next(s for s in pres.sections if s.plan_id == packaging.id)
    assert any(b.text == "Embalagens novas" for b in sec.blocks if b.kind == "text")
    assert sec.background == "#202020"
    assert all(s.plan_id != intro.id for s in pres.sections)


def test_few_assets_compact_presentation(demo):
    _, assets = demo
    by_name = {a.filename: a for a in assets}
    few = [by_name[n] for n in ("butter-bean-logo-primary.png", "coffee-bag-mockup.jpg", "poster-specialty-coffee.jpg", "instagram-post-01.jpg", "DSC_0142.jpg")]
    for family in FAMILIES:
        plan, pres = _compose(few, family, 1)
        report = validate_presentation(pres, {a.id: a for a in few}, plan)
        assert report.passed, (family, [i.message for i in report.errors])
        content = [s for s in pres.sections if s.type != "divider"]
        assert len(content) <= 7, (family, [s.type for s in content])


def test_large_collection(demo):
    photos = [make_asset("photo", f"IMG_{i:04d}.jpg", 3000 if i % 3 else 2000, 2000 if i % 3 else 3000) for i in range(80)]
    for family in FAMILIES:
        plan, pres = _compose(photos, family, 3)
        report = validate_presentation(pres, {a.id: a for a in photos}, plan)
        assert report.passed, (family, [i.message for i in report.errors][:3])
        assert pres.height < 60000


SCRIPT = """PROJECT: Butter & Bean
LANGUAGE: en

## Cover
TITLE: Butter & Bean
SUBTITLE: Specialty Coffee. Freshly Baked.
IMAGES: DSC_0157 shop interior.jpg

## Introduction
TEXT:
Butter & Bean is a neighbourhood café.
Every word here must survive exactly.

## Brand Identity
IMAGES:
- butter-bean-logo-primary.png | Primary logo
- butter-bean-monogram.png | Monogram

## Campaign
TITLE: Advertising that feels like a warm welcome
IMAGES: poster-specialty-coffee.jpg, poster-favourite-corner.jpg

## Thank You
TITLE: Obrigado & thank you
"""


@pytest.mark.parametrize("family", FAMILIES)
def test_script_compliance_in_every_family(demo, family):
    _, assets = demo
    plan, pres = _compose(assets, family, 5, script=SCRIPT)
    report = validate_presentation(pres, {a.id: a for a in assets}, plan)
    assert report.passed, [i.message for i in report.errors]
    assert report.scores["compliance"] == 1.0
    content = [s for s in pres.sections if s.type != "divider"]
    assert [s.type for s in content] == ["cover", "intro", "logo", "campaign", "closing"]
    names = {a.id: a.filename for a in assets}
    logo_sec = content[2]
    assert [names[a] for a in logo_sec.asset_ids()][:2] == ["butter-bean-logo-primary.png", "butter-bean-monogram.png"] or set(names[a] for a in logo_sec.asset_ids()) == {"butter-bean-logo-primary.png", "butter-bean-monogram.png"}
    texts = [b.text for s in content for b in s.blocks if b.kind == "text"] + [b.meta.get("source_text", "") for s in content for b in s.blocks]
    assert "Butter & Bean is a neighbourhood café.\nEvery word here must survive exactly." in texts
    assert "Advertising that feels like a warm welcome" in texts
    used = {names[a] for s in content for a in s.asset_ids()}
    assert used <= {"DSC_0157 shop interior.jpg", "butter-bean-logo-primary.png", "butter-bean-monogram.png", "poster-specialty-coffee.jpg", "poster-favourite-corner.jpg"}
