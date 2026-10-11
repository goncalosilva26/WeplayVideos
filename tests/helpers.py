"""Helpers to build in-memory asset records for planning/layout tests."""

from __future__ import annotations

from behance_studio.assets.roles import infer_roles
from behance_studio.projects.models import AssetRecord, new_id

_COLORS = {
    "logo": [{"hex": "#2E1F17", "weight": 0.8, "lab": [12, 6, 8], "chroma": 10}, {"hex": "#F4C95D", "weight": 0.2, "lab": [82, 5, 55], "chroma": 55}],
    "palette": [{"hex": "#2E1F17", "weight": 0.25, "lab": [12, 6, 8], "chroma": 10}, {"hex": "#F4C95D", "weight": 0.25, "lab": [82, 5, 55], "chroma": 55}, {"hex": "#D9663F", "weight": 0.25, "lab": [58, 42, 45], "chroma": 61}, {"hex": "#F7EFE3", "weight": 0.25, "lab": [95, 1, 7], "chroma": 7}],
}


def make_asset(kind: str, filename: str | None = None, width: int = 2000, height: int = 1500, **extra) -> AssetRecord:
    media = "video" if kind == "video" else "gif" if kind == "motion" else "image"
    analysis = {
        "colors": _COLORS.get(kind, [{"hex": "#8A6A50", "weight": 1.0, "lab": [47, 8, 18], "chroma": 20}]),
        "content_colors": _COLORS.get(kind, [{"hex": "#8A6A50", "weight": 1.0, "lab": [47, 8, 18], "chroma": 20}]),
        "brightness": 0.6,
        "sharpness": 900.0,
        "flat_ratio": 0.3 if kind in ("photo", "lifestyle", "product") else 0.8,
        "focal_point": [0.5, 0.45],
        "quietness": 0.5,
        "saliency_spread": 0.2,
        "luminance_grid": [[0.6] * 8 for _ in range(8)],
        "content_bbox": [0.1, 0.1, 0.9, 0.9],
        "background": "transparent" if kind in ("logo", "monogram", "logo_variant") else None,
    }
    analysis.update(extra.pop("analysis", {}))
    asset = AssetRecord(
        id=new_id(),
        media_type=media,
        filename=filename or f"{kind}-{new_id()[:4]}.jpg",
        rel_path=f"Assets/{filename or kind}.jpg",
        width=width,
        height=height,
        kind=kind,
        kind_confidence=0.9,
        has_alpha=kind in ("logo", "monogram", "logo_variant"),
        analysis=analysis,
        animated=kind in ("video", "motion"),
        duration=3.0 if kind == "video" else 0.0,
        phash=extra.pop("phash", new_id() + "0000"),
        **extra,
    )
    asset.roles = infer_roles(asset)
    return asset


def brand_kit() -> list[AssetRecord]:
    return [
        make_asset("logo", "logo-primary.png", 1800, 500),
        make_asset("logo_variant", "logo-stacked.png", 800, 1200),
        make_asset("monogram", "monogram.png", 1000, 1000),
        make_asset("palette", "colour-palette.png", 2400, 1350),
        make_asset("typography", "typography.png", 2400, 1500),
        make_asset("packaging", "bag.jpg", 2000, 2000),
        make_asset("packaging", "cups.jpg", 2200, 1650),
        make_asset("packaging", "box.jpg", 2200, 1650),
        make_asset("poster", "poster-1.jpg", 1414, 2000),
        make_asset("poster", "poster-2.jpg", 1414, 2000),
        make_asset("outdoor", "billboard.jpg", 3000, 1000),
        make_asset("social", "post-01.jpg", 1080, 1350),
        make_asset("social", "post-02.jpg", 1080, 1350),
        make_asset("social", "post-03.jpg", 1080, 1350),
        make_asset("social", "post-04.jpg", 1080, 1080),
        make_asset("photo", "DSC_0142.jpg", 2600, 1734),
        make_asset("lifestyle", "interior.jpg", 2800, 1866),
        make_asset("photo", "croissants.jpg", 1800, 2250),
        make_asset("photo", "beans.jpg", 2400, 1600),
    ]
