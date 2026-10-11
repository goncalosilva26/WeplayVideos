"""Optional AI assistance for the generation pipeline.

The offline pipeline is always complete on its own; this module only
*refines* its results when the user has configured a provider:

* ``classify_assets``  – recognise asset types from downscaled previews.
* ``refine_direction`` – read the creative brief for personality and mood.
* ``write_copy``       – draft neutral section descriptions.

Privacy and cost rules (see docs/AI_PROVIDERS.md):

* Project content (brief text, previews) is only sent when the project has
  granted AI consent – unless the provider runs on this machine/network.
* Images additionally require the global "allow sending previews" setting,
  and only small JPEG previews are sent, never the original files.
* Every answer is cached by content hash so regenerating does not repeat
  (and re-bill) the same requests.
* Generated copy passes a fact guard: drafts that introduce numbers,
  metrics, awards, clients or superlatives absent from the user's own text
  are rejected and the offline text is kept.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from PIL import Image

from behance_studio.ai.providers import ImagePart, Provider, create_provider
from behance_studio.assets.derivatives import ensure_thumbnail
from behance_studio.assets.roles import infer_roles
from behance_studio.core.errors import OperationCancelled, ProviderError
from behance_studio.core.fsutil import atomic_write_json, read_json
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken
from behance_studio.design.typography import AXES, TypeSystem, rank_pairings
from behance_studio.planning.sections import section_type
from behance_studio.projects.models import ASSET_KINDS

log = get_logger(__name__)

PROMPT_VERSION = 2
PREVIEW_SIZE = 640
MAX_IMAGES_PER_RUN = 150
MIN_CONFIDENCE = 0.6

CLASSIFY_SYSTEM = (
    "You label design-portfolio assets for an offline layout tool. Look at the image and its file name and "
    "answer with JSON only. Do not guess brand facts. Choose exactly one kind from the allowed list."
)
BRIEF_SYSTEM = (
    "You read a designer's creative brief and describe the intended brand personality for an automatic layout tool. "
    "Answer with JSON only. Only use what the brief says or clearly implies; do not invent facts."
)
COPY_SYSTEM = (
    "You write short, neutral captions for sections of a design portfolio presentation. "
    "Strict rules: describe only what the section shows, using only facts present in the provided material. "
    "Never invent clients, results, numbers, percentages, dates, awards, prices, locations or process steps. "
    "No superlatives or marketing claims. One or two plain sentences, at most 32 words. Answer with JSON only."
)

# Copy that sections may receive (others keep titles only).
COPY_TYPES = {
    "intro", "about", "logo", "logo_variations", "visual_language", "applications", "packaging", "campaign",
    "posters", "outdoor", "social", "website", "mobile", "ui_screens", "motion", "photography", "illustration", "editorial",
}

_FORBIDDEN = re.compile(
    r"\b(award\w*|prize\w*|winner|won|wins|winning|nominat\w*|best|leading|first|#1|number one|record|revenue|sales|"
    r"growth|increase\w*|decrease\w*|roi|kpi|conversion\w*|percent|million\w*|billion\w*|thousand\w*|clients?|customers?|"
    r"world[- ]class|unique|unparalleled|revolutionary|iconic|ultimate|prémio\w*|vencedor\w*|melhor\w*|líder|primeiro|"
    r"vendas|crescimento|aumento|clientes?|únic[oa]s?)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d")


class AIService:
    def __init__(self, provider: Provider, settings, project) -> None:
        self.provider = provider
        self.settings = settings
        self.project = project
        self._lock = threading.Lock()
        self.log: list[str] = []
        self.failed: str | None = None  # set after a provider failure: no further requests this run

    # ----------------------------------------------------------- factory
    @classmethod
    def create(cls, project, settings) -> "AIService | None":
        try:
            provider = create_provider(settings)
        except ProviderError as exc:
            log.info("AI not used: %s", exc.message)
            return None
        if provider is None:
            return None
        return cls(provider, settings, project)

    # ----------------------------------------------------------- gating
    @property
    def content_allowed(self) -> bool:
        """May project content (text) be sent to the provider?"""
        if self.failed:
            return False
        return bool(self.project.config.ai_consent) or self.provider.is_local

    @property
    def images_allowed(self) -> bool:
        return self.content_allowed and bool(self.settings.ai.allow_image_upload)

    def status(self) -> str:
        if not self.content_allowed:
            return "AI provider configured, but this project has not allowed AI assistance."
        parts = ["text"] + (["previews"] if self.images_allowed else [])
        return f"AI assistance active ({self.provider.kind}, {self.provider.model}); sends {' and '.join(parts)}."

    # ------------------------------------------------------------- cache
    def _cache_file(self, name: str):
        return self.project.cache_subdir("ai") / f"{name}.json"

    def _cache_get(self, name: str, key: str) -> Any:
        try:
            data = read_json(self._cache_file(name))
        except (OSError, ValueError):
            return None
        return data.get(key) if isinstance(data, dict) else None

    def _cache_put(self, name: str, key: str, value: Any) -> None:
        with self._lock:
            path = self._cache_file(name)
            try:
                data = read_json(path) if path.exists() else {}
            except (OSError, ValueError):
                data = {}
            data[key] = value
            atomic_write_json(path, data)

    def _key(self, *parts: Any) -> str:
        raw = json.dumps([PROMPT_VERSION, self.provider.kind, self.provider.model, *parts], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    # --------------------------------------------------- classification
    def _preview(self, asset) -> ImagePart:
        path = ensure_thumbnail(self.project, asset)
        with Image.open(path) as im:
            image = im.convert("RGB")
        if max(image.size) > PREVIEW_SIZE:
            image.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=82)  # re-encoded: no EXIF/GPS metadata leaves the machine
        return ImagePart(buf.getvalue(), "image/jpeg")

    def _classify_one(self, asset) -> dict[str, Any] | None:
        key = self._key("classify", asset.sha256)
        cached = self._cache_get("classify", key)
        if cached is not None:
            return cached
        kinds = ", ".join(f"{k} ({v})" for k, v in ASSET_KINDS.items())
        prompt = (
            f"File name: {asset.filename}\nFolder: {asset.import_group or '-'}\n"
            f"Allowed kinds: {kinds}\n"
            'Return {"kind": "<one allowed kind>", "confidence": <0..1>, "description": "<max 12 words, what is visible>", '
            '"tags": ["<up to 5 lowercase words>"]}'
        )
        data = self.provider.complete_json(CLASSIFY_SYSTEM, prompt, [self._preview(asset)], max_tokens=200)
        kind = str(data.get("kind", "")).strip().lower().replace(" ", "_")
        if kind not in ASSET_KINDS:
            return None
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        result = {
            "kind": kind,
            "confidence": round(confidence, 3),
            "description": _clean_text(str(data.get("description", "")))[:120],
            "tags": [_clean_text(str(t)).lower()[:24] for t in (data.get("tags") or [])[:5] if str(t).strip()],
        }
        self._cache_put("classify", key, result)
        return result

    def classify_assets(self, project, assets, token: CancelToken | None = None, progress: Callable[[float, str], None] = lambda f, m: None) -> bool:
        if not (self.settings.ai.use_for_classification and self.images_allowed):
            return False
        token = token or CancelToken()
        todo = [a for a in assets if a.is_visual and not a.excluded and not a.user_kind and a.sha256][:MAX_IMAGES_PER_RUN]
        if not todo:
            return False
        changed = []
        done = 0
        failures = 0
        progress(0.0, f"AI is recognising {len(todo)} asset(s)…")
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(self._classify_one, a): a for a in todo}
            try:
                for future in as_completed(futures):
                    if token.cancelled:
                        for f in futures:
                            f.cancel()
                        raise OperationCancelled("Generation cancelled")
                    asset = futures[future]
                    done += 1
                    try:
                        result = future.result()
                    except ProviderError as exc:
                        failures += 1
                        if failures >= 3 and done <= 3:  # failing from the start: stop early
                            for f in futures:
                                f.cancel()
                            self.failed = exc.message
                            raise
                        log.warning("AI classification failed for %s: %s", asset.filename, exc.message)
                        continue
                    progress(done / len(todo), f"AI recognised {done} of {len(todo)}")
                    if result and self._apply_classification(asset, result):
                        changed.append(asset)
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        if changed:
            project.save_assets(changed)
            from behance_studio.assets.importer import finalize_relationships

            finalize_relationships(project, changed)
        self.log.append(f"AI asset recognition: {len(changed)} of {len(todo)} asset type(s) updated.")
        return bool(changed)

    @staticmethod
    def _apply_classification(asset, result: dict[str, Any]) -> bool:
        asset.analysis["ai"] = result
        if result.get("description") and not asset.description:
            asset.description = result["description"]
        if result.get("tags"):
            asset.tags = sorted(set(asset.tags or []) | set(result["tags"]))
        heuristic_conf = asset.kind_confidence or 0.0
        ai_conf = result["confidence"]
        if ai_conf < MIN_CONFIDENCE:
            return bool(result.get("description"))
        if result["kind"] != asset.kind and (heuristic_conf < 0.85 or ai_conf > heuristic_conf):
            asset.kind = result["kind"]
            asset.kind_confidence = ai_conf
            asset.kind_source = "ai"
            asset.roles = infer_roles(asset)
        return True

    # ---------------------------------------------------- creative brief
    def refine_direction(self, project, directives, direction) -> bool:
        brief = directives.brief
        if not (self.settings.ai.use_for_brief and self.content_allowed) or brief.is_empty:
            return False
        key = self._key("brief", brief.raw)
        data = self._cache_get("brief", key)
        if data is None:
            axes = ", ".join(AXES)
            prompt = (
                f"Creative brief:\n\"\"\"\n{brief.raw[:6000]}\n\"\"\"\n"
                f"Rate the intended brand personality on these axes from -1 to 1: {axes} "
                "(warmth: cool→warm, energy: calm→energetic, refinement: casual→refined, boldness: subtle→bold, "
                "modernity: classic→contemporary, organic: geometric→organic). Use null for axes the brief does not imply.\n"
                'Return {"personality": {...}, "mood_words": ["<up to 6 adjectives taken from or implied by the brief>"], '
                '"tone": "light" | "dark" | null}'
            )
            try:
                data = self.provider.complete_json(BRIEF_SYSTEM, prompt, max_tokens=300)
            except ProviderError as exc:
                self.failed = exc.message
                raise
            self._cache_put("brief", key, data)
        changed = False
        personality = data.get("personality") if isinstance(data, dict) else None
        if isinstance(personality, dict):
            for axis in AXES:
                if axis in brief.personality:
                    continue  # explicit wording in the brief always wins
                try:
                    value = personality.get(axis)
                    if value is None:
                        continue
                    value = max(-1.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    continue
                direction.personality[axis] = round(0.5 * direction.personality.get(axis, 0.0) + 0.5 * value, 3)
                changed = True
        words = [w for w in (data.get("mood_words") or []) if isinstance(w, str)] if isinstance(data, dict) else []
        for word in words[:6]:
            word = _clean_text(word).lower()
            if word and len(word) < 24 and word not in direction.mood_words:
                direction.mood_words.append(word)
                changed = True
        tone = data.get("tone") if isinstance(data, dict) else None
        if tone in ("light", "dark") and not brief.tone and tone != direction.tone:
            direction.tone = tone
            changed = True
        if changed and direction.type_system.source != "brief":
            best = rank_pairings(direction.personality)[0]
            direction.type_system = TypeSystem(display=best.display, text=best.text, label=best.label, display_weight=best.display_weight, source="inferred")
        if changed:
            direction.notes.append("Brief interpreted with AI assistance (personality and mood).")
            self.log.append("AI brief interpretation applied.")
        return changed

    # --------------------------------------------------------------- copy
    def write_copy(self, project, plan, directives, direction) -> bool:
        if not (self.settings.ai.use_for_copywriting and self.content_allowed):
            return False
        language = "Portuguese (Portugal)" if plan.language == "pt" else "English"
        assets = {a.id: a for a in project.list_assets()}
        sources = [directives.brief.raw or "", plan.project_title, plan.category_label]
        changed = False
        for sp in plan.sections:
            if sp.locked or sp.exact_text or sp.source == "script" or sp.type not in COPY_TYPES:
                continue
            if sp.meta.get("copy_source") == "user":
                continue
            if sp.type in ("intro", "about") and directives.brief.about:
                continue  # the user's own description is never replaced
            descriptions = [assets[a].description for a in sp.asset_ids if a in assets and assets[a].description][:8]
            material = {
                "project": plan.project_title,
                "category": plan.category_label,
                "section": section_type(sp.type).title("en"),
                "section_title": sp.title,
                "current_text": sp.body,
                "images_show": descriptions,
            }
            key = self._key("copy", plan.language, material, directives.brief.raw)
            draft = self._cache_get("copy", key)
            if draft is None:
                prompt = (
                    f"Language: {language}\nCreative brief (may be empty):\n\"\"\"\n{(directives.brief.raw or '')[:4000]}\n\"\"\"\n"
                    f"Section material:\n{json.dumps(material, ensure_ascii=False)}\n"
                    'Return {"text": "<one or two sentences describing what this section shows>"}'
                )
                try:
                    answer = self.provider.complete_json(COPY_SYSTEM, prompt, max_tokens=160)
                except ProviderError as exc:
                    log.warning("AI copy failed: %s", exc.message)
                    self.failed = exc.message
                    raise
                draft = _clean_text(str(answer.get("text", "")))
                self._cache_put("copy", key, draft)
            source_text = " ".join(sources + descriptions + [sp.title, sp.body or ""])
            ok, reason = fact_guard(draft, source_text)
            if not ok:
                log.info("AI copy for %s rejected: %s", sp.type, reason)
                sp.meta["ai_copy_rejected"] = reason
                continue
            sp.body = draft
            sp.meta["copy_source"] = "ai"
            changed = True
        if changed:
            self.log.append("AI drafted section descriptions (checked by the fact guard).")
        return changed


# ---------------------------------------------------------------- helpers
def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().strip('"').strip()
    return text


def fact_guard(draft: str, source_text: str) -> tuple[bool, str]:
    """Reject drafts that add facts the user did not provide."""
    if not draft:
        return False, "empty"
    words = draft.split()
    if len(words) > 45:
        return False, "too long"
    source_lower = source_text.lower()
    for match in _FORBIDDEN.finditer(draft):
        if match.group(0).lower() not in source_lower:
            return False, f"claim word “{match.group(0)}”"
    for token in re.findall(r"[\w%.,]*\d[\w%.,]*", draft):
        if token.strip(".,") not in source_text:
            return False, f"number “{token}”"
    # Proper names must come from the user's material.
    sentences = re.split(r"(?<=[.!?])\s+", draft)
    for sentence in sentences:
        for i, word in enumerate(sentence.split()):
            clean = word.strip(".,;:!?“”\"'()[]")
            if i > 0 and clean[:1].isupper() and len(clean) > 1 and clean.lower() not in source_lower:
                return False, f"name “{clean}”"
    return True, ""
