from behance_studio.brief.directives import build_directives
from behance_studio.design.category import infer_category
from behance_studio.design.direction import build_direction
from behance_studio.planning.planner import PlanningContext, PlanPreferences, plan_presentation
from helpers import brand_kit, make_asset
from test_brief_script import SCRIPT_EN

BRIEF = """Project: Butter & Bean
About: Butter & Bean is a neighbourhood specialty coffee shop and bakery.
Personality: warm, welcoming, slightly playful.
Brand messages: "Specialty Coffee. Freshly Baked." "Your New Favourite Corner."
Colours: Espresso #2E1F17, Butter #F4C95D, Cream #F7EFE3, Terracotta #D9663F
Typography: Fraunces for headings, Manrope for body copy.
"""


def _ctx(assets, brief="", script=""):
    d = build_directives("Butter & Bean", assets, brief_text=brief, script_text=script)
    direction = build_direction(d.brief, assets, d.category)
    return PlanningContext("Butter & Bean", assets, d, direction)


def test_category_inference():
    assert infer_category(brand_kit()).category == "brand_identity"
    photos = [make_asset("photo", f"p{i}.jpg") for i in range(8)]
    assert infer_category(photos).category == "photography"
    ui = [make_asset("website", f"w{i}.png", 1440, 4000) for i in range(3)] + [make_asset("mobile", f"m{i}.png", 1170, 2532) for i in range(5)]
    assert infer_category(ui).category in ("ui_ux", "app")
    social = [make_asset("social", f"s{i}.jpg", 1080, 1350) for i in range(9)]
    assert infer_category(social).category == "social_media"
    assert infer_category(photos, explicit_hint="Brand identity for a café").category == "brand_identity"


def test_auto_plan_brand_identity():
    ctx = _ctx(brand_kit(), BRIEF)
    plan = plan_presentation(ctx, PlanPreferences(merge_small=2), seed=1)
    types = [s.type for s in plan.sections]
    assert types[0] == "cover" and types[-1] == "closing"
    assert types[1] == "intro"
    for expected in ("logo", "palette", "typography", "packaging", "social"):
        assert expected in types
    intro = plan.sections[1]
    assert intro.body.startswith("Butter & Bean is a neighbourhood") and intro.exact_text
    cover = plan.sections[0]
    assert cover.subtitle == "Specialty Coffee. Freshly Baked."
    assert plan.hero_asset_id
    # every asset id referenced exists
    ids = {a.id for a in ctx.assets}
    assert all(aid in ids for s in plan.sections for aid in s.asset_ids)


def test_small_project_is_compact():
    assets = [
        make_asset("logo", "logo.png", 1600, 500),
        make_asset("packaging", "pack.jpg"),
        make_asset("poster", "poster.jpg", 1414, 2000),
        make_asset("social", "post.jpg", 1080, 1350),
        make_asset("photo", "shop.jpg", 2400, 1600),
    ]
    plan = plan_presentation(_ctx(assets), PlanPreferences(merge_small=2), seed=3)
    types = [s.type for s in plan.sections]
    assert len(types) <= 7, types
    assert "typography" not in types  # no fonts known, no type asset: no fabricated section
    assert all(s.asset_ids or s.type in ("cover", "intro", "closing", "palette") for s in plan.sections)


def test_large_collection_is_curated():
    assets = [make_asset("photo", f"IMG_{i:04d}.jpg", 3000, 2000) for i in range(120)]
    plan = plan_presentation(_ctx(assets), PlanPreferences(max_per_section=9), seed=2)
    used = plan.used_asset_ids()
    assert len(used) <= 30
    assert len(plan.unused_asset_ids) >= 90
    assert len(plan.sections) <= 8


def test_script_plan_is_exact_and_strict():
    assets = brand_kit()
    ctx = _ctx(assets, BRIEF, SCRIPT_EN)
    plan = plan_presentation(ctx, PlanPreferences(), seed=5)
    assert plan.script_driven
    assert [s.type for s in plan.sections] == ["cover", "intro", "logo", "campaign", "closing"]
    names = {a.id: a.filename for a in assets}
    assert [names[a] for a in plan.sections[0].asset_ids] == ["interior.jpg"]
    assert [names[a] for a in plan.sections[2].asset_ids] == ["logo-primary.png", "monogram.png"]
    assert plan.sections[2].captions[plan.sections[2].asset_ids[0]] == "Primary logo"
    assert plan.sections[1].body.startswith("Butter & Bean is your new favourite corner.")
    assert plan.sections[4].title == "Thank you!"
    assert all(s.locked and s.exact_text for s in plan.sections)
    excluded = next(a.id for a in assets if a.filename == "beans.jpg")
    assert excluded not in plan.used_asset_ids()
    # strict: unreferenced assets are not used
    assert len(plan.used_asset_ids()) == 6


def test_script_auto_sections_allowed():
    script = "AUTO_SECTIONS: yes\n" + SCRIPT_EN
    ctx = _ctx(brand_kit(), BRIEF, script)
    plan = plan_presentation(ctx, PlanPreferences(), seed=5)
    types = [s.type for s in plan.sections]
    assert types[:4] == ["cover", "intro", "logo", "campaign"] and types[-1] == "closing"
    assert len(types) > 5


def test_plans_vary_with_seed_but_are_reproducible():
    ctx = _ctx(brand_kit())
    a = plan_presentation(ctx, PlanPreferences(shuffle=1.0, hero_rank=0), seed=1)
    b = plan_presentation(ctx, PlanPreferences(shuffle=1.0, hero_rank=0), seed=1)
    assert [s.type for s in a.sections] == [s.type for s in b.sections]
    c = plan_presentation(ctx, PlanPreferences(shuffle=1.0, hero_rank=1), seed=2)
    assert a.hero_asset_id != c.hero_asset_id


def test_direction_palette_from_brief_and_assets():
    assets = brand_kit()
    d = build_directives("x", assets, brief_text=BRIEF)
    direction = build_direction(d.brief, assets, d.category)
    assert direction.palette.source == "brief"
    assert direction.palette.ink == "#2E1F17" and direction.palette.paper == "#F7EFE3"
    assert direction.type_system.display == "Fraunces" and direction.brand_fonts_known
    d2 = build_directives("x", assets)
    direction2 = build_direction(d2.brief, assets, d2.category)
    assert direction2.palette.source == "assets"
    assert not direction2.brand_fonts_known
