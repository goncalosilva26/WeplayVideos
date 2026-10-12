"""Deterministic layout validation and quality metrics.

Checks geometry and content integrity without a browser: bounds, overlaps,
text overflow, legibility (size, WCAG contrast), cropping of protected
artwork, upscaling, missing or repeated assets, spacing anomalies, alignment
and script compliance. The browser adds a rendered check (overflow, broken
images) during preview rendering.

Scores are internal engineering metrics; they are *not* a measure of artistic
quality and are presented as such.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from behance_studio.design import color as C
from behance_studio.layout import text as T
from behance_studio.layout.fitting import MAX_CROP, TOP_ANCHORED_CROP, _content_safe
from behance_studio.layout.devices import media_rect
from behance_studio.layout.model import Block, Presentation, Section
from behance_studio.planning.models import PresentationPlan
from behance_studio.projects.models import AssetRecord

CONTENT_KINDS = {"image", "video", "text"}


@dataclass
class Issue:
    severity: str  # error | warning | info
    code: str
    message: str
    section_id: str = ""
    block_id: str = ""
    section_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class QualityReport:
    issues: list[Issue] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def overall(self) -> float:
        return self.scores.get("overall", 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {"issues": [i.to_dict() for i in self.issues], "metrics": self.metrics, "scores": self.scores}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityReport":
        return cls(
            issues=[Issue(**i) for i in data.get("issues", [])],
            metrics=dict(data.get("metrics", {})),
            scores=dict(data.get("scores", {})),
        )

    def section_errors(self, section_id: str) -> list[Issue]:
        return [i for i in self.errors if i.section_id == section_id]


def _intersection(a: Block, b: Block) -> float:
    w = min(a.right, b.right) - max(a.x, b.x)
    h = min(a.bottom, b.bottom) - max(a.y, b.y)
    return w * h if w > 0 and h > 0 else 0.0


def _background_under(section: Section, block: Block) -> str:
    cx, cy = block.x + block.w / 2, block.y + block.h / 2
    bg = section.background
    best_z = -1
    for b in section.blocks:
        if b.kind == "shape" and b is not block and b.fill and b.z <= block.z and b.x <= cx <= b.right and b.y <= cy <= b.bottom:
            fill = str(b.fill)
            if fill.startswith(("linear", "radial", "rgba", "transparent")):
                continue
            if b.z >= best_z:
                bg, best_z = fill, b.z
    return bg


def displayed_width(block: Block, asset: AssetRecord) -> float:
    _x, _y, mw, mh = media_rect(block)
    inner_w = max(1.0, mw - 2 * block.pad)
    inner_h = max(1.0, mh - 2 * block.pad)
    if block.zoom and block.zoom > 1 and block.fit == "cover":
        inner_w *= block.zoom
        inner_h *= block.zoom
    if block.fit == "cover":
        return max(inner_w, inner_h * asset.aspect)
    return min(inner_w, inner_h * asset.aspect)


def validate_section(section: Section, width: float, assets: dict[str, AssetRecord], issues: list[Issue]) -> dict[str, float]:
    sid, title = section.id, section.title
    stats = {"images": 0, "upscale_sum": 0.0, "text_blocks": 0, "contrast_fail": 0, "small_text": 0}

    def add(sev: str, code: str, msg: str, block: Block | None = None) -> None:
        issues.append(Issue(sev, code, msg, sid, block.id if block else "", title))

    if section.height < 120 and section.type != "divider":
        add("warning", "section_small", f"Section '{title}' is unusually short ({section.height:.0f}px).")
    if section.height > 7500:
        add("warning", "section_large", f"Section '{title}' is very tall ({section.height:.0f}px); consider fewer images.")
    for b in section.blocks:
        tol = 1.5
        x0, y0, x1, y1 = b.bounds()
        if not b.meta.get("bleed") and (x0 < -tol or y0 < -tol or x1 > width + tol or y1 > section.height + tol):
            add("error", "out_of_bounds", f"An element extends outside section '{title}'.", b)
        if b.w <= 0 or b.h <= 0:
            add("error", "invalid_size", f"An element in '{title}' has an invalid size.", b)
        if any(math.isnan(v) or math.isinf(v) for v in (b.x, b.y, b.w, b.h)):
            add("error", "invalid_coordinates", f"Invalid coordinates in '{title}'.", b)

    content = [b for b in section.blocks if b.kind in CONTENT_KINDS and not b.decorative]
    for i, a in enumerate(content):
        for b in content[i + 1 :]:
            inter = _intersection(a, b)
            if inter <= 0:
                continue
            smaller = min(a.w * a.h, b.w * b.h)
            if smaller <= 0 or inter / smaller < 0.01:
                continue
            text_over_image = (a.kind == "text" and a.overlay and b.kind in ("image", "video")) or (b.kind == "text" and b.overlay and a.kind in ("image", "video"))
            if text_over_image:
                continue
            # Deliberately layered media (collages, stacked cards) may overlap
            # each other — never text.
            if a.kind != "text" and b.kind != "text" and (a.meta.get("layered") or b.meta.get("layered")):
                continue
            if a.kind == "text" and b.kind == "text" and (a.overlay or b.overlay) and abs(a.y - b.y) > 0:
                # stacked overlay labels share a scrim, never each other's lines
                if min(a.bottom, b.bottom) - max(a.y, b.y) <= 1:
                    continue
            add("error", "overlap", f"Two elements overlap in section '{title}'.", b)

    for b in section.blocks:
        if b.kind == "text" and b.style is not None:
            stats["text_blocks"] += 1
            st = b.style
            if st.size < 10.5 * (width / 1400):
                add("warning", "text_small", f"Text '{b.text[:30]}' is very small ({st.size:.1f}px).", b)
                stats["small_text"] += 1
            if b.role != "marquee":
                widest = T.widest(b.lines, st)
                if widest > b.w + 2:
                    add("error", "text_overflow", f"Text '{b.text[:30]}' is wider than its box.", b)
                expected = T.text_height(b.lines, st, b.para_gap)
                if expected > b.h + 1:
                    add("error", "text_overflow", f"Text '{b.text[:30]}' is taller than its box.", b)
            if not b.overlay and not st.stroke:
                bg = _background_under(section, b)
                ratio = C.contrast_ratio(st.color, bg) if C.parse_hex(bg) else 21.0
                need = 3.0 if st.size >= 24 * (width / 1400) or (st.size >= 18.5 and st.weight >= 700) else 4.5
                if ratio < need:
                    stats["contrast_fail"] += 1
                    sev = "error" if ratio < 2.0 else "warning"
                    add(sev, "contrast", f"Low contrast ({ratio:.1f}:1) for text '{b.text[:30]}'.", b)
        if b.kind in ("image", "video") and b.asset_id:
            asset = assets.get(b.asset_id)
            if asset is None:
                add("error", "missing_asset", f"An image in '{title}' refers to an asset that no longer exists.", b)
                continue
            if asset.status != "ok":
                add("error", "missing_asset", f"'{asset.filename}' is {asset.status}.", b)
                continue
            stats["images"] += 1
            if b.fit == "cover" and b.crop > 0.015:
                kind = asset.effective_kind
                limit = MAX_CROP.get(kind, 0.08)
                if kind in TOP_ANCHORED_CROP and b.focal[1] == 0.0:
                    limit = TOP_ANCHORED_CROP[kind]
                vis = tuple(b.meta.get("visible", (0, 0, 1, 1)))
                if b.crop > limit + 0.02 and not _content_safe(asset, vis):  # type: ignore[arg-type]
                    add("error", "artwork_cropped", f"'{asset.filename}' is cropped by {b.crop:.0%} (allowed {limit:.0%}).", b)
            if asset.media_type != "svg" and asset.width > 0:
                shown = displayed_width(b, asset)
                factor = shown / asset.width
                stats["upscale_sum"] += max(0.0, factor - 1.0)
                if factor > 2.2:
                    add("warning", "low_resolution", f"'{asset.filename}' is shown at {factor:.1f}× its resolution.", b)
                elif factor > 1.5:
                    add("info", "upscaled", f"'{asset.filename}' is enlarged {factor:.1f}×.", b)

    # Large empty bands inside the section.
    spans = sorted((b.y, b.bottom) for b in content)
    if spans:
        cursor = spans[0][1]
        for top, bottom in spans[1:]:
            if top - cursor > 900:
                add("warning", "empty_space", f"A large empty gap ({top - cursor:.0f}px) appears inside '{title}'.")
            cursor = max(cursor, bottom)
    # Near-miss alignment of text columns (1–6 px apart looks like an error).
    lefts = sorted({round(b.x) for b in section.blocks if b.kind == "text" and b.align == "left" and not b.overlay})
    for a, b2 in zip(lefts, lefts[1:]):
        if 1 <= b2 - a <= 5:
            add("info", "misaligned", f"Text in '{title}' is almost, but not exactly, aligned ({b2 - a}px).")
            break
    return stats


def validate_presentation(
    presentation: Presentation,
    assets: dict[str, AssetRecord],
    plan: PresentationPlan | None = None,
) -> QualityReport:
    issues: list[Issue] = []
    totals: Counter = Counter()
    for section in presentation.sections:
        stats = validate_section(section, presentation.width, assets, issues)
        totals.update(stats)

    # Repeated images.
    usage = Counter()
    for s in presentation.sections:
        for aid in set(s.asset_ids()):
            asset = assets.get(aid)
            # Brand marks recur deliberately across an identity case study
            # (cover, logo pages, badges, sign-off).
            if asset is not None and asset.effective_kind in ("logo", "logo_variant", "monogram"):
                continue
            usage[aid] += 1
    reprise_ok = {s.asset_ids()[0] for s in presentation.sections if s.type == "closing" and s.asset_ids()}
    for aid, count in usage.items():
        allowed = 2 if aid in reprise_ok else 1
        if count > allowed:
            name = assets[aid].filename if aid in assets else aid
            issues.append(Issue("warning", "repeated_image", f"'{name}' is used {count} times."))

    # Images in a section they do not belong to (see planning.fit).
    if plan is not None:
        from behance_studio.planning.fit import mismatches

        kinds = {aid: a.effective_kind for aid, a in assets.items()}
        by_plan = {s.plan_id: s for s in presentation.sections if s.plan_id}
        for sp in plan.sections:
            for aid in mismatches(sp, kinds):
                shown = by_plan.get(sp.id)
                name = assets[aid].filename if aid in assets else aid
                issues.append(Issue("warning", "section_mismatch",
                                    f"'{name}' ({kinds[aid].replace('_', ' ')}) is in the section '{sp.title}'.",
                                    shown.id if shown else "", "", sp.title))

    planned = 0
    placed = 0
    compliance_checks = 0
    compliance_fail = 0
    if plan is not None:
        by_plan = {s.plan_id: s for s in presentation.sections}
        order = [s.plan_id for s in presentation.sections]
        hidden = set()
        for sp in plan.sections:
            sec = by_plan.get(sp.id)
            if sec is None:
                hidden.add(sp.id)
                if sp.locked:
                    compliance_checks += 1
                    compliance_fail += 1
                    issues.append(Issue("error", "script_section_missing", f"The script section '{sp.title}' is missing."))
                continue
            sec_assets = set(sec.asset_ids())
            for aid in sp.asset_ids:
                planned += 1
                if aid in sec_assets:
                    placed += 1
                elif sp.locked:
                    compliance_checks += 1
                    compliance_fail += 1
                    issues.append(Issue("error", "script_image_missing", f"A required image is missing from '{sp.title}'.", sec.id, "", sec.title))
                else:
                    issues.append(Issue("warning", "planned_image_missing", f"A planned image was not placed in '{sp.title}'.", sec.id, "", sec.title))
            if sp.locked and sp.exact_text:
                texts = [b.text for b in sec.blocks if b.kind == "text"]
                joined = "\n".join(texts)
                for field_name in ("title", "subtitle", "body"):
                    value = getattr(sp, field_name)
                    if not value:
                        continue
                    compliance_checks += 1
                    group_text = " ".join(b.meta.get("source_text", "") for b in sec.blocks if b.kind == "text")
                    if value not in texts and value not in joined and value not in group_text:
                        compliance_fail += 1
                        issues.append(Issue("error", "script_text_changed", f"The exact {field_name} of '{sp.title}' is not present.", sec.id, "", sec.title))
        locked_ids = [sp.id for sp in plan.sections if sp.locked and sp.id not in hidden]
        positions = [order.index(pid) for pid in locked_ids if pid in order]
        if positions != sorted(positions):
            compliance_fail += 1
            issues.append(Issue("error", "script_order", "The section order differs from the script."))
        compliance_checks += 1 if locked_ids else 0

    n_err = sum(1 for i in issues if i.severity == "error")
    n_warn = sum(1 for i in issues if i.severity == "warning")
    images = max(1, totals["images"])
    texts = max(1, totals["text_blocks"])
    metrics = {
        "sections": len(presentation.sections),
        "height": round(presentation.height),
        "images": totals["images"],
        "text_blocks": totals["text_blocks"],
        "errors": n_err,
        "warnings": n_warn,
        "planned_images": planned,
        "placed_images": placed,
    }
    scores = {
        "completeness": round(placed / planned, 3) if planned else 1.0,
        "compliance": round(1 - compliance_fail / compliance_checks, 3) if compliance_checks else 1.0,
        "integrity": round(max(0.0, 1 - 0.25 * sum(1 for i in issues if i.severity == "error" and i.code in ("overlap", "out_of_bounds", "text_overflow", "artwork_cropped", "missing_asset", "invalid_size"))), 3),
        "readability": round(max(0.0, 1 - (totals["contrast_fail"] + totals["small_text"]) / texts), 3),
        "asset_quality": round(max(0.0, 1 - totals["upscale_sum"] / images), 3),
        "consistency": round(max(0.0, 1 - 0.1 * sum(1 for i in issues if i.code in ("misaligned", "empty_space", "section_small", "section_large", "repeated_image"))), 3),
    }
    weights = {"completeness": 1.0, "compliance": 1.5, "integrity": 2.0, "readability": 1.2, "asset_quality": 0.8, "consistency": 0.8}
    scores["overall"] = round(sum(scores[k] * w for k, w in weights.items()) / sum(weights.values()), 3)
    return QualityReport(issues=issues, metrics=metrics, scores=scores)


# ------------------------------------------------------------ diversity
def signature(presentation: Presentation) -> dict[str, float]:
    """Structural fingerprint used to compare proposals."""
    W = presentation.width
    total_h = max(1.0, presentation.height)
    dark = sum(s.height for s in presentation.sections if C.is_dark(s.background) if C.parse_hex(s.background)) / total_h
    media = [b for s in presentation.sections for b in s.blocks if b.kind in ("image", "video")]
    full_bleed = sum(1 for b in media if b.w >= W - 2) / max(1, len(media))
    mean_w = sum(b.w for b in media) / max(1, len(media)) / W
    texts = [b for s in presentation.sections for b in s.blocks if b.kind == "text" and b.style]
    max_size = max((b.style.size for b in texts), default=0) / W
    upper = sum(1 for b in texts if b.style.uppercase) / max(1, len(texts))
    margins = [min((b.x for b in s.blocks if b.kind == "text"), default=0) / W for s in presentation.sections]
    shapes = sum(1 for s in presentation.sections for b in s.blocks if b.kind == "shape") / max(1, len(presentation.sections))
    bg_changes = sum(1 for a, b in zip(presentation.sections, presentation.sections[1:]) if a.background != b.background) / max(1, len(presentation.sections) - 1)
    centered = sum(1 for b in texts if b.align == "center") / max(1, len(texts))
    return {
        "dark": dark,
        "full_bleed": full_bleed,
        "mean_width": mean_w,
        "max_text": max_size * 10,
        "uppercase": upper,
        "margin": sum(margins) / max(1, len(margins)) * 5,
        "shapes": min(1.0, shapes / 8),
        "bg_changes": bg_changes,
        "centered": centered,
    }


def signature_distance(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    return math.sqrt(sum((a.get(k, 0) - b.get(k, 0)) ** 2 for k in keys))


def _iou(a: Block, b: Block) -> float:
    inter = _intersection(a, b)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def layout_distance(a: Presentation, b: Presentation) -> float:
    """0 = identical composition, 1 = completely different.

    A pure colour variation of the same layout can score at most 0.2 (the
    background term), so values above 0.25 imply structural differences.
    Compares sections that show the same plan content: where the same assets
    are placed (IoU of their frames), section heights, backgrounds and the
    largest text size. Colour-only variations score low by construction.
    """
    by_plan_b = {s.plan_id: s for s in b.sections if s.plan_id}
    diffs: list[float] = []
    for sa in a.sections:
        sb_ = by_plan_b.get(sa.plan_id)
        if sb_ is None:
            continue
        media_a = {x.asset_id: x for x in sa.blocks if x.asset_id}
        media_b = {x.asset_id: x for x in sb_.blocks if x.asset_id}
        common = set(media_a) & set(media_b)
        geo = 1 - (sum(_iou(media_a[k], media_b[k]) for k in common) / len(common)) if common else 0.5
        height = abs(sa.height - sb_.height) / max(sa.height, sb_.height, 1)
        bg = min(1.0, C.delta_e(sa.background, sb_.background) / 60) if C.parse_hex(sa.background) and C.parse_hex(sb_.background) else 0.5
        ta = max((x.style.size for x in sa.blocks if x.style), default=0)
        tb = max((x.style.size for x in sb_.blocks if x.style), default=0)
        text = abs(ta - tb) / max(ta, tb, 1)

        def decor(sec: Section) -> float:
            area = sum(x.w * x.h for x in sec.blocks if x.kind == "shape" and x.fill and not str(x.fill).startswith(("linear", "radial", "transparent")))
            return min(1.0, area / max(1.0, a.width * sec.height))

        deco = abs(decor(sa) - decor(sb_))

        def title_pos(sec: Section) -> tuple[float, float]:
            t = next((x for x in sec.blocks if x.role in ("title", "display")), None)
            return ((t.x + t.w / 2) / a.width, (t.y + t.h / 2) / max(1.0, sec.height)) if t else (0.5, 0.5)

        pa, pb = title_pos(sa), title_pos(sb_)
        title = min(1.0, math.dist(pa, pb) * 2)
        diffs.append(0.3 * geo + 0.1 * height + 0.2 * bg + 0.15 * text + 0.15 * deco + 0.1 * title)
    return sum(diffs) / len(diffs) if diffs else 1.0
