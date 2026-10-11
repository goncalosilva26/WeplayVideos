"""Image fitting rules: when an asset may be cropped, and how.

Artwork integrity comes first: logos, posters, social posts, interfaces,
palettes and typography are never cropped into (they are *contained*, on a
mat if needed). Photographs may be cropped moderately around their focal
point. Any image may be cropped when only its plain background is removed
(the measured content bounding box stays fully visible).
"""

from __future__ import annotations

from dataclasses import dataclass

from behance_studio.projects.models import AssetRecord

MAX_CROP: dict[str, float] = {
    "photo": 0.40, "lifestyle": 0.40, "portrait": 0.32, "product": 0.28, "mockup": 0.24,
    "packaging": 0.20, "stationery": 0.15, "video": 0.25, "pattern": 0.65, "before_after": 0.0,
    "illustration": 0.0, "logo": 0.0, "logo_variant": 0.0, "monogram": 0.0, "palette": 0.0,
    "typography": 0.0, "poster": 0.0, "social": 0.0, "outdoor": 0.0, "website": 0.0,
    "mobile": 0.0, "ui": 0.0, "editorial": 0.04, "motion": 0.0, "other": 0.08,
}

# Long web pages may be shown from the top ("above the fold"), a standard
# presentation practice; only vertical cropping from the top anchor.
TOP_ANCHORED_CROP = {"website": 0.75}


def crop_fraction(image_aspect: float, frame_aspect: float) -> float:
    if image_aspect <= 0 or frame_aspect <= 0:
        return 1.0
    return 1.0 - min(image_aspect / frame_aspect, frame_aspect / image_aspect)


@dataclass
class Fit:
    mode: str  # cover | contain
    position: tuple[float, float]  # CSS object-position %
    crop: float
    visible: tuple[float, float, float, float]  # normalised visible region of the image


def cover_region(image_aspect: float, frame_aspect: float, focal: tuple[float, float], top_anchor: bool = False) -> tuple[tuple[float, float], tuple[float, float, float, float]]:
    """Object-position (%) centring the focal point, and the visible region."""
    fx, fy = focal
    if image_aspect > frame_aspect:  # wider: crop left/right
        v = frame_aspect / image_aspect
        x0 = min(max(fx - v / 2, 0.0), 1.0 - v)
        px = x0 / (1.0 - v) * 100 if v < 1 else 50.0
        return (round(px, 2), 50.0), (x0, 0.0, x0 + v, 1.0)
    v = image_aspect / frame_aspect  # taller: crop top/bottom
    if top_anchor:
        return (50.0, 0.0), (0.0, 0.0, 1.0, v)
    y0 = min(max(fy - v / 2, 0.0), 1.0 - v)
    py = y0 / (1.0 - v) * 100 if v < 1 else 50.0
    return (50.0, round(py, 2)), (0.0, y0, 1.0, y0 + v)


def _content_safe(asset: AssetRecord, visible: tuple[float, float, float, float]) -> bool:
    a = asset.analysis or {}
    bbox = a.get("content_bbox")
    plain_bg = a.get("background") == "transparent" or (a.get("background") and a.get("background_uniformity", 0) >= 0.85)
    if not bbox or not plain_bg:
        return False
    tol = 0.01
    return (
        visible[0] <= bbox[0] + tol
        and visible[1] <= bbox[1] + tol
        and visible[2] >= bbox[2] - tol
        and visible[3] >= bbox[3] - tol
    )


def max_crop(asset: AssetRecord) -> float:
    return MAX_CROP.get(asset.effective_kind, 0.08)


def choose_fit(asset: AssetRecord, frame_w: float, frame_h: float, prefer: str = "cover", tolerance: float = 0.012) -> Fit:
    """Decide cover/contain for an asset in a frame, respecting integrity."""
    image_aspect = asset.aspect
    frame_aspect = frame_w / frame_h if frame_h > 0 else 1.0
    crop = crop_fraction(image_aspect, frame_aspect)
    focal_raw = (asset.analysis or {}).get("focal_point") or [0.5, 0.5]
    focal = (float(focal_raw[0]), float(focal_raw[1]))
    if crop <= tolerance:
        # Practically identical proportions: cover hides at most a hairline.
        position, visible = cover_region(image_aspect, frame_aspect, (0.5, 0.5))
        return Fit("cover", position, crop, visible)
    if prefer == "contain":
        return Fit("contain", (50.0, 50.0), 0.0, (0, 0, 1, 1))
    kind = asset.effective_kind
    top_anchor = kind in TOP_ANCHORED_CROP and image_aspect < frame_aspect
    limit = TOP_ANCHORED_CROP[kind] if top_anchor else max_crop(asset)
    position, visible = cover_region(image_aspect, frame_aspect, focal, top_anchor=top_anchor)
    if crop <= limit or _content_safe(asset, visible):
        return Fit("cover", position, crop, visible)
    return Fit("contain", (50.0, 50.0), 0.0, (0, 0, 1, 1))


def can_cover(asset: AssetRecord, frame_aspect: float) -> bool:
    return choose_fit(asset, frame_aspect * 1000, 1000).mode == "cover"


def best_crop_aspect(asset: AssetRecord, candidates: list[float]) -> float | None:
    """First candidate aspect the asset may be cover-cropped to."""
    for aspect in candidates:
        if can_cover(asset, aspect):
            return aspect
    return None


def native_limit(asset: AssetRecord, upscale: float = 1.15) -> float:
    """Largest displayed width (px at 1x) before visible upscaling."""
    if asset.media_type == "svg":
        return 1e9
    return asset.width * upscale
