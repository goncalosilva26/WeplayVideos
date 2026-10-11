import json

from behance_studio.brief.brief import parse_brief
from behance_studio.brief.directives import build_directives
from behance_studio.brief.script import apply_resolution, parse_script, resolve_references, script_template
from helpers import brand_kit, make_asset

SCRIPT_EN = """# PROJECT SCRIPT
PROJECT: Butter & Bean
LANGUAGE: en
EXCLUDE: beans.jpg

## Cover
TITLE: Butter & Bean
SUBTITLE: Specialty Coffee. Freshly Baked.
IMAGES: interior.jpg
LAYOUT: full-bleed

## Introduction
TEXT:
Butter & Bean is your new favourite corner.
Note: this sentence has a colon and must stay in the text.

Second paragraph, kept exactly.

## Brand Identity
IMAGES:
- logo-primary.png | Primary logo
- monogram.png | Monogram

## Campaign
TEXT: "Posters and outdoor."
IMAGES: poster-1.jpg, poster-2.jpg, billboard.jpg

## Thank You
TITLE: Thank you!
"""


def test_script_sections_order_and_exact_text():
    script = parse_script(SCRIPT_EN)
    assert [s.type for s in script.sections] == ["cover", "intro", "logo", "campaign", "closing"]
    assert script.project_name == "Butter & Bean"
    assert script.language == "en"
    intro = script.sections[1]
    assert intro.text == (
        "Butter & Bean is your new favourite corner.\n"
        "Note: this sentence has a colon and must stay in the text.\n\n"
        "Second paragraph, kept exactly."
    )
    assert script.sections[0].subtitle == "Specialty Coffee. Freshly Baked."
    assert script.sections[0].layout == "full-bleed"
    assert script.sections[3].text == "Posters and outdoor."
    assert script.sections[4].title == "Thank you!"
    logo = script.sections[2]
    assert [(i.ref, i.caption) for i in logo.images] == [("logo-primary.png", "Primary logo"), ("monogram.png", "Monogram")]
    assert [i.ref for i in script.sections[3].images] == ["poster-1.jpg", "poster-2.jpg", "billboard.jpg"]


def test_script_portuguese_keys_and_headings():
    text = """PROJETO: Pastelaria Aurora
IDIOMA: português
EXCLUIR: rascunho-*.jpg

SECÇÃO 1: Capa
TÍTULO: Aurora
SUBTÍTULO: Doces de sempre.

[Embalagem]
IMAGENS:
- caixa.jpg | Caixa de bolos
TEXTO: As embalagens.

== Encerramento ==
TÍTULO: Obrigado
"""
    script = parse_script(text)
    assert script.language == "pt"
    assert script.exclude == ["rascunho-*.jpg"]
    assert [s.type for s in script.sections] == ["cover", "packaging", "closing"]
    assert script.sections[0].title == "Aurora"
    assert script.sections[1].images[0].caption == "Caixa de bolos"
    assert script.sections[1].text == "As embalagens."


def test_reference_resolution_missing_ambiguous_excluded():
    assets = brand_kit()
    dup1 = make_asset("photo", "same.jpg")
    dup2 = make_asset("photo", "same.jpg")
    dup1.import_group, dup2.import_group = "A", "B"
    assets += [dup1, dup2]
    text = SCRIPT_EN + "\n## Extra\nIMAGES: interor.jpg, same.jpg, beans.jpg\n"
    script = resolve_references(parse_script(text), assets)
    by_name = {a.filename: a.id for a in assets}
    codes = [i.code for i in script.issues]
    assert "missing_ref" in codes
    missing = next(i for i in script.issues if i.code == "missing_ref")
    assert missing.ref == "interor.jpg" and "interior.jpg" in missing.suggestions
    assert "ambiguous_ref" in codes
    assert "ref_excluded" in codes
    assert by_name["beans.jpg"] in script.excluded_asset_ids
    extra = script.sections[-1]
    # Nothing was silently substituted.
    assert all(not img.asset_ids for img in extra.images)
    # Explicit user resolution
    apply_resolution(script, "interor.jpg", by_name["interior.jpg"])
    assert extra.images[0].asset_ids == [by_name["interior.jpg"]]
    assert not any(i.ref == "interor.jpg" for i in script.issues)


def test_script_json_format():
    data = {
        "project": "X",
        "language": "pt",
        "sections": [{"type": "cover", "title": "X"}, {"name": "Packaging", "images": [{"file": "a.jpg", "caption": "A"}]}],
    }
    script = parse_script(json.dumps(data))
    assert script.source_format == "json"
    assert [s.type for s in script.sections] == ["cover", "packaging"]
    assert script.sections[1].images[0].caption == "A"


def test_script_template_parses():
    for lang in ("en", "pt"):
        script = parse_script(script_template("Demo", lang))
        assert script.language == lang
        assert script.sections[0].type == "cover"
        assert script.sections[-1].type == "closing"


def test_brief_parsing_fields_colors_fonts_personality():
    brief = parse_brief(
        """Project: Lumen
About: Lumen is a jewellery studio.
Brand personality: elegant, refined, calm, not playful.
Colours: Ink #111111, Gold #C9A227, Ivory #F6F1E6
Typography: Headlines in Bodoni, body text in Helvetica.
Brand messages: "Light, made precious."
"""
    )
    assert brief.project == "Lumen"
    assert brief.about == "Lumen is a jewellery studio."
    assert [c.hex for c in brief.colors] == ["#111111", "#C9A227", "#F6F1E6"]
    assert brief.colors[1].name == "Gold"
    assert brief.display_font == "Playfair Display" and brief.text_font == "Inter"
    assert len(brief.font_notes) == 2  # both substituted
    assert brief.personality["refinement"] > 0.5
    assert brief.personality["energy"] < 0
    assert brief.messages == ["Light, made precious."]


def test_brief_portuguese():
    brief = parse_brief("Personalidade: quente, acolhedora, ligeiramente divertida.\nCores: terracota e creme\nIdioma: português")
    assert brief.language == "pt"
    assert brief.personality["warmth"] > 0.5
    assert 0 < brief.personality["energy"] < 0.8
    assert {c.name for c in brief.colors} == {"Terracota", "Creme"}


def test_precedence_script_over_brief():
    assets = brand_kit()
    brief = "Language: Portuguese\nPersonality: warm\nColours: #111111, #EEEEEE"
    d = build_directives("Demo", assets, brief_text=brief, script_text=SCRIPT_EN)
    assert d.language == "en" and d.provenance["language"] == "script"
    assert d.script_locked
    excluded = {a.filename for a in assets if a.id in d.excluded_asset_ids}
    assert excluded == {"beans.jpg"}
    # Brief still controls visual direction (colours) — tested in direction tests.
    assert d.brief.colors[0].hex == "#111111"


def test_language_defaults_to_english_without_instructions():
    d = build_directives("Demo", brand_kit(), brief_text="Mood: warm", script_text="")
    assert d.language == "en" and d.provenance["language"] == "default"


def test_language_detected_from_portuguese_script_text():
    script = "## Capa\nTÍTULO: A nossa marca\n## Sobre\nTEXTO: A marca nasceu em Lisboa e é feita para todos os dias."
    d = build_directives("Demo", brand_kit(), script_text=script)
    assert d.language == "pt"
