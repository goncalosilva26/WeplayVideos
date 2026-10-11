"""Creative brief interpretation (``brief.txt``).

The brief guides *artistic treatment*: personality, mood, colours, fonts,
audience, preferred presentation style. It is free text, so parsing is
tolerant: known "Key: value" fields are read when present, and keywords are
detected anywhere (English and Portuguese, with negation such as "premium
without feeling overly luxurious" and intensity such as "slightly playful").

User-authored sentences (the "About" description and quoted brand messages)
are kept verbatim so they can be used as presentation copy.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from behance_studio.brief.language import detect_language, normalize_language
from behance_studio.design.color import NAMED_COLORS, normalize_hex, parse_color
from behance_studio.design.typography import AXES, find_font_mentions

FIELD_ALIASES = {
    "project": ["project", "projeto", "projecto", "project name", "nome", "name", "brand", "marca", "client", "cliente"],
    "type": ["type", "tipo", "project type", "tipo de projeto", "category", "categoria", "discipline", "disciplina"],
    "about": ["about", "sobre", "description", "descricao", "overview", "summary", "resumo", "context", "contexto", "intro", "introduction", "introducao", "project purpose", "purpose", "objetivo", "objective"],
    "audience": ["audience", "target audience", "publico", "publico alvo", "target", "alvo"],
    "personality": ["personality", "brand personality", "personalidade", "personalidade da marca", "character", "brand character", "caracter", "tone", "tom", "tone of voice"],
    "mood": ["mood", "visual mood", "ambiente", "atmosfera", "atmosphere", "feel", "look and feel", "estilo", "style"],
    "messages": ["messages", "brand messages", "mensagens", "taglines", "tagline", "slogans", "slogan", "claims", "claim", "headline", "headlines"],
    "colors": ["colours", "colors", "colour", "color", "cores", "cor", "palette", "paleta", "brand colours", "brand colors"],
    "typography": ["typography", "tipografia", "fonts", "fontes", "typefaces", "type", "fonte"],
    "language": ["language", "idioma", "lingua"],
    "constraints": ["constraints", "restricoes", "restrictions", "avoid", "evitar", "do not", "nao", "rules", "regras"],
    "priorities": ["priorities", "prioridades", "focus", "foco", "emphasis", "enfase", "presentation priorities"],
    "references": ["references", "referencias", "inspiration", "inspiracao"],
    "storytelling": ["storytelling", "narrative", "narrativa", "story", "historia", "preferred storytelling style"],
}

# keyword → (axis, direction). Multi-word phrases first.
MOOD_LEXICON: list[tuple[str, str, float]] = [
    # warmth
    ("warm", "warmth", 1), ("quente", "warmth", 1), ("acolhedor", "warmth", 0.8), ("acolhedora", "warmth", 0.8), ("welcoming", "warmth", 0.8),
    ("cozy", "warmth", 0.9), ("cosy", "warmth", 0.9), ("inviting", "warmth", 0.7), ("friendly", "warmth", 0.5), ("amigavel", "warmth", 0.5),
    ("cool", "warmth", -0.8), ("cold", "warmth", -1), ("frio", "warmth", -1), ("fria", "warmth", -1), ("fresh", "warmth", -0.3), ("clinical", "warmth", -0.8), ("icy", "warmth", -1),
    # energy
    ("playful", "energy", 1), ("ludico", "energy", 1), ("ludica", "energy", 1), ("divertido", "energy", 1), ("divertida", "energy", 1), ("fun", "energy", 0.9),
    ("youthful", "energy", 0.8), ("jovem", "energy", 0.8), ("vibrant", "energy", 0.9), ("vibrante", "energy", 0.9), ("energetic", "energy", 1), ("energetico", "energy", 1),
    ("dynamic", "energy", 0.7), ("dinamico", "energy", 0.7), ("dinamica", "energy", 0.7), ("lively", "energy", 0.8), ("approachable", "energy", 0.3),
    ("calm", "energy", -0.9), ("calmo", "energy", -0.9), ("calma", "energy", -0.9), ("serene", "energy", -0.9), ("sereno", "energy", -0.9), ("quiet", "energy", -0.7),
    ("minimal", "energy", -0.5), ("minimalist", "energy", -0.6), ("minimalista", "energy", -0.6), ("restrained", "energy", -0.6), ("contido", "energy", -0.6), ("serious", "energy", -0.7), ("serio", "energy", -0.7),
    # refinement
    ("luxury", "refinement", 1), ("luxurious", "refinement", 1), ("luxo", "refinement", 1), ("luxuoso", "refinement", 1), ("premium", "refinement", 0.8),
    ("elegant", "refinement", 0.9), ("elegante", "refinement", 0.9), ("refined", "refinement", 0.9), ("refinado", "refinement", 0.9), ("sophisticated", "refinement", 0.9),
    ("sofisticado", "refinement", 0.9), ("sofisticada", "refinement", 0.9), ("exclusive", "refinement", 0.8), ("exclusivo", "refinement", 0.8), ("high end", "refinement", 1), ("upscale", "refinement", 0.8),
    ("approachable", "refinement", -0.3), ("accessible", "refinement", -0.4), ("acessivel", "refinement", -0.4), ("casual", "refinement", -0.7), ("informal", "refinement", -0.6),
    ("everyday", "refinement", -0.5), ("affordable", "refinement", -0.6), ("down to earth", "refinement", -0.5), ("unpretentious", "refinement", -0.5),
    # boldness
    ("bold", "boldness", 1), ("arrojado", "boldness", 1), ("ousado", "boldness", 1), ("ousada", "boldness", 1), ("strong", "boldness", 0.7), ("forte", "boldness", 0.7),
    ("impactful", "boldness", 0.9), ("impactante", "boldness", 0.9), ("expressive", "boldness", 0.8), ("expressivo", "boldness", 0.8), ("expressiva", "boldness", 0.8),
    ("loud", "boldness", 0.9), ("striking", "boldness", 0.8), ("confident", "boldness", 0.5), ("confiante", "boldness", 0.5), ("graphic", "boldness", 0.5),
    ("subtle", "boldness", -0.8), ("subtil", "boldness", -0.8), ("sutil", "boldness", -0.8), ("delicate", "boldness", -0.8), ("delicado", "boldness", -0.8), ("delicada", "boldness", -0.8),
    ("soft", "boldness", -0.6), ("suave", "boldness", -0.6), ("gentle", "boldness", -0.6), ("understated", "boldness", -0.8), ("discreet", "boldness", -0.7), ("discreto", "boldness", -0.7),
    # modernity
    ("contemporary", "modernity", 0.8), ("contemporaneo", "modernity", 0.8), ("contemporanea", "modernity", 0.8), ("modern", "modernity", 0.8), ("moderno", "modernity", 0.8), ("moderna", "modernity", 0.8),
    ("tech", "modernity", 1), ("technology", "modernity", 1), ("tecnologia", "modernity", 1), ("digital", "modernity", 0.8), ("futuristic", "modernity", 1), ("futurista", "modernity", 1), ("innovative", "modernity", 0.7), ("inovador", "modernity", 0.7),
    ("classic", "modernity", -0.8), ("classico", "modernity", -0.8), ("classica", "modernity", -0.8), ("heritage", "modernity", -0.9), ("tradition", "modernity", -0.8),
    ("traditional", "modernity", -0.9), ("tradicional", "modernity", -0.9), ("vintage", "modernity", -1), ("retro", "modernity", -0.9), ("timeless", "modernity", -0.5), ("intemporal", "modernity", -0.5), ("nostalgic", "modernity", -0.8),
    # organic
    ("organic", "organic", 1), ("organico", "organic", 1), ("organica", "organic", 1), ("natural", "organic", 0.8), ("handmade", "organic", 1), ("artesanal", "organic", 1),
    ("handcrafted", "organic", 1), ("craft", "organic", 0.8), ("artisan", "organic", 0.9), ("rustic", "organic", 0.8), ("rustico", "organic", 0.8), ("earthy", "organic", 0.7), ("sustainable", "organic", 0.5),
    ("geometric", "organic", -1), ("geometrico", "organic", -1), ("geometrica", "organic", -1), ("structured", "organic", -0.7), ("estruturado", "organic", -0.7),
    ("systematic", "organic", -0.8), ("sistematico", "organic", -0.8), ("precise", "organic", -0.7), ("preciso", "organic", -0.7), ("technical", "organic", -0.8), ("tecnico", "organic", -0.8), ("modular", "organic", -0.7),
]

FAMILY_HINTS = {
    "editorial": ["editorial", "magazine", "revista", "elegant grid", "clean grid"],
    "cinematic": ["cinematic", "cinematico", "cinematografico", "film", "immersive", "imersivo", "dramatic", "dramatico"],
    "split": ["split", "asymmetric", "assimetrico", "case study", "caso de estudo", "storytelling"],
    "posters": ["poster", "posters", "cartaz", "bold typography", "tipografia expressiva", "expressive typography", "experimental"],
    "gallery": ["gallery", "galeria", "museum", "museu", "curated", "curado", "art", "arte"],
    "modular": ["modular", "system", "sistema", "grid system", "bento", "design system", "sistema de design"],
}

TONE_HINTS = {
    "dark": ["dark", "escuro", "escura", "moody", "noir", "night", "noite", "black background", "fundo preto", "fundo escuro"],
    "light": ["light", "claro", "clara", "airy", "bright", "luminoso", "luminosa", "white background", "fundo branco", "fundo claro"],
}

_NEGATORS = {"not", "no", "without", "never", "sem", "nao", "nem", "nunca", "avoid", "evitar", "less", "menos", "neither", "nor"}
_SOFTENERS = {"slightly": 0.5, "somewhat": 0.6, "a bit": 0.5, "a little": 0.5, "ligeiramente": 0.5, "um pouco": 0.5, "subtly": 0.5, "moderately": 0.7}
_BOOSTERS = {"very": 1.4, "extremely": 1.6, "highly": 1.4, "muito": 1.4, "bastante": 1.3, "really": 1.3, "super": 1.5, "overly": 1.3}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return text


@dataclass
class BrandColor:
    hex: str
    name: str | None = None
    source: str = "brief"  # brief (exact value) | brief-name (from colour name)


@dataclass
class CreativeBrief:
    raw: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    project: str | None = None
    category_hint: str | None = None
    about: str | None = None
    audience: str | None = None
    messages: list[str] = field(default_factory=list)
    colors: list[BrandColor] = field(default_factory=list)
    display_font: str | None = None
    text_font: str | None = None
    font_notes: list[str] = field(default_factory=list)
    language: str | None = None
    text_language: str = "en"
    personality: dict[str, float] = field(default_factory=dict)
    mood_words: list[str] = field(default_factory=list)
    family_preferences: list[str] = field(default_factory=list)
    tone: str | None = None  # dark | light
    constraints: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.raw.strip()

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["colors"] = [c.__dict__ for c in self.colors]
        return data


_FIELD_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ /&\-]{1,40}?)\s*[:：]\s*(.*)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+(.*)$")


def _field_for(key: str) -> str | None:
    k = " ".join(_norm(key).replace("&", " ").split())
    for canon, aliases in FIELD_ALIASES.items():
        if k in aliases:
            return canon
    return None


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _FIELD_RE.match(line)
        canon = _field_for(m.group(1)) if m else None
        if m and canon:
            current = canon
            value = m.group(2).strip()
            fields.setdefault(canon, [])
            if value:
                fields[canon].append(value)
            continue
        if not line.strip():
            current = None if current not in ("messages", "colors") else current
            continue
        if current:
            b = _BULLET_RE.match(line)
            fields[current].append((b.group(1) if b else line).strip())
    return {k: "\n".join(v).strip() for k, v in fields.items()}


def _extract_messages(text: str, fields: dict[str, str]) -> list[str]:
    messages: list[str] = []
    source = fields.get("messages", "")
    pattern = r"[\"“«]([^\"”»]{3,140})[\"”»]"
    for m in re.finditer(pattern, source):
        messages.append(m.group(1).strip())
    if not messages and source:
        for line in source.split("\n"):
            line = line.strip().strip("-•* ").strip()
            if 2 < len(line) <= 140:
                messages.append(line.strip('"“”'))
    if not messages:
        for m in re.finditer(pattern, text):
            candidate = m.group(1).strip()
            if 2 < len(candidate) <= 100:
                messages.append(candidate)
    seen: set[str] = set()
    out = []
    for msg in messages:
        if msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out[:8]


def _extract_colors(text: str, fields: dict[str, str]) -> list[BrandColor]:
    colors: list[BrandColor] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?:([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\- ]{1,24}?)\s*[:=\-–(]?\s*)?(#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b)", text):
        hexv = normalize_hex(m.group(2))
        if not hexv or hexv in seen:
            continue
        name = (m.group(1) or "").strip(" :-–(").strip()
        name_words = name.split()
        if name_words:
            name = name_words[-1] if len(name_words) > 2 else name
        if name and _norm(name) in {"colours", "colors", "cores", "palette", "paleta", "color", "colour", "cor", "and", "e"}:
            name = ""
        seen.add(hexv)
        colors.append(BrandColor(hex=hexv, name=name.title() if name and name.islower() else (name or None), source="brief"))
    for m in re.finditer(r"rgb\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)", text, re.I):
        hexv = parse_color(m.group(0))
        if hexv and hexv not in seen:
            seen.add(hexv)
            colors.append(BrandColor(hex=hexv, source="brief"))
    if not colors and fields.get("colors"):
        norm = " " + _norm(fields["colors"]) + " "
        for name in sorted(NAMED_COLORS, key=len, reverse=True):
            if f" {name} " in norm:
                hexv = NAMED_COLORS[name]
                if hexv not in seen:
                    seen.add(hexv)
                    colors.append(BrandColor(hex=hexv, name=name.title(), source="brief-name"))
                norm = norm.replace(f" {name} ", " ")
    return colors


def _personality(text: str) -> tuple[dict[str, float], list[str]]:
    norm = _norm(text)
    tokens = re.findall(r"[a-z]+", norm)
    joined = " " + " ".join(tokens) + " "
    totals = {a: 0.0 for a in AXES}
    counts = {a: 0 for a in AXES}
    words: list[str] = []
    for phrase, axis, direction in sorted(MOOD_LEXICON, key=lambda x: -len(x[0])):
        start = 0
        while True:
            idx = joined.find(f" {phrase} ", start)
            if idx < 0:
                break
            start = idx + len(phrase) + 1
            prefix = joined[:idx].split()[-4:]
            weight = 1.0
            if any(p in _NEGATORS for p in prefix):
                weight = -0.6
            prefix_text = " ".join(prefix[-2:])
            for soft, factor in _SOFTENERS.items():
                if prefix_text.endswith(soft) or (prefix and prefix[-1] == soft):
                    weight *= factor
            for boost, factor in _BOOSTERS.items():
                if prefix and prefix[-1] == boost and weight > 0:
                    weight *= factor
            # "overly luxurious" after a negator is a moderated rejection
            totals[axis] += direction * weight
            counts[axis] += 1
            if weight > 0 and phrase not in words:
                words.append(phrase)
    personality = {}
    for axis in AXES:
        if counts[axis]:
            value = totals[axis] / max(1.0, counts[axis] ** 0.5)
            personality[axis] = round(max(-1.0, min(1.0, value)), 3)
    return personality, words


def parse_brief(text: str) -> CreativeBrief:
    text = (text or "").replace("\r\n", "\n").lstrip("﻿")
    brief = CreativeBrief(raw=text)
    if not text.strip():
        return brief
    fields = _parse_fields(text)
    brief.fields = fields
    brief.project = (fields.get("project") or "").split("\n")[0].strip() or None
    brief.category_hint = fields.get("type")
    brief.about = fields.get("about")
    brief.audience = fields.get("audience")
    brief.constraints = fields.get("constraints")
    brief.messages = _extract_messages(text, fields)
    brief.colors = _extract_colors(fields.get("colors") or text, fields) or _extract_colors(text, {})
    lang_field = fields.get("language")
    brief.language = normalize_language(lang_field) if lang_field else None
    brief.text_language = detect_language(text)

    mentions = find_font_mentions(fields.get("typography") or text)
    display = next((m for m in mentions if m.role == "display"), None)
    body = next((m for m in mentions if m.role == "text"), None)
    unassigned = [m for m in mentions if m.role is None]
    if display is None and unassigned:
        display = unassigned.pop(0)
    if body is None and unassigned:
        body = unassigned.pop(0)
    if display is None and body is not None and len(mentions) == 1:
        display = body
    for m, role in ((display, "display"), (body, "text")):
        if m is None:
            continue
        if role == "display":
            brief.display_font = m.family
        else:
            brief.text_font = m.family
        if m.substituted:
            brief.font_notes.append(
                f"'{m.requested.title()}' is not bundled; '{m.family}' is used as the closest available alternative for {role} text."
            )

    personality_source = " ".join(
        v for k, v in fields.items() if k in ("personality", "mood", "storytelling", "priorities", "type", "about")
    ) or text
    brief.personality, brief.mood_words = _personality(personality_source)
    if not brief.personality:
        brief.personality, brief.mood_words = _personality(text)

    norm_all = " " + " ".join(re.findall(r"[a-z]+", _norm(text))) + " "
    for family, hints in FAMILY_HINTS.items():
        if any(f" {h} " in norm_all for h in hints):
            brief.family_preferences.append(family)
    dark = sum(norm_all.count(f" {h} ") for h in TONE_HINTS["dark"])
    light = sum(norm_all.count(f" {h} ") for h in TONE_HINTS["light"])
    if dark > light:
        brief.tone = "dark"
    elif light > dark:
        brief.tone = "light"
    return brief
