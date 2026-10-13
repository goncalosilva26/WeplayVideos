"""What an asset *is* for presentation purposes, and how it may be treated.

Asset kinds (logo, poster, photo…) say what an image shows. Presentation
needs a second, coarser answer — its **nature** — because that decides how a
designer may handle it:

* ``element``  – reusable brand element (logo, logo variant, symbol, pattern).
  Never cropped (except patterns); may sit on brand colours; strictly
  single-colour marks may be shown reversed.
* ``artwork``  – a finished composition (poster, social post, billboard
  artwork, flat packaging/stationery design). Never cropped; staged,
  framed or placed in a device.
* ``document`` – a brand-guideline page (palette sheet, type specimen).
  Shown whole; the engine can also present the same information natively.
* ``screen``   – website / app / interface capture: shown in a device frame.
* ``photo``    – photography and photographic mockups/scenes: may run
  full-bleed and be cropped within limits, never through detected text.
* ``motion``   – video and animation.

The decision combines the asset kind with measured features (flat colour
areas, detected lines of typography, plain backgrounds). With a configured
multimodal provider the kind itself comes from genuine visual analysis;
without one it is a documented heuristic, and the UI says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from behance_studio.assets.roles import quality_score
from behance_studio.projects.models import AssetRecord

NATURES = ("element", "artwork", "document", "screen", "photo", "motion")

NATURE_BY_KIND = {
    "logo": "element", "logo_variant": "element", "monogram": "element", "pattern": "element",
    "palette": "document", "typography": "document",
    "poster": "artwork", "social": "artwork", "editorial": "artwork", "illustration": "artwork",
    "website": "screen", "mobile": "screen", "ui": "screen",
    "photo": "photo", "lifestyle": "photo", "portrait": "photo", "before_after": "photo",
    "video": "motion", "motion": "motion",
}
# Kinds that may be either a flat design file or a photographed scene.
AMBIGUOUS_KINDS = {"packaging", "outdoor", "stationery", "mockup", "product", "other"}


def asset_nature(asset: AssetRecord) -> str:
    kind = asset.effective_kind
    if asset.media_type == "video" or (asset.animated and kind in ("motion", "video")):
        return "motion"
    if kind in NATURE_BY_KIND:
        return NATURE_BY_KIND[kind]
    # Packaging, outdoor, stationery, mockups… can be a flat design file or a
    # photographed scene. A vision model that looked at it decides first.
    from behance_studio.ai.vision import nature_from_ai

    seen = nature_from_ai(asset)
    if seen in ("artwork", "photo", "document", "screen"):
        return seen
    a = asset.analysis or {}
    flat = a.get("flat_ratio", 0.5)
    text = a.get("text_fraction", 0.0)
    plain = a.get("background_uniformity", 0.0)
    # A flat design with real typography and no photographic ground reads as
    # finished artwork (e.g. a billboard design); otherwise it is a scene.
    if flat >= 0.6 and text >= 0.04 and plain < 0.8:
        return "artwork"
    if flat >= 0.9 and plain >= 0.97 and text >= 0.02:
        return "artwork"
    return "photo"


def is_single_colour_mark(asset: AssetRecord) -> bool:
    """A transparent mark drawn in one colour (safe to show reversed)."""
    a = asset.analysis or {}
    if a.get("background") != "transparent":
        return False
    colours = a.get("content_colors") or []
    return bool(colours) and colours[0].get("weight", 0) >= 0.985


def logo_ink(asset: AssetRecord) -> str:
    colours = (asset.analysis or {}).get("content_colors") or (asset.analysis or {}).get("colors") or []
    return colours[0]["hex"] if colours else "#000000"


@dataclass
class Treatment:
    nature: str
    may_crop: bool  # cover-cropping within the kind's limit is acceptable
    may_bleed: bool  # may run edge to edge
    stage: bool  # should be presented on a surface (mat/stage) rather than cropped
    device: str | None  # preferred frame
    reversible: bool  # single-colour mark: may be tinted to a brand colour


def treatment(asset: AssetRecord) -> Treatment:
    nature = asset_nature(asset)
    kind = asset.effective_kind
    device = None
    if nature == "screen":
        device = "phone" if kind == "mobile" or asset.aspect < 0.75 else "browser"
    elif kind == "social" and asset.aspect < 0.7:
        device = "phone"
    return Treatment(
        nature=nature,
        may_crop=nature in ("photo", "motion") or kind == "pattern",
        may_bleed=nature in ("photo", "motion") or kind == "pattern",
        stage=nature in ("artwork", "document", "element", "screen"),
        device=device,
        reversible=nature == "element" and is_single_colour_mark(asset),
    )


def strength(asset: AssetRecord) -> float:
    """How strong an asset is as presentation material (0–1+).

    Combines measured image quality (resolution, sharpness) with its
    suitability as a hero and a penalty for very small files.
    """
    q = quality_score(asset)
    hero = (asset.roles or {}).get("hero", 0.0)
    long_edge = max(asset.width, asset.height)
    size = 1.0 if long_edge >= 1600 else 0.8 if long_edge >= 1000 else 0.55 if long_edge >= 600 else 0.3
    score = 0.55 * q + 0.25 * hero + 0.2 * size
    # Visual interest: an almost edgeless, monotone frame (blur, plain
    # texture) is weak material for a case study however large it is.
    a = asset.analysis or {}
    if asset_nature(asset) == "photo" and a.get("edge_density", 1.0) < 0.005 and a.get("colorfulness", 100) < 30:
        score *= 0.72
    # The vision model judged the image as a case-study opener (composition,
    # appeal, brand presence): it weighs in on which images lead and which are
    # held back, alongside the measured quality.
    from behance_studio.ai.vision import cover_score

    judged = cover_score(asset)
    if judged is not None:
        score = 0.6 * score + 0.4 * judged
    return round(score, 4)
