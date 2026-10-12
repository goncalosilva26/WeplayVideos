"""AI visual critique of rendered proposals (optional, bounded).

The rendered QA (:mod:`behance_studio.qa.rendered`) measures technical
problems. This module asks a multimodal provider to *look* at the rendered
sections — small JPEG crops of the same capture used for previews — and
judge them as an art director would, against a fixed rubric:

* every section gets a score from 1 to 5 and problems from a closed list;
* ``recompose`` marks sections a different composition of the same content
  would improve.

The pipeline then recomposes at most :data:`MAX_FIXES` flagged sections per
proposal with an alternative module, re-renders once, and keeps the change
only when the technical checks do not get worse. It is one round: the
critique is not repeated on the recomposed result, so its score describes
the version that was reviewed.

Privacy: rendered sections contain the project's images, so this only runs
when the project has allowed AI assistance *and* sending previews is
enabled. Nothing runs unless "AI visual critique" is switched on.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

from behance_studio.ai.providers import ImagePart
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

MAX_SECTIONS = 16
MAX_FIXES = 3
SECTION_WIDTH = 512
SECTION_MAX_HEIGHT = 900
ANSWER_TOKENS = 1400
PROBLEMS = [
    "weak_hierarchy", "too_empty", "cramped", "awkward_crop", "poor_contrast", "unbalanced",
    "repetitive", "low_quality_image", "off_concept", "text_hard_to_read",
]

SYSTEM = (
    "You are a senior art director reviewing a Behance case study before it is published. You see its sections in "
    "order, rendered exactly as they will be exported. Judge only what is visible: composition, hierarchy, balance, "
    "cropping, contrast, rhythm between sections and fit with the stated concept. Do not comment on the brand's "
    "design itself — only on how this presentation shows it. Be strict and concrete. Answer with JSON only."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall": {"type": "integer"},
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "integer"},
                    "score": {"type": "integer"},
                    "problems": {"type": "array", "items": {"type": "string", "enum": PROBLEMS}},
                    "action": {"type": "string", "enum": ["keep", "recompose"]},
                    "note": {"type": "string"},
                },
                "required": ["section", "score", "problems", "action", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall", "summary", "sections"],
    "additionalProperties": False,
}

RUBRIC = (
    "Rubric for each section score: 5 portfolio-ready; 4 good, minor issues; 3 acceptable but unremarkable; "
    "2 clearly weak (hierarchy, crop, balance or emptiness problems a viewer would notice); 1 broken. "
    "Use action \"recompose\" only for sections scoring 1–2 that a different arrangement of the same content would fix."
)


def section_images(presentation, capture: Image.Image) -> list[tuple[int, ImagePart]]:
    """Crop each section from a full-length capture (any scale)."""
    scale = capture.width / max(1.0, float(presentation.width))
    out: list[tuple[int, ImagePart]] = []
    for index, (section, y0) in enumerate(zip(presentation.sections, presentation.section_offsets())):
        if len(out) >= MAX_SECTIONS:
            break
        top, bottom = int(round(y0 * scale)), int(round((y0 + section.height) * scale))
        if bottom - top < 8:
            continue
        crop = capture.crop((0, top, capture.width, min(capture.height, bottom))).convert("RGB")
        ratio = min(SECTION_WIDTH / crop.width, SECTION_MAX_HEIGHT / crop.height, 1.0)
        if ratio < 1.0:
            crop = crop.resize((max(1, int(crop.width * ratio)), max(1, int(crop.height * ratio))), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, "JPEG", quality=78)
        out.append((index, ImagePart(buf.getvalue(), "image/jpeg", crop.width, crop.height)))
    return out


def critique_presentation(service, presentation, capture_path) -> dict[str, Any] | None:
    """Ask the provider for a structured critique; cached by image content."""
    import hashlib
    import json

    from behance_studio.director.concepts import CONCEPTS

    with Image.open(capture_path) as im:
        crops = section_images(presentation, im.convert("RGB"))
    if not crops:
        return None
    concept = presentation.variant.get("concept", presentation.family)
    info = CONCEPTS.get(concept)
    lines = [f"Concept: {info.name} — {info.description}" if info else f"Layout family: {presentation.family}",
             f"{len(crops)} section image(s) follow in order; image k is section k (numbered from 0).", RUBRIC]
    for k, (index, _) in enumerate(crops):
        section = presentation.sections[index]
        lines.append(f"{k}: {section.meta.get('module', section.pattern)}")
    lines.append('Return {"overall": 1-5, "summary": "<two sentences>", "sections": [{"section": k, "score": 1-5, '
                 '"problems": [...], "action": "keep" | "recompose", "note": "<one short sentence>"}]}')
    prompt = "\n".join(lines)
    digest = hashlib.sha256(prompt.encode("utf-8"))
    for _, part in crops:
        digest.update(hashlib.sha256(part.data).digest())
    key = service._key("critique", digest.hexdigest())
    data = service._cache_get("critique", key)
    if data is None:
        data = service.provider.complete_json(SYSTEM, prompt, [part for _, part in crops], max_tokens=ANSWER_TOKENS,
                                              schema=SCHEMA, effort="low", purpose="critique")
        service._cache_put("critique", key, data)
    return normalise(data, presentation, [index for index, _ in crops]) if isinstance(data, dict) else None


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def normalise(data: dict[str, Any], presentation, indices: list[int]) -> dict[str, Any]:
    """Map the answer back to section ids; drop anything that does not exist."""
    sections = []
    seen = set()
    for item in data.get("sections") or []:
        if not isinstance(item, dict):
            continue
        k = _clamp(item.get("section"), -1, len(indices) - 1, -1)
        if k < 0 or k in seen:
            continue
        seen.add(k)
        section = presentation.sections[indices[k]]
        problems = [p for p in (item.get("problems") or []) if p in PROBLEMS][:4]
        score = _clamp(item.get("score"), 1, 5, 3)
        action = "recompose" if item.get("action") == "recompose" and score <= 2 else "keep"
        sections.append({"section": section.id, "plan_id": section.plan_id, "index": indices[k], "score": score,
                         "problems": problems, "action": action, "note": " ".join(str(item.get("note", "")).split())[:160]})
    return {
        "overall": _clamp(data.get("overall"), 1, 5, 3),
        "summary": " ".join(str(data.get("summary", "")).split())[:300],
        "sections": sections,
    }


def to_fix(critique: dict[str, Any]) -> list[str]:
    """Plan ids of the weakest sections the critique asked to recompose."""
    flagged = [s for s in critique.get("sections", []) if s.get("action") == "recompose" and s.get("plan_id")]
    flagged.sort(key=lambda s: s["score"])
    return [s["plan_id"] for s in flagged[:MAX_FIXES]]
