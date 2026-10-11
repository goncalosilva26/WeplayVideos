"""Asset role inference and grouping.

Roles are *suitability scores* (0..1), never exclusive assignments: the
planner and layout families can use any asset in any role, these scores only
guide their choices.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

from behance_studio.assets.analysis import hamming
from behance_studio.assets.classify import tokenize
from behance_studio.projects.models import (
    LOGO_KINDS,
    MOTION_KINDS,
    PHOTO_KINDS,
    UI_KINDS,
    AssetRecord,
)

ROLES = (
    "hero",
    "full_width",
    "pair",
    "grid",
    "identity",
    "typography",
    "product",
    "mockup",
    "campaign",
    "closing",
    "text_overlay",
)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def resolution_score(asset: AssetRecord, target_width: int = 1400) -> float:
    if asset.media_type == "svg":
        return 1.0
    return _clamp(asset.width / target_width)


def quality_score(asset: AssetRecord) -> float:
    """Technical quality estimate: resolution and sharpness."""
    a = asset.analysis or {}
    sharp = a.get("sharpness", 300.0)
    sharp_score = _clamp(math.log10(max(sharp, 1.0)) / 3.0)  # 1000 → 1.0
    flat = a.get("flat_ratio", 0)
    if flat > 0.6:  # flat graphics are inherently "soft" on the Laplacian
        sharp_score = max(sharp_score, 0.8)
    megapixels = asset.width * asset.height / 1e6 if asset.media_type != "svg" else 4.0
    mp_score = _clamp(math.log2(max(megapixels, 0.05) * 4) / 4.5)
    return round(0.55 * mp_score + 0.45 * sharp_score, 3)


def infer_roles(asset: AssetRecord) -> dict[str, float]:
    kind = asset.effective_kind
    a = asset.analysis or {}
    aspect = asset.aspect
    res = resolution_score(asset)
    quality = quality_score(asset)
    photo_like = kind in PHOTO_KINDS or kind in {"mockup", "packaging", "lifestyle", "product"}
    landscape = aspect >= 1.2
    wide = aspect >= 1.6
    quiet = a.get("quietness", 0.0)
    focused = 1.0 - _clamp(a.get("saliency_spread", 0.3) / 0.45)

    roles: dict[str, float] = {}
    hero = 0.0
    if photo_like or kind in {"poster", "outdoor", "illustration", "video"}:
        hero = 0.35 + 0.25 * res + 0.2 * quality + (0.15 if landscape else 0) + 0.1 * focused
        if kind in {"lifestyle", "mockup", "packaging", "product", "video"}:
            hero += 0.08
        if kind in {"poster", "social"}:
            hero -= 0.15
    roles["hero"] = _clamp(hero)
    roles["full_width"] = _clamp((0.4 if wide else 0.2 if landscape else 0.0) + 0.4 * res + (0.15 if kind in UI_KINDS | {"outdoor"} else 0) + (0.1 if photo_like else 0))
    roles["pair"] = _clamp(0.5 + (0.25 if 0.6 <= aspect <= 1.25 else 0) + 0.15 * quality - (0.3 if kind in LOGO_KINDS else 0))
    roles["grid"] = _clamp(0.4 + (0.35 if kind in {"social", "poster", "pattern", "illustration", "stationery"} else 0) + (0.1 if 0.75 <= aspect <= 1.35 else 0))
    roles["identity"] = 1.0 if kind in LOGO_KINDS | {"palette", "typography", "pattern"} else 0.15
    roles["typography"] = 1.0 if kind == "typography" else 0.0
    roles["product"] = _clamp((0.8 if kind in {"product", "packaging"} else 0.3 if kind == "mockup" else 0.0) + 0.2 * quality)
    roles["mockup"] = _clamp(0.9 if kind in {"mockup", "stationery", "packaging"} else 0.2 if photo_like else 0.0)
    roles["campaign"] = _clamp(0.9 if kind in {"poster", "outdoor", "social"} else 0.3 if kind in {"lifestyle", "illustration"} else 0.0)
    roles["closing"] = _clamp(roles["hero"] * 0.7 + (0.3 if kind in LOGO_KINDS else 0) + (0.1 if quiet > 0.6 else 0))
    roles["text_overlay"] = _clamp((quiet - 0.3) * 1.4) if photo_like else 0.0
    return {k: round(v, 3) for k, v in roles.items()}


_PAIR_TOKENS = {
    "before": {"before", "antes", "original", "raw", "orig"},
    "after": {"after", "depois", "edited", "editado", "retouched", "retocado", "final"},
}


def _pair_key(asset: AssetRecord) -> tuple[str | None, str]:
    tokens = tokenize(asset.filename.rsplit(".", 1)[0])
    role = None
    rest = []
    for t in tokens:
        if t in _PAIR_TOKENS["before"]:
            role = "before"
        elif t in _PAIR_TOKENS["after"]:
            role = "after"
        else:
            # digits are kept: they often identify the pair (portrait_03_before)
            rest.append(t)
    return role, "_".join(rest)


def detect_before_after(assets: Iterable[AssetRecord]) -> list[tuple[str, str]]:
    """Return (before_id, after_id) pairs matched by file-name stem."""
    befores: dict[str, AssetRecord] = {}
    afters: dict[str, AssetRecord] = {}
    for asset in assets:
        if not asset.is_visual:
            continue
        role, key = _pair_key(asset)
        if role == "before":
            befores[key] = asset
        elif role == "after":
            afters[key] = asset
    pairs = []
    for key, before in befores.items():
        after = afters.get(key)
        if after is not None:
            pairs.append((before.id, after.id))
    return pairs


def near_duplicate_clusters(assets: list[AssetRecord], threshold: int = 6) -> list[list[str]]:
    """Cluster visually near-identical images by perceptual hash distance."""
    items = [a for a in assets if a.phash and a.is_visual]
    parent = {a.id: a.id for a in items}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            if abs(a.aspect - b.aspect) > 0.05:
                continue
            if hamming(a.phash, b.phash) <= threshold:
                parent[find(a.id)] = find(b.id)
    groups: dict[str, list[str]] = defaultdict(list)
    for a in items:
        groups[find(a.id)].append(a.id)
    return [g for g in groups.values() if len(g) > 1]


def group_assets(assets: list[AssetRecord]) -> dict[str, list[AssetRecord]]:
    """Group usable assets by semantic kind."""
    groups: dict[str, list[AssetRecord]] = defaultdict(list)
    for asset in assets:
        if asset.excluded or not asset.is_visual:
            continue
        groups[asset.effective_kind].append(asset)
    return dict(groups)


__all__ = [
    "ROLES",
    "infer_roles",
    "quality_score",
    "detect_before_after",
    "near_duplicate_clusters",
    "group_assets",
    "MOTION_KINDS",
]
