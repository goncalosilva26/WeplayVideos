"""Rendered visual QA: measure what was actually drawn.

The geometric validator checks the design spec before rendering. This
module inspects the rendered pixels of every section (the same Chromium
capture used for previews) and reports problems a spec cannot show:

* ``rendered_whitespace``  – a media section whose surface is mostly empty;
* ``rendered_blank_media`` – an image area that rendered as a flat field
  (missing or failed media);
* ``rendered_contrast``    – text over imagery whose measured background
  contrast is too low;
* ``rendered_off_balance`` – a composition meant to be centred whose visual
  mass sits clearly to one side.

These are technical measurements. Passing them does not make a layout
good; failing them marks a section for a targeted re-composition (see
``generation.pipeline.refine_rendered``). With a configured multimodal
provider an additional AI critique can be layered on top.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from behance_studio.design import color as C
from behance_studio.layout.devices import media_rect
from behance_studio.layout.model import Presentation, Section

# Fraction of a media section allowed to be plain ground, per concept.
WHITESPACE_LIMIT = {"minimal": 0.86, "bold": 0.8, "photo": 0.8, "layered": 0.82, "story": 0.82}
TEXT_LED = {"statement", "quote_band", "chapter", "closing", "type_specimen", "cover_logo", "logo_hero", "mark_feature",
            "palette_columns", "palette_circles", "logo_tiles", "logo_pair"}
CENTRED = {"cover_logo", "logo_hero", "stage", "doc_stage", "closing", "quote_band", "poster_wall", "phones", "browser"}


def _rgb(color: str) -> np.ndarray | None:
    rgb = C.parse_hex(color) if color else None
    return np.array(rgb, dtype=np.int16) if rgb else None


def _issue(kind: str, section: Section, severity: str, message: str, value: float, block: str = "") -> dict:
    return {"kind": kind, "section": section.id, "block": block, "severity": severity, "message": message, "value": round(float(value), 3)}


def inspect_section(section: Section, region: np.ndarray, scale: float, concept: str) -> list[dict]:
    issues: list[dict] = []
    h, w = region.shape[:2]
    if h < 4 or w < 4:
        return issues
    module = section.meta.get("module", section.pattern)
    bg = _rgb(section.background)
    media = [b for b in section.blocks if b.kind in ("image", "video")]
    if bg is not None:
        diff = np.abs(region - bg).max(axis=2)
        empty = float((diff < 10).mean())
        if media and module not in TEXT_LED and empty > WHITESPACE_LIMIT.get(concept, 0.85):
            issues.append(_issue("rendered_whitespace", section, "warning", f"Section '{section.title}' is {empty:.0%} empty surface.", empty))
        if module in CENTRED and media:
            mass = (diff >= 18).astype(np.float32)
            total = float(mass.sum())
            if total > 0.02 * mass.size:
                cx = float((mass.sum(axis=0) * np.arange(w)).sum() / total) / w
                if abs(cx - 0.5) > 0.12:
                    issues.append(_issue("rendered_off_balance", section, "warning", f"'{section.title}' leans to one side ({cx:.2f}).", cx))
    for b in media:
        x, y, bw, bh = media_rect(b)
        x0, y0 = max(0, int(x * scale)), max(0, int(y * scale))
        x1, y1 = min(w, int((x + bw) * scale)), min(h, int((y + bh) * scale))
        if x1 - x0 < 6 or y1 - y0 < 6 or b.tint or b.rotate:
            continue
        patch = region[y0:y1, x0:x1]
        if float(patch.std()) < 1.5:
            issues.append(_issue("rendered_blank_media", section, "error", f"An image in '{section.title}' rendered as an empty area.", float(patch.std()), b.id))
    for b in section.blocks:
        if b.kind != "text" or not b.overlay or b.style is None:
            continue
        x0, y0 = max(0, int(b.x * scale)), max(0, int(b.y * scale))
        x1, y1 = min(w, int(b.right * scale)), min(h, int(b.bottom * scale))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        patch = region[y0:y1, x0:x1].reshape(-1, 3)
        ink = _rgb(b.style.color)
        if ink is None:
            continue
        ground = patch[np.abs(patch - ink).max(axis=1) > 60]
        if len(ground) < 10:
            continue
        median = np.median(ground, axis=0)
        ratio = C.contrast_ratio(b.style.color, C.to_hex(tuple(int(v) for v in median)))
        if ratio < 3.0:
            issues.append(_issue("rendered_contrast", section, "warning", f"Text '{b.text[:24]}' over imagery measures {ratio:.1f}:1.", ratio, b.id))
    return issues


def inspect_rendered(presentation: Presentation, image: Image.Image, scale: float) -> list[dict]:
    """Inspect a full-length capture (``scale`` = pixels per design px)."""
    arr = np.asarray(image.convert("RGB")).astype(np.int16)
    concept = presentation.variant.get("concept", presentation.family)
    issues: list[dict] = []
    for section, y0 in zip(presentation.sections, presentation.section_offsets()):
        top, bottom = int(round(y0 * scale)), int(round((y0 + section.height) * scale))
        region = arr[top:bottom]
        issues.extend(inspect_section(section, region, scale, concept))
    return issues


def score(issues: list[dict]) -> float:
    """Lower is better: errors weigh more than warnings."""
    return sum(3.0 if i.get("severity") == "error" else 1.0 for i in issues if str(i.get("kind", "")).startswith("rendered_"))
