"""Design-purpose recognition with a vision model (local or cloud).

The model looks at a small preview and answers, as a design studio would,
*what the image is for*: a logo, packaging, a social post, a poster, a
photograph… plus how it is presented (finished flat artwork, a design shown
in a photographed scene, a plain photograph, an isolated brand element, a
document sheet or a screen).

Answers are never trusted blindly. :func:`implausible` compares each answer
with facts the app measured itself (transparency, colour count, flatness,
media type) and rejects contradictions — e.g. a "photograph" with a
transparent background, or a "logo" that is a full-colour photo. Rejected
answers are kept for transparency (``analysis["ai"]["rejected"]``) but do not
change the asset's type, so a wrong label cannot move an image into the
wrong section.
"""

from __future__ import annotations

import re
from typing import Any

from behance_studio.projects.models import ASSET_KINDS

PROMPT_VERSION = 3

# Kinds the model may choose ("reference" is only set by the user or folder).
AI_KINDS = {k: v for k, v in ASSET_KINDS.items() if k != "reference"}

PURPOSE_HINTS = {
    "logo": "the brand's logo or wordmark on its own (plain or transparent background)",
    "logo_variant": "another version of the logo: stacked, negative, single-colour, reduced",
    "monogram": "a symbol, icon, emblem or monogram on its own",
    "palette": "a sheet presenting the brand colours (swatches, colour codes)",
    "typography": "a sheet presenting typefaces, letters or a type specimen",
    "pattern": "a repeating pattern, texture or graphic element on its own",
    "illustration": "an illustration or drawing as artwork",
    "packaging": "packaging: box, bag, cup, label, bottle, can, sleeve — flat design or photographed",
    "poster": "a poster or flyer design",
    "outdoor": "out-of-home advertising: billboard, bus shelter, street banner, storefront signage",
    "social": "a social-media post, story or ad (square or vertical graphic, Instagram-style)",
    "stationery": "business cards, letterhead, envelopes, menus, notebooks, tickets",
    "editorial": "magazine, book, brochure or catalogue pages and spreads",
    "mockup": "the design applied to another object (apparel, tote, mug, vehicle, device) in a scene",
    "website": "a website or landing page screen",
    "mobile": "a mobile app screen",
    "ui": "a user-interface screen, dashboard or component sheet",
    "photo": "a photograph of a place, food or objects with no design applied",
    "product": "a product photograph (packshot) of the brand's product",
    "lifestyle": "a photograph of people or atmosphere (shop interior, customers, staff)",
    "portrait": "a portrait photograph of a person",
    "before_after": "a before/after comparison",
    "video": "a frame from a video",
    "motion": "a frame from an animation",
    "document": "a text document or presentation page",
    "other": "none of the above",
}
PRESENTATIONS = {
    "flat_artwork": "a finished design file shown flat (not photographed)",
    "photographed_scene": "a design shown on a real or rendered object or place",
    "photograph": "a photograph with no design applied",
    "brand_element": "an isolated logo, symbol or pattern",
    "document_sheet": "a guideline page: colour sheet, type sheet, specification",
    "screen": "a screenshot of a website or app",
}
PRESENTATION_NATURE = {"flat_artwork": "artwork", "photographed_scene": "photo", "photograph": "photo",
                       "brand_element": "element", "document_sheet": "document", "screen": "screen"}

SYSTEM = (
    "You are a senior designer sorting the files of a brand-design project before building its Behance case study. "
    "Look at the image and decide what it is FOR in the project — its design purpose — not what it depicts. "
    "A coffee cup with the brand's label is packaging; a photo of the shop without visible design is a photograph; "
    "a square graphic with a headline is a social post. Judge from the image first; the file name is only a hint "
    "and may be wrong. Never invent brand facts. Answer with JSON only."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(AI_KINDS)},
        "presentation": {"type": "string", "enum": list(PRESENTATIONS)},
        "shows_logo": {"type": "boolean"},
        "text_visible": {"type": "boolean"},
        "confidence": {"type": "number"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "presentation", "shows_logo", "text_visible", "confidence", "description", "tags"],
    "additionalProperties": False,
}


def prompt(filename: str, folder: str, include_names: bool = True) -> str:
    kinds = "\n".join(f"- {k}: {PURPOSE_HINTS.get(k, v)}" for k, v in AI_KINDS.items())
    shows = "\n".join(f"- {k}: {v}" for k, v in PRESENTATIONS.items())
    names = (f"File name: {filename}\nFolder (the designer's own organisation): {folder or '-'}\n" if include_names
             else "File name: (hidden)\n")
    return (
        f"{names}"
        f"Allowed kinds (design purpose):\n{kinds}\n"
        f"Presentation:\n{shows}\n"
        'Return {"kind": "<one allowed kind>", "presentation": "<one presentation>", "shows_logo": true|false, '
        '"text_visible": true|false, "confidence": <0..1>, "description": "<max 12 words, what is visible>", '
        '"tags": ["<up to 5 lowercase words>"]}'
    )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().strip('"').strip()


def normalise(data: dict[str, Any]) -> dict[str, Any] | None:
    """Turn a model answer into a clean result, or None when unusable."""
    kind = str(data.get("kind", "")).strip().lower().replace(" ", "_").replace("-", "_")
    if kind not in AI_KINDS:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if 1.0 < confidence <= 100.0:  # some models answer on a 0–100 scale
        confidence /= 100.0
    confidence = max(0.0, min(1.0, confidence))
    presentation = str(data.get("presentation", "")).strip().lower()
    return {
        "kind": kind,
        "presentation": presentation if presentation in PRESENTATIONS else None,
        "shows_logo": bool(data.get("shows_logo")) if "shows_logo" in data else None,
        "text_visible": bool(data.get("text_visible")) if "text_visible" in data else None,
        "confidence": round(confidence, 3),
        "description": _clean(str(data.get("description", "")))[:120],
        "tags": [_clean(str(t)).lower()[:24] for t in (data.get("tags") or [])[:5] if str(t).strip()],
    }


PHOTO_KINDS = {"photo", "product", "lifestyle", "portrait"}
ELEMENT_KINDS = {"logo", "logo_variant", "monogram"}
SHEET_KINDS = {"palette", "typography"}


def implausible(result: dict[str, Any], asset) -> str:
    """Why the answer contradicts measured facts ("" when it is plausible)."""
    kind = result["kind"]
    a = asset.analysis or {}
    moving = asset.media_type == "video" or bool(getattr(asset, "animated", False))
    if kind in ("video", "motion") and not moving:
        return "a still image cannot be a video or animation"
    if asset.media_type == "video" and kind not in ("video", "motion"):
        return "the file is a video"
    transparent = a.get("background") == "transparent"
    colours = int(a.get("n90_colors", 0) or 0)
    flat = float(a.get("flat_ratio", 0.0) or 0.0)
    uniform = float(a.get("background_uniformity", 0.0) or 0.0)
    if kind in PHOTO_KINDS and transparent:
        return "a photograph has no transparent background"
    if kind in PHOTO_KINDS and result.get("presentation") in ("brand_element", "document_sheet", "screen"):
        return "the answer contradicts itself (photograph vs. graphic)"
    if kind in ELEMENT_KINDS and not transparent and colours > 200 and flat < 0.3 and uniform < 0.5:
        return "a full-colour photographic image is not an isolated logo or symbol"
    if kind in SHEET_KINDS and colours > 220 and flat < 0.25:
        return "a colour or type sheet is a flat graphic, not a photograph"
    return ""


def nature_from_ai(asset) -> str | None:
    """The presentation the model saw, as an asset nature (None when unknown)."""
    ai = (asset.analysis or {}).get("ai") or {}
    if ai.get("rejected") or float(ai.get("confidence", 0) or 0) < 0.6:
        return None
    if ai.get("kind") and ai.get("kind") != asset.effective_kind:
        return None  # the user (or the heuristics) decided otherwise
    return PRESENTATION_NATURE.get(ai.get("presentation") or "")
