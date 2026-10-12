"""Behance Studio 2.0: Design Spec v2, concepts, director, asset nature, rendered QA."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from behance_studio.assets.analysis import text_regions
from behance_studio.assets.importer import import_paths
from behance_studio.assets.understanding import asset_nature, treatment
from behance_studio.brief.directives import build_directives
from behance_studio.core.qtsupport import ensure_gui_application
from behance_studio.design.direction import build_direction
from behance_studio.director.inventory import build_inventory
from behance_studio.layout.devices import device_size, screen_rect
from behance_studio.layout.engine import ProposalSpec, build_plan, compose
from behance_studio.layout.families import CONCEPT_FAMILIES
from behance_studio.layout.model import Block, Presentation, Section, TextStyle
from behance_studio.layout.spec import from_spec, schema, to_spec, validate_spec
from behance_studio.layout.validate import layout_distance, validate_presentation
from behance_studio.planning.planner import PlanningContext
from behance_studio.projects.store import Project
from behance_studio.qa.rendered import inspect_section
from behance_studio.render.html import RenderOptions, render_html
from test_brief_script import SCRIPT_EN


@pytest.fixture(scope="module")
def demo(tmp_path_factory, demo_assets_dir):
    ensure_gui_application()
    root = tmp_path_factory.mktemp("v2")
    project = Project.create(root, "Butter & Bean")
    import_paths(project, [demo_assets_dir], workers=4)
    return project, project.list_assets()


def _ctx(assets, brief="", script=""):
    d = build_directives("Butter & Bean", assets, brief_text=brief, script_text=script)
    direction = build_direction(d.brief, assets, d.category)
    return PlanningContext("Butter & Bean", assets, d, direction), direction


def _compose(assets, concept, seed=7, brief="", script="", overrides=None):
    ctx, direction = _ctx(assets, brief, script)
    spec = ProposalSpec(family=concept, seed=seed, overrides=overrides or {})
    plan = build_plan(ctx, spec)
    return plan, compose(plan, {a.id: a for a in assets}, direction, spec)


# ------------------------------------------------------------ design spec
def test_spec_round_trip_and_schema(demo):
    project, assets = demo
    _plan, pres = _compose(assets, "layered", brief=project.brief_text)
    data = to_spec(pres)
    assert data["spec_version"] == 2
    ids = {a.id for a in assets}
    assert validate_spec(data, asset_ids=ids) == []
    again = from_spec(data, asset_ids=ids)
    assert to_spec(again) == data
    doc = schema()
    assert doc["properties"]["sections"]["items"]["properties"]["blocks"]["items"]["properties"]["clip"]["enum"][:2] == ["circle", "oval"]


def test_spec_validation_rejects_bad_ai_output():
    good = {"width": 1400, "sections": [{"type": "custom", "height": 600, "background": "#FFFFFF", "blocks": [
        {"kind": "shape", "x": 0, "y": 0, "w": 100, "h": 100, "fill": "#123456", "id": "a"}]}]}
    assert validate_spec(good) == []
    bad = {"width": 1400, "sections": [{"type": "custom", "height": 600, "background": "not-a-colour", "blocks": [
        {"kind": "image", "x": 0, "y": 0, "w": 100, "h": 100, "asset_id": "nope", "id": "a"},
        {"kind": "sticker", "x": 0, "y": 0, "w": 100, "h": 100, "id": "a"},
        {"kind": "shape", "x": float("nan"), "y": 0, "w": 100, "h": 100, "rotate": 400, "clip": "star"},
        {"kind": "text", "x": 0, "y": 0, "w": 100, "h": 100, "text": "Hi"},
        {"kind": "shape", "x": 9000, "y": 0, "w": 100, "h": 100}]}]}
    messages = " | ".join(str(e) for e in validate_spec(bad, asset_ids={"real"}))
    for expected in ("must be one of", "finite", "≤ 180"):
        assert expected in messages
    schema_ok_but_semantic = {"width": 1400, "sections": [{"type": "custom", "height": 600, "background": "nope", "blocks": [
        {"kind": "image", "x": 0, "y": 0, "w": 100, "h": 100, "asset_id": "missing", "id": "a"},
        {"kind": "text", "x": 0, "y": 0, "w": 100, "h": 100, "text": "Hi", "style": {"family": "Comic", "size": 12}, "id": "a"},
        {"kind": "shape", "x": 9000, "y": 0, "w": 100, "h": 100}]}]}
    sem = " | ".join(str(e) for e in validate_spec(schema_ok_but_semantic, asset_ids={"real"}, fonts={"Inter"}))
    for expected in ("not a colour", "unknown asset", "duplicate layer id", "not available", "laid out into lines", "far outside"):
        assert expected in sem


def test_device_geometry_round_trip():
    for device, (sw, sh) in {"phone": (300, 650), "tablet": (800, 600), "browser": (1000, 620), "frame": (500, 707)}.items():
        w, h = device_size(device, sw, sh)
        s = screen_rect(device, w, h)
        assert math.isclose(s.w, sw, abs_tol=0.05) and math.isclose(s.h, sh, abs_tol=0.05)


def test_renderer_draws_v2_layers():
    blocks = [
        Block(kind="image", x=10, y=10, w=200, h=300, asset_id="a", rotate=-4, shadow="float", clip="arch", id="b1"),
        Block(kind="image", x=300, y=10, w=200, h=420, asset_id="a", device="phone", id="b2"),
        Block(kind="image", x=600, y=10, w=300, h=80, asset_id="a", tint="#FFFFFF", id="b3"),
        Block(kind="shape", x=0, y=0, w=1400, h=600, fill="#EEE", fill_asset="a", fill_size=200, opacity=0.2, id="b4"),
        Block(kind="image", x=900, y=10, w=300, h=200, asset_id="a", perspective=(8.0, -12.0), fade="bottom", blend="multiply", filter="muted", id="b5"),
    ]
    pres = Presentation("test", 1, 1400, [Section("custom", 600, "#FFFFFF", blocks)])
    html = render_html(pres, RenderOptions(mode="static", asset_url=lambda b: "file:///x.png"))
    for fragment in ("rotate(-4deg)", "border-radius:100px 100px 0 0", "bs-dev", "bs-screen", "mask:url('file:///x.png')",
                     "background-repeat:repeat", "rotateY(-12deg)", "mask-image:linear-gradient(to bottom", "mix-blend-mode:multiply", "saturate(.62)"):
        assert fragment in html, fragment


# ----------------------------------------------------------------- concepts
@pytest.mark.parametrize("concept", CONCEPT_FAMILIES)
def test_concept_is_complete_valid_and_varied(demo, concept):
    project, assets = demo
    plan, pres = _compose(assets, concept, brief=project.brief_text)
    report = validate_presentation(pres, {a.id: a for a in assets}, plan)
    assert report.passed, [i.message for i in report.errors]
    assert pres.sections[0].type == "cover" and pres.sections[-1].type == "closing"
    modules = [s.meta.get("module") for s in pres.sections]
    assert all(modules) and len(set(modules)) >= 7, modules
    assert all(a != b for a, b in zip(modules, modules[1:]) if a not in ("fullbleed",)), modules
    assert not any(s.meta.get("fallback") for s in pres.sections)
    # No catalogue headings: few title blocks relative to sections.
    titles = [b for s in pres.sections for b in s.blocks if b.kind == "text" and b.role == "title"]
    assert len(titles) <= len(pres.sections) // 2 + 2


@pytest.mark.parametrize("concept", CONCEPT_FAMILIES)
def test_concepts_never_crop_artwork_or_logos(demo, concept):
    project, assets = demo
    by_id = {a.id: a for a in assets}
    _plan, pres = _compose(assets, concept, seed=3, brief=project.brief_text)
    for s in pres.sections:
        for b in s.blocks:
            if b.kind in ("image", "video") and b.asset_id:
                t = treatment(by_id[b.asset_id])
                if not t.may_crop:
                    assert b.crop <= 0.015, (concept, by_id[b.asset_id].filename, b.crop)


def test_five_concepts_are_genuinely_different(demo):
    project, assets = demo
    pres = {c: _compose(assets, c, brief=project.brief_text)[1] for c in CONCEPT_FAMILIES}
    distances = {(a, b): layout_distance(pres[a], pres[b]) for a, b in itertools.combinations(CONCEPT_FAMILIES, 2)}
    assert min(distances.values()) > 0.25, sorted(distances.items(), key=lambda kv: kv[1])[:3]
    sequences = {c: tuple(s.meta.get("module") for s in p.sections) for c, p in pres.items()}
    assert len(set(sequences.values())) == 5
    covers = {sequences[c][0] for c in CONCEPT_FAMILIES}
    assert len(covers) >= 3, covers


def test_concepts_are_reproducible_and_regenerate_by_section(demo):
    project, assets = demo

    def geo(p):
        return [(s.meta.get("module"), round(s.height, 1), [(b.kind, round(b.x, 1), round(b.y, 1), round(b.w, 1), round(b.h, 1), b.asset_id) for b in s.blocks]) for s in p.sections]

    plan, a = _compose(assets, "photo", seed=11, brief=project.brief_text)
    _p, b = _compose(assets, "photo", seed=11, brief=project.brief_text)
    assert geo(a) == geo(b)
    target = next(sp for sp in plan.sections if len(sp.meta.get("alternatives", [])) > 1 and sp.type != "cover")
    _p2, changed = _compose(assets, "photo", seed=11, brief=project.brief_text, overrides={target.id: {"variant_seed": 101}})
    before = {s.plan_id: s.meta.get("module") for s in a.sections}
    after = {s.plan_id: s.meta.get("module") for s in changed.sections}
    assert before[target.id] != after[target.id]
    assert {k: v for k, v in before.items() if k != target.id} == {k: v for k, v in after.items() if k != target.id}


@pytest.mark.parametrize("concept", CONCEPT_FAMILIES)
def test_script_is_followed_exactly_by_every_concept(demo, concept):
    project, assets = demo
    plan, pres = _compose(assets, concept, script=SCRIPT_EN)
    report = validate_presentation(pres, {a.id: a for a in assets}, plan)
    assert not [i for i in report.issues if i.code.startswith("script_")], [i.message for i in report.issues if i.code.startswith("script_")]
    texts = " ".join(b.text for s in pres.sections for b in s.blocks if b.kind == "text")
    for sp in plan.sections:
        for text in (sp.title, sp.subtitle, sp.body):
            if text and sp.exact_text:
                assert text.strip() in texts or text.strip().upper() in texts.upper(), text


def test_user_text_edits_always_show(demo):
    project, assets = demo
    plan, _pres = _compose(assets, "bold", brief=project.brief_text)
    target = next(sp for sp in plan.sections if sp.meta.get("module") in ("duo", "fullbleed", "stage_pair"))
    _p, pres = _compose(assets, "bold", brief=project.brief_text, overrides={target.id: {"title": "Edited in the inspector"}})
    sec = next(s for s in pres.sections if s.plan_id == target.id)
    assert any(b.kind == "text" and b.text == "Edited in the inspector" for b in sec.blocks)


# ---------------------------------------------------------- understanding
def _text_image() -> Image.Image:
    img = Image.new("RGB", (900, 600), "#F4C95D")
    d = ImageDraw.Draw(img)
    from behance_studio.core.paths import FONTS_DIR

    font = ImageFont.truetype(str(FONTS_DIR / "Inter-VF.ttf"), 42)
    for i, line in enumerate(["Specialty coffee", "Freshly baked daily", "Open every morning 7am"]):
        d.text((60, 80 + i * 90), line, fill="#2E1F17", font=font)
    return img


def test_text_regions_find_typography_not_texture():
    img = _text_image()
    gray = np.asarray(img.convert("L"))
    boxes, area = text_regions(gray)
    assert len(boxes) >= 3 and area > 0.03
    rng = np.random.default_rng(1)
    texture = (rng.normal(128, 6, (600, 900)).clip(0, 255)).astype(np.uint8)
    boxes, area = text_regions(texture)
    assert len(boxes) == 0


def test_asset_nature_and_selection(demo):
    project, assets = demo
    by_name = {a.filename: a for a in assets}
    assert asset_nature(by_name["poster-specialty-coffee.jpg"]) == "artwork"
    assert asset_nature(by_name["instagram-post-02.jpg"]) == "artwork"
    assert asset_nature(by_name["billboard-48-sheet.jpg"]) == "artwork"
    assert asset_nature(by_name["DSC_0157 shop interior.jpg"]) == "photo"
    assert asset_nature(by_name["butter-bean-logo-primary.png"]) == "element"
    assert asset_nature(by_name["colour-palette.png"]) == "document"
    assert not treatment(by_name["poster-specialty-coffee.jpg"]).may_crop
    ctx, _direction = _ctx(assets, project.brief_text)
    inv = build_inventory(ctx)
    assert inv.logo is not None and inv.logo.filename == "butter-bean-logo-primary.png"
    assert by_name["DSC_0171.jpg"].id in inv.dropped  # soft, low-interest frame held back
    assert len(inv.marks) == 1  # PNG and SVG of the same mark collapse to one


# ---------------------------------------------------------------- rendered QA
def _section(blocks, bg="#FFFFFF", module="duo", height=400):
    s = Section("custom", height, bg, blocks)
    s.meta["module"] = module
    return s


def test_rendered_qa_flags_blank_media_whitespace_and_contrast():
    img_block = Block(kind="image", x=100, y=100, w=200, h=100, asset_id="a", id="img")
    region = np.full((200, 700, 3), 255, dtype=np.int16)  # scale 0.5: all white, media rendered flat
    issues = inspect_section(_section([img_block]), region, 0.5, "minimal")
    kinds = {i["kind"] for i in issues}
    assert "rendered_blank_media" in kinds and "rendered_whitespace" in kinds
    # Light text over a light photograph.
    text = Block(kind="text", x=0, y=0, w=400, h=100, text="Butter", lines=["Butter"], overlay=True,
                 style=TextStyle("Inter", 60, color="#FFFFFF"), id="t")
    photo = Block(kind="image", x=0, y=0, w=1400, h=400, asset_id="a", id="p")
    rng = np.random.default_rng(3)
    region = (rng.normal(225, 20, (200, 700, 3))).clip(0, 255).astype(np.int16)
    issues = inspect_section(_section([photo, text], bg="#000000", module="cover_hero"), region, 0.5, "photo")
    assert any(i["kind"] == "rendered_contrast" for i in issues)
    # A healthy, busy section passes.
    region = (rng.normal(110, 50, (200, 700, 3))).clip(0, 255).astype(np.int16)
    assert inspect_section(_section([photo], bg="#000000", module="fullbleed"), region, 0.5, "photo") == []
