"""Project category inference from the asset mix and the brief/script."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from behance_studio.projects.models import LOGO_KINDS, PHOTO_KINDS, UI_KINDS, AssetRecord

CATEGORIES: dict[str, tuple[str, str]] = {
    "brand_identity": ("Brand Identity", "Identidade Visual"),
    "logo_design": ("Logo Design", "Design de Logótipo"),
    "graphic_design": ("Graphic Design", "Design Gráfico"),
    "advertising": ("Advertising Campaign", "Campanha Publicitária"),
    "social_media": ("Social Media Design", "Design para Redes Sociais"),
    "packaging": ("Packaging Design", "Design de Embalagem"),
    "product": ("Product Design", "Design de Produto"),
    "photography": ("Photography", "Fotografia"),
    "retouching": ("Photo Retouching", "Retoque Fotográfico"),
    "motion": ("Motion Graphics", "Motion Graphics"),
    "video": ("Video Production", "Produção de Vídeo"),
    "multimedia": ("Multimedia Design", "Design Multimédia"),
    "editorial": ("Editorial Design", "Design Editorial"),
    "illustration": ("Illustration", "Ilustração"),
    "ui_ux": ("UI/UX Design", "Design UI/UX"),
    "website": ("Website Design", "Design de Website"),
    "app": ("App Design", "Design de Aplicação"),
    "typography": ("Typography", "Tipografia"),
    "campaign": ("Creative Campaign", "Campanha Criativa"),
    "mixed": ("Mixed-Discipline Project", "Projeto Multidisciplinar"),
}

BRIEF_KEYWORDS: dict[str, list[str]] = {
    "brand_identity": ["brand identity", "branding", "visual identity", "identidade visual", "identidade de marca", "rebrand", "rebranding", "brand system"],
    "logo_design": ["logo design", "logotipo", "logo", "logotype", "wordmark"],
    "graphic_design": ["graphic design", "design grafico"],
    "advertising": ["advertising", "publicidade", "ad campaign", "advertising campaign", "campanha publicitaria", "ads"],
    "social_media": ["social media", "redes sociais", "instagram", "content design"],
    "packaging": ["packaging", "embalagem", "embalagens", "label design", "rotulo"],
    "product": ["product design", "design de produto", "industrial design"],
    "photography": ["photography", "fotografia", "photo shoot", "photoshoot", "sessao fotografica"],
    "retouching": ["retouch", "retouching", "retoque", "photo editing", "edicao fotografica", "compositing"],
    "motion": ["motion", "motion graphics", "animation", "animacao"],
    "video": ["video", "film", "filme", "video production", "producao de video"],
    "multimedia": ["multimedia", "multimedia design"],
    "editorial": ["editorial", "magazine", "revista", "book design", "livro", "publication", "publicacao"],
    "illustration": ["illustration", "ilustracao"],
    "ui_ux": ["ui/ux", "ui ux", "ux", "user interface", "interface design", "product design system", "design system"],
    "website": ["website", "web design", "site", "landing page"],
    "app": ["app design", "mobile app", "aplicacao movel", "app", "ios", "android"],
    "typography": ["typeface", "type design", "typography project", "tipografia", "font design"],
    "campaign": ["campaign", "campanha", "launch", "lancamento"],
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " " + " ".join(re.findall(r"[a-z0-9/]+", text)) + " "


@dataclass
class CategoryResult:
    category: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    source: str = "assets"  # assets | brief | script | user

    def label(self, language: str = "en") -> str:
        en, pt = CATEGORIES.get(self.category, CATEGORIES["mixed"])
        return pt if language == "pt" else en


def infer_category(
    assets: list[AssetRecord],
    hint_text: str = "",
    explicit: str | None = None,
    explicit_hint: str = "",
) -> CategoryResult:
    """``explicit_hint`` is a stated project type (brief "Type:" / script
    "CATEGORY:") and outweighs what the assets suggest; ``hint_text`` is
    general prose that only nudges the estimate."""
    if explicit and explicit in CATEGORIES:
        return CategoryResult(explicit, 1.0, {explicit: 1.0}, ["set by the user"], "user")
    usable = [a for a in assets if a.is_visual and not a.excluded and a.effective_kind != "reference"]
    counts = Counter(a.effective_kind for a in usable)
    total = max(1, sum(counts.values()))

    def frac(kinds) -> float:
        return sum(counts.get(k, 0) for k in kinds) / total

    logos = frac(LOGO_KINDS)
    identity_elems = frac({"palette", "typography", "pattern"})
    applications = frac({"packaging", "stationery", "mockup", "social", "poster", "outdoor", "editorial"})
    application_kinds = sum(1 for k in ("packaging", "stationery", "mockup", "social", "poster", "outdoor", "editorial") if counts.get(k))
    photos = frac(PHOTO_KINDS)
    scores: dict[str, float] = {}
    reasons: list[str] = []
    if logos > 0:
        scores["brand_identity"] = 0.35 + min(0.3, identity_elems * 2) + min(0.3, application_kinds * 0.08) + (0.1 if logos >= 0.05 else 0)
        scores["logo_design"] = 0.2 + logos * 1.2 - application_kinds * 0.08
        reasons.append(f"{counts.get('logo', 0) + counts.get('monogram', 0) + counts.get('logo_variant', 0)} logo file(s)")
    scores["packaging"] = frac({"packaging"}) * 1.6 + frac({"product"}) * 0.4
    scores["advertising"] = frac({"poster", "outdoor"}) * 1.4 + frac({"social"}) * 0.3
    scores["social_media"] = frac({"social"}) * 1.5
    scores["campaign"] = (frac({"poster", "outdoor", "social", "video"}) * 0.9) if application_kinds >= 2 else 0
    scores["photography"] = photos * 1.1 - logos * 2 - applications
    scores["retouching"] = frac({"before_after"}) * 2.2
    scores["motion"] = frac({"motion"}) * 1.6 + frac({"video"}) * 0.6
    scores["video"] = frac({"video"}) * 1.5
    scores["illustration"] = frac({"illustration"}) * 1.5
    scores["ui_ux"] = frac(UI_KINDS) * 1.2
    scores["website"] = frac({"website"}) * 1.4
    scores["app"] = frac({"mobile"}) * 1.4
    scores["typography"] = frac({"typography"}) * 1.5 - logos
    scores["editorial"] = frac({"editorial"}) * 1.5
    distinct = sum(1 for k, c in counts.items() if c)
    scores["mixed"] = 0.15 + (0.1 if distinct >= 6 else 0)

    source = "assets"
    for text, strong in ((explicit_hint, True), (hint_text, False)):
        hint = _norm(text)
        if not hint.strip():
            continue
        for cat, words in BRIEF_KEYWORDS.items():
            for w in words:
                if f" {w} " in hint:
                    boost = (2.0 if len(w) > 4 else 1.2) if strong else (0.6 if len(w) > 4 else 0.35)
                    scores[cat] = scores.get(cat, 0) + boost
                    reasons.append(f"{'project type' if strong else 'brief'} mentions '{w}'")
                    source = "brief"
                    break
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, value = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    confidence = max(0.1, min(0.95, 0.4 + (value - second)))
    if not usable and not (hint_text.strip() or explicit_hint.strip()):
        return CategoryResult("mixed", 0.1, {}, ["no assets"], "assets")
    return CategoryResult(best, round(confidence, 3), {k: round(v, 3) for k, v in ranked[:6]}, reasons[:6], source)
