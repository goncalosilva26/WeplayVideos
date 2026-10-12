"""Optional AI assistance for the generation pipeline.

The offline pipeline is always complete on its own; this module only
*refines* its results when the user has configured a provider:

* ``classify_assets``  – recognise asset types from downscaled previews.
* ``refine_direction`` – read the creative brief for personality and mood.
* ``direct_plan``      – AI Creative Director: a validated storyboard for a
                         concept (see :mod:`ai.director`), local fallback.
* ``write_copy``       – draft neutral section descriptions.
* ``critique``         – AI critique of rendered sections (see :mod:`ai.critique`).

Costs (see :mod:`ai.costs`): every request is authorised against the
spending limits before it is sent and its reported usage is recorded;
``estimate_generation`` discloses the expected requests and cost before a
paid run starts.

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

from behance_studio.ai.costs import (
    BudgetExceeded,
    CostEstimate,
    PriceUnknown,
    SpendMeter,
    UsageLedger,
    resolve_prices,
)
from behance_studio.ai.providers import ImagePart, Provider, create_provider
from behance_studio.ai.vision import SYSTEM as CLASSIFY_SYSTEM
from behance_studio.assets.derivatives import ensure_thumbnail
from behance_studio.assets.roles import infer_roles
from behance_studio.core.errors import OperationCancelled, ProviderError
from behance_studio.core.fsutil import atomic_write_json, read_json
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken
from behance_studio.design.typography import AXES, TypeSystem, rank_pairings
from behance_studio.planning.sections import section_type

log = get_logger(__name__)

PROMPT_VERSION = 2
PREVIEW_SIZE = 640
MAX_IMAGES_PER_RUN = 150
MIN_CONFIDENCE = 0.6

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

# Concept modules that display a section's body text.
COPY_MODULES = {"statement", "split_feature"}

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
        self.director_off: str | None = None
        self.stats = {"analysed": 0, "from_cache": 0, "failed": 0}
        ai = settings.ai
        prices = resolve_prices(provider.kind, provider.model, provider.is_local, ai)
        self.meter = SpendMeter(provider.kind, provider.model, prices, provider.may_bill and not provider.is_local,
                                getattr(ai, "run_limit_usd", 0.0), getattr(ai, "monthly_limit_usd", 0.0), UsageLedger())
        provider.meter = self.meter

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
        if provider.kind == "ollama":
            # A quick local check: when Ollama or the model is missing the
            # app simply works offline (Settings shows how to set it up).
            from behance_studio.ai.ollama import detect

            status = detect(provider.base_url, provider.model, timeout=2.0)
            if not status.ready:
                log.info("Local AI not used: %s", status.summary())
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
        from behance_studio.ai.providers import is_loopback_url

        if not self.content_allowed:
            return False
        # A model on this computer sees previews without them leaving the PC.
        on_this_pc = self.provider.is_local and is_loopback_url(self.provider.base_url)
        return on_this_pc or bool(self.settings.ai.allow_image_upload)

    def status(self) -> str:
        if self.failed:
            return f"AI assistance stopped: {self.failed}"
        if not self.content_allowed:
            return "AI provider configured, but this project has not allowed AI assistance."
        parts = ["text"] + (["previews"] if self.images_allowed else [])
        return f"AI assistance active ({self.provider.kind}, {self.provider.model}); sends {' and '.join(parts)}."

    def _stop_for_budget(self, exc: Exception) -> None:
        message = getattr(exc, "message", str(exc))
        self.failed = message
        if message not in self.log:
            self.log.append(message)

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

    def _classify_one(self, asset, include_names: bool = True) -> dict[str, Any] | None:
        """Design purpose of one asset, from the image itself (a small preview).

        Cached by image content + model + prompt version + the folder/file-name
        context in the prompt (shared by all projects): an unchanged image is
        never analysed twice. ``None`` = the model's answer was unusable."""
        from behance_studio.ai import vision
        from behance_studio.ai.cache import ANALYSIS_CACHE

        folder = asset.source_folder or asset.import_group
        key = self._key("classify", vision.PROMPT_VERSION, asset.sha256, include_names, folder if include_names else "",
                        asset.filename if include_names else "")
        with ANALYSIS_CACHE.lock(key):
            cached = ANALYSIS_CACHE.get(key) or self._cache_get("classify", key)
            if cached is not None:
                self.stats["from_cache"] += 1
                return {**cached, "from_cache": True}
            prompt = vision.prompt(asset.filename, folder, include_names)
            image = self._preview(asset)  # the actual pixels, re-encoded (no metadata)
            data = self.provider.complete_json(vision.SYSTEM, prompt, [image], max_tokens=240, schema=vision.SCHEMA, purpose="classify")
            self.stats["analysed"] += 1
            result = vision.normalise(data)
            if result is None:
                log.info("AI answer for %s was unusable: %s", asset.filename, str(data)[:200])
                return None
            result["model"] = self.provider.model
            ANALYSIS_CACHE.put(key, result)
            self._cache_put("classify", key, result)
            return result

    def classify_assets(self, project, assets, token: CancelToken | None = None, progress: Callable[[float, str], None] = lambda f, m: None) -> bool:
        if not (self.settings.ai.use_for_classification and self.images_allowed):
            return False
        token = token or CancelToken()
        todo = self._classify_todo(assets)
        if not todo:
            return False
        changed = []
        done = 0
        failures = 0
        progress(0.0, f"AI is recognising {len(todo)} asset(s)…")
        with ThreadPoolExecutor(max_workers=max(1, getattr(self.provider, "parallel", 3))) as pool:
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
                    except (BudgetExceeded, PriceUnknown) as exc:
                        for f in futures:
                            f.cancel()
                        self._stop_for_budget(exc)
                        break
                    except ProviderError as exc:
                        failures += 1
                        self.stats["failed"] += 1
                        if failures >= 3 and done <= 3:  # failing from the start: stop early
                            for f in futures:
                                f.cancel()
                            self.failed = exc.message
                            raise
                        log.warning("AI classification failed for %s: %s", asset.filename, exc.message)
                        self._record_unanalysed(asset, f"not run: {exc.message} (the measured type is used)")
                        changed.append(asset)
                        continue
                    except Exception as exc:  # noqa: BLE001 - one unreadable preview must not stop the rest
                        log.warning("AI classification skipped %s: %s", asset.filename, exc)
                        self._record_unanalysed(asset, f"not run: the preview could not be read ({exc}); the measured type is used")
                        changed.append(asset)
                        continue
                    progress(done / len(todo), f"AI recognised {done} of {len(todo)}")
                    if result is None:
                        self._record_unanalysed(asset, "not applied: the model's answer was not one of the known types; the measured type is used")
                        changed.append(asset)
                    elif self._apply_classification(asset, result):
                        changed.append(asset)
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        if changed:
            project.save_assets(changed)
            from behance_studio.assets.importer import finalize_relationships

            finalize_relationships(project, changed)
        retyped = sum(1 for a in changed if (a.analysis.get("ai") or {}).get("applied") and a.kind_source == "ai")
        self.log.append(f"AI asset recognition ({self.provider.model}): {self.stats['analysed']} image(s) analysed, "
                        f"{self.stats['from_cache']} from cache, {self.stats['failed']} failed; {retyped} type(s) set by AI.")
        return bool(changed)

    def _classify_todo(self, assets) -> list:
        return [a for a in assets if a.is_visual and not a.excluded and not a.user_kind and a.sha256
                and a.effective_kind != "reference"][:MAX_IMAGES_PER_RUN]

    def _apply_classification(self, asset, result: dict[str, Any]) -> bool:
        return self.apply_classification(asset, result, folder_authority=getattr(self.project.config, "section_source", "auto") != "content")

    @staticmethod
    def apply_classification(asset, result: dict[str, Any], folder_authority: bool = True) -> bool:
        """Apply the model's answer to the asset's *type* and record why.

        Every answer is stored with an explicit decision (never dropped
        silently). The type decides how an image is shown; the section it
        belongs to is decided separately (planning.assignment) — in an
        organised project by its folder, which the AI never overrides."""
        from behance_studio.ai.vision import implausible
        from behance_studio.assets.folders import FOLDER_KINDS, section_type_of_path

        result = {k: v for k, v in result.items() if k not in ("decision", "applied", "rejected")}
        before = asset.effective_kind
        reason = implausible(result, asset)
        applied = False
        folder = asset.source_folder or asset.import_group
        folder_type = section_type_of_path(folder)
        allowed = FOLDER_KINDS.get(folder_type or "", set())
        if asset.user_kind:
            decision = f"not applied: you set the type to {asset.user_kind.replace('_', ' ')}"
        elif reason:
            decision = f"rejected: {reason}"
            result["rejected"] = reason
        elif result["confidence"] < MIN_CONFIDENCE:
            decision = f"not applied: the model was unsure ({result['confidence']:.2f} < {MIN_CONFIDENCE})"
        elif allowed and result["kind"] not in allowed and folder_authority:
            # The designer filed it in a section folder: the model may refine the type
            # within that section (packaging / product / mockup…), never contradict it.
            decision = (f"not applied: '{result['kind'].replace('_', ' ')}' contradicts the folder "
                        f"'{folder.split('/')[-1]}' ({folder_type.replace('_', ' ')})")
        else:
            applied = True
            decision = "applied (agrees with the measured type)" if result["kind"] == asset.kind else \
                f"applied (the measured guess was {asset.kind.replace('_', ' ')})"
        result["decision"] = decision
        result["applied"] = applied
        result["sha256"] = asset.sha256  # which image this answer is about
        asset.analysis["ai"] = result
        if result.get("description") and not asset.description:
            asset.description = result["description"]
        if result.get("tags"):
            asset.tags = sorted(set(asset.tags or []) | set(result["tags"]))
        if applied and result["kind"] != asset.kind:
            asset.kind = result["kind"]
            asset.kind_confidence = result["confidence"]
            asset.kind_source = "ai"
            asset.roles = infer_roles(asset)
        elif applied:  # the model confirmed the measured type
            asset.kind_confidence = max(asset.kind_confidence or 0.0, result["confidence"])
            asset.kind_source = "ai"
        log.info("AI type for %s: %s (%.2f) — %s [type now %s, was %s]", asset.filename, result["kind"], result["confidence"],
                 decision, asset.effective_kind, before)
        return True

    @staticmethod
    def _record_unanalysed(asset, decision: str) -> None:
        previous = (asset.analysis or {}).get("ai") or {}
        if previous.get("kind") and previous.get("sha256", asset.sha256) == asset.sha256:
            # An earlier answer about this same image stays in force; only the failed attempt is noted.
            asset.analysis["ai"] = {**previous, "last_attempt": decision}
            return
        asset.analysis["ai"] = {"kind": None, "decision": decision, "applied": False}

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
                data = self.provider.complete_json(BRIEF_SYSTEM, prompt, max_tokens=300, schema=BRIEF_SCHEMA, purpose="brief")
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
            if sp.meta.get("module") and sp.meta["module"] not in COPY_MODULES:
                continue  # this composition does not display a description: nothing to write
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
                if not self.content_allowed:
                    break
                prompt = (
                    f"Language: {language}\nCreative brief (may be empty):\n\"\"\"\n{(directives.brief.raw or '')[:4000]}\n\"\"\"\n"
                    f"Section material:\n{json.dumps(material, ensure_ascii=False)}\n"
                    'Return {"text": "<one or two sentences describing what this section shows>"}'
                )
                try:
                    answer = self.provider.complete_json(COPY_SYSTEM, prompt, max_tokens=160, schema=COPY_SCHEMA, purpose="copy")
                except (BudgetExceeded, PriceUnknown) as exc:
                    self._stop_for_budget(exc)
                    break
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
        note = "AI drafted section descriptions (checked by the fact guard)."
        if changed and note not in self.log:
            self.log.append(note)
        return changed


    # -------------------------------------------------- creative direction
    def direct_plan(self, project, ctx, spec, others: list[str] | None = None):
        """An AI-directed plan for a 2.0 concept, or None (use the offline director)."""
        from behance_studio.ai import director as AD
        from behance_studio.layout.families import is_concept

        if not (getattr(self.settings.ai, "use_for_direction", True) and self.content_allowed) or self.director_off:
            return None
        if not is_concept(spec.family) or ctx.directives.script_locked:
            return None
        references = [a for a in project.list_assets() if a.is_visual and not a.excluded and a.effective_kind == "reference"]
        request = AD.build_request(project, ctx, spec.family, spec.seed, spec.creativity, list(others or []),
                                   self.images_allowed, references)
        key = request.key(self.provider.kind, self.provider.model)
        data = self._cache_get("director", key)
        if data is None:
            try:
                data = self.provider.complete_json(request.system, request.prompt, request.images, max_tokens=AD.ANSWER_TOKENS,
                                                   schema=AD.SCHEMA, effort="medium", purpose="director", shared=request.shared)
            except (BudgetExceeded, PriceUnknown) as exc:
                self._stop_for_budget(exc)
                return None
            except ProviderError as exc:
                log.warning("AI director unavailable: %s", exc.message)
                self.director_off = exc.message
                self.log.append(f"AI creative direction skipped: {exc.message}")
                return None
            self._cache_put("director", key, data)
        story = AD.parse_storyboard(data)
        if story is None:
            self.log.append(f"AI storyboard for {spec.family} was unreadable; the offline director planned it.")
            return None
        plan, report = AD.storyboard_to_plan(ctx, request.inventory, request.groups, request.handles, spec.family, spec.seed, story)
        if plan is None:
            self.log.append(f"AI storyboard for {spec.family} did not pass validation ({'; '.join(report[:3])}); the offline director planned it.")
            return None
        log.info("AI director planned %s (%d sections, %d correction(s))", spec.family, len(plan.sections), len(report))
        return plan

    # ------------------------------------------------------------ critique
    def critique(self, presentation, capture_path, purpose_label: str = ""):
        """AI critique of a rendered proposal (None when not allowed/available)."""
        from behance_studio.ai import critique as AC

        if not (self.settings.ai.use_for_evaluation and self.images_allowed) or self.failed:
            return None
        try:
            return AC.critique_presentation(self, presentation, capture_path)
        except (BudgetExceeded, PriceUnknown) as exc:
            self._stop_for_budget(exc)
        except ProviderError as exc:
            log.warning("AI critique failed: %s", exc.message)
            self.log.append(f"AI critique skipped: {exc.message}")
            self.failed = exc.message
        return None

    # --------------------------------------------------------------- costs
    def estimate_generation(self, project, families: list[str], render_previews: bool = True) -> CostEstimate:
        """Expected requests and cost of an AI-assisted generation (before it runs)."""
        from behance_studio.ai import critique as AC
        from behance_studio.ai import director as AD
        from behance_studio.layout.families import is_concept

        ai = self.settings.ai
        est = CostEstimate(self.provider.kind, self.provider.model, self.meter.prices, self.meter.may_bill,
                           run_limit=self.meter.run_limit, monthly_limit=self.meter.monthly_limit,
                           month_spent=self.meter.ledger.month_spent() if self.meter.ledger else 0.0)
        if not self.content_allowed:
            est.notes.append("Nothing will be sent: this project has not allowed AI assistance.")
            return est
        p = self.provider
        assets = [a for a in project.list_assets() if a.is_visual and not a.excluded]
        if ai.use_for_classification and self.images_allowed:
            from behance_studio.ai.vision import PROMPT_VERSION as VISION_VERSION

            todo = [a for a in self._classify_todo(assets)
                    if self._cache_get("classify", self._key("classify", VISION_VERSION, a.sha256, True)) is None]
            sample = p.estimate(CLASSIFY_SYSTEM, "x" * 2600, [ImagePart(b"", "image/jpeg", 640, 480)], 240, purpose="classify")
            est.add("Asset recognition (one preview each)", len(todo), sample)
        brief = project.brief_text or ""
        if ai.use_for_brief and brief.strip() and self._cache_get("brief", self._key("brief", brief)) is None:
            est.add("Brief interpretation", 1, p.estimate(BRIEF_SYSTEM, brief[:6000] + "x" * 700, None, 300, purpose="brief"))
        concepts = [f for f in families if is_concept(f)]
        classic = [f for f in families if not is_concept(f)]
        if getattr(ai, "use_for_direction", True) and concepts:
            n = min(AD.MAX_ASSETS, len(assets))
            shared = "x" * int(5200 + 140 * n + min(len(brief), 5000))
            rows = max(1, -(-n // 6))
            images = [ImagePart(b"", "image/jpeg", 6 * 168, rows * 192)] if self.images_allowed else []
            est.add("Creative direction (one storyboard per concept)", len(concepts),
                    p.estimate(AD.SYSTEM, shared + "x" * 2600, images, AD.ANSWER_TOKENS, effort="medium", purpose="director"))
        if ai.use_for_copywriting:
            sections = len(concepts) + 6 * len(classic)
            est.add("Section descriptions (upper bound; cached drafts are reused)", sections,
                    p.estimate(COPY_SYSTEM, "x" * 2200, None, 160, purpose="copy"))
        if ai.use_for_evaluation and self.images_allowed and render_previews:
            sections = AC.MAX_SECTIONS
            images = [ImagePart(b"", "image/jpeg", AC.SECTION_WIDTH, 330)] * sections
            est.add("Visual critique of rendered proposals", len(families),
                    p.estimate(AC.SYSTEM, "x" * 1800, images, AC.ANSWER_TOKENS, effort="low", purpose="critique"))
        if est.requests and est.prices is not None and est.prices.source != "free":
            est.notes.append("Answers are cached per project: repeating a generation with the same material costs less.")
        return est

    def usage_note(self) -> str:
        return self.meter.summary()


# ---------------------------------------------------------------- schemas
_AXIS = {"anyOf": [{"type": "number"}, {"type": "null"}]}
BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "personality": {"type": "object", "properties": {a: _AXIS for a in AXES}, "required": list(AXES), "additionalProperties": False},
        "mood_words": {"type": "array", "items": {"type": "string"}},
        "tone": {"anyOf": [{"type": "string", "enum": ["light", "dark"]}, {"type": "null"}]},
    },
    "required": ["personality", "mood_words", "tone"],
    "additionalProperties": False,
}
COPY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


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
