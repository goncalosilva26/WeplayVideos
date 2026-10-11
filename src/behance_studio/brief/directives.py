"""Instruction precedence.

1. ``GUIAO_PROJETO.txt`` (script): authoritative for content, order, exact
   text, image assignments and exclusions.
2. ``brief.txt``: artistic direction where it does not conflict with 1.
3. Automatically inferred direction (assets analysis).
4. Default heuristics.

``Directives`` records, for each decision, which level it came from so the UI
can explain it and tests can verify the precedence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from behance_studio.brief.brief import CreativeBrief, parse_brief
from behance_studio.brief.language import detect_language
from behance_studio.brief.script import ProjectScript, ScriptIssue, parse_script, resolve_references
from behance_studio.core.settings import ALL_FAMILIES
from behance_studio.design.category import CATEGORIES, CategoryResult, infer_category
from behance_studio.projects.models import AssetRecord

FAMILY_ALIASES = {
    "editorial": "editorial", "editorial classic": "editorial", "classic": "editorial", "classico": "editorial",
    "cinematic": "cinematic", "cinematic story": "cinematic", "cinematico": "cinematic", "cinema": "cinematic",
    "split": "split", "split narrative": "split", "narrativa dividida": "split", "dividido": "split",
    "posters": "posters", "poster": "posters", "graphic posters": "posters", "cartazes": "posters", "graphic": "posters",
    "gallery": "gallery", "curated gallery": "gallery", "galeria": "gallery", "galeria curada": "gallery",
    "modular": "modular", "modular identity": "modular", "identidade modular": "modular", "system": "modular",
}


@dataclass
class Directives:
    language: str
    category: CategoryResult
    brief: CreativeBrief
    script: ProjectScript | None
    excluded_asset_ids: set[str] = field(default_factory=set)
    families_allowed: list[str] | None = None
    provenance: dict[str, str] = field(default_factory=dict)
    issues: list[ScriptIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def script_locked(self) -> bool:
        return bool(self.script and self.script.has_sections)

    @property
    def strict(self) -> bool:
        return bool(self.script and self.script.has_sections and self.script.strict)

    @property
    def blocking_issues(self) -> list[ScriptIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def project_title(self) -> str | None:
        if self.script and self.script.project_name:
            return self.script.project_name
        return None


def build_directives(
    project_name: str,
    assets: list[AssetRecord],
    brief_text: str = "",
    script_text: str = "",
    project_language: str = "auto",
    category_override: str | None = None,
    default_language: str = "en",
) -> Directives:
    brief = parse_brief(brief_text)
    script = parse_script(script_text) if script_text.strip() else None
    provenance: dict[str, str] = {}
    notes: list[str] = []

    if script is not None:
        script = resolve_references(script, [a for a in assets])

    # --- language ---------------------------------------------------------
    if script and script.language:
        language, provenance["language"] = script.language, "script"
    elif brief.language:
        language, provenance["language"] = brief.language, "brief"
    elif project_language in ("en", "pt"):
        language, provenance["language"] = project_language, "project settings"
    elif script and script.all_text().strip():
        language, provenance["language"] = detect_language(script.all_text(), default_language), "script text"
    else:
        language, provenance["language"] = default_language, "default"

    # --- category -----------------------------------------------------------
    if category_override and category_override in CATEGORIES:
        category = infer_category(assets, explicit=category_override)
        provenance["category"] = "user"
    else:
        explicit_hint = " ".join(filter(None, [script.category if script else None, brief.category_hint]))
        hint = " ".join(filter(None, [brief.about or "", brief.raw[:600]]))
        category = infer_category(assets, hint_text=hint, explicit_hint=explicit_hint)
        if script and script.category:
            provenance["category"] = "script"
        else:
            provenance["category"] = "brief" if category.source == "brief" else "assets"

    # --- exclusions -----------------------------------------------------------
    excluded = {a.id for a in assets if a.excluded}
    if script:
        excluded |= script.excluded_asset_ids
        if script.excluded_asset_ids:
            provenance["exclusions"] = "script"

    # --- families ---------------------------------------------------------------
    families_allowed = None
    if script and script.families:
        resolved = [FAMILY_ALIASES.get(f) for f in script.families]
        families_allowed = [f for f in dict.fromkeys(resolved) if f in ALL_FAMILIES] or None
        if families_allowed:
            provenance["families"] = "script"
        else:
            notes.append("The script's FAMILY entry was not recognised; all layout families are allowed.")

    if brief.about and detect_language(brief.about, language) != language:
        notes.append(
            "The brief's description is written in a different language from the presentation; it is used as guidance only, not as copy."
        )
    notes.extend(brief.font_notes)

    issues = list(script.issues) if script else []
    return Directives(
        language=language,
        category=category,
        brief=brief,
        script=script,
        excluded_asset_ids=excluded,
        families_allowed=families_allowed,
        provenance=provenance,
        issues=issues,
        notes=notes,
    )
