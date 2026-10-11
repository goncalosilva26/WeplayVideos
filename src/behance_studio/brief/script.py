"""Parser for the detailed project script (``GUIAO_PROJETO.txt``).

The script is the *authoritative* source for content: section order, exact
titles and text, image assignments and exclusions. The parser never rewrites
user text; it only splits it into fields.

Accepted syntax (keys are case-insensitive, English or Portuguese)::

    PROJECT: Butter & Bean            PROJETO:
    LANGUAGE: en                      IDIOMA: pt
    EXCLUDE: old-logo.png, draft-*    EXCLUIR:
    FAMILY: editorial, cinematic      FAMÍLIA:   (optional)

    ## Cover                          (also: [Cover], == Cover ==, SECTION: Cover,
    TITLE: Butter & Bean               SECÇÃO 1: Capa)
    SUBTITLE: Specialty Coffee. Freshly Baked.
    IMAGES: DSC_0157 shop interior.jpg
    LAYOUT: full-bleed

    ## Introduction
    TEXT:
    Paragraphs are kept exactly as written,
    including line breaks.

    ## Brand Identity
    IMAGES:
    - butter-bean-logo-primary.png | Primary logo
    - butter-bean-monogram.png | Monogram

A JSON file with the same fields (``{"sections": [{"title": ...}]}``) is
also accepted.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable

from behance_studio.brief.language import normalize_language
from behance_studio.planning.sections import SECTION_TYPES, section_type_from_name

# canonical key -> accepted spellings (normalised: no accents, lowercase)
_SECTION_KEYS = {
    "type": ["type", "tipo", "section type", "tipo de seccao"],
    "title": ["title", "titulo", "heading", "cabecalho", "headline"],
    "subtitle": ["subtitle", "subtitulo", "tagline", "slogan", "lead"],
    "eyebrow": ["eyebrow", "label", "etiqueta", "kicker", "antetitulo"],
    "text": ["text", "texto", "body", "copy", "description", "descricao", "conteudo", "content", "paragraph", "paragrafo"],
    "images": ["images", "image", "imagens", "imagem", "assets", "files", "ficheiros", "arquivos", "media", "video", "videos", "photos", "fotos"],
    "captions": ["captions", "caption", "legendas", "legenda"],
    "layout": ["layout", "composition", "composicao", "grid", "grelha", "disposicao"],
    "background": ["background", "fundo", "bg", "background color", "cor de fundo"],
    "notes": ["notes", "notas", "note", "nota", "comments", "comentarios"],
}
_DOC_KEYS = {
    "project": ["project", "projeto", "projecto", "project name", "nome do projeto", "name", "nome"],
    "language": ["language", "idioma", "lingua", "lang"],
    "exclude": ["exclude", "excluir", "exclusions", "exclusoes", "do not use", "nao usar", "ignore", "ignorar"],
    "families": ["family", "families", "familia", "familias", "layout family", "style", "estilo"],
    "strict": ["strict", "estrito", "strict mode", "modo estrito"],
    "client": ["client", "cliente"],
    "year": ["year", "ano"],
    "credits": ["credits", "creditos", "author", "autor", "designer", "team", "equipa"],
    "category": ["category", "categoria", "project type", "tipo de projeto", "discipline", "disciplina"],
    "auto_sections": ["auto sections", "auto_sections", "seccoes automaticas", "allow extra sections", "permitir seccoes extra"],
    "preserve_case": ["preserve case", "preserve_case", "manter maiusculas", "manter capitalizacao"],
}

_KEY_LOOKUP: dict[str, tuple[str, str]] = {}
for _scope, _table in (("section", _SECTION_KEYS), ("doc", _DOC_KEYS)):
    for _canon, _spellings in _table.items():
        for _s in _spellings:
            _KEY_LOOKUP.setdefault(_s, (_scope, _canon))

_SECTION_WORDS = ("section", "seccao", "secao", "seção", "secção", "chapter", "capitulo", "parte", "part")
_YES = {"yes", "y", "true", "sim", "s", "1", "on", "ativo", "activo"}

LAYOUT_HINTS = {
    "full-bleed": ["full-bleed", "full bleed", "fullbleed", "full width", "full-width", "largura total", "sangria", "ecra inteiro", "fullscreen"],
    "single": ["single", "unica", "uma imagem", "one image", "centered", "centrado", "centrada"],
    "two-up": ["two-up", "two up", "pair", "par", "duas", "two images", "side by side", "lado a lado", "dupla", "2 columns", "2 colunas"],
    "grid": ["grid", "grelha", "grade", "mosaic", "mosaico", "masonry", "gallery", "galeria"],
    "split": ["split", "dividido", "dividida", "half", "metade", "text and image", "texto e imagem", "asymmetric", "assimetrico"],
    "text": ["text", "text only", "so texto", "apenas texto", "texto"],
    "hero": ["hero", "destaque", "large", "grande", "big"],
    "carousel": ["sequence", "sequencia", "carousel", "carrossel", "strip", "faixa"],
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace("_", " ").split())


def normalize_layout_hint(value: str | None) -> str | None:
    if not value:
        return None
    v = _norm(value)
    for hint, spellings in LAYOUT_HINTS.items():
        if v == hint or v in spellings:
            return hint
    for hint, spellings in LAYOUT_HINTS.items():
        if any(s in v for s in spellings if len(s) > 3):
            return hint
    return None


@dataclass
class ScriptIssue:
    severity: str  # error | warning | info
    message: str
    line: int | None = None
    section: str | None = None
    ref: str | None = None
    suggestions: list[str] = field(default_factory=list)
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ScriptImage:
    ref: str
    caption: str | None = None
    asset_ids: list[str] = field(default_factory=list)
    line: int | None = None


@dataclass
class ScriptSection:
    index: int
    name: str
    type: str
    title: str | None = None
    subtitle: str | None = None
    eyebrow: str | None = None
    text: str | None = None
    images: list[ScriptImage] = field(default_factory=list)
    captions: dict[str, str] = field(default_factory=dict)  # ref -> caption
    layout: str | None = None
    layout_raw: str | None = None
    background: str | None = None
    notes: str | None = None
    line: int | None = None

    @property
    def display_title(self) -> str:
        return self.title if self.title is not None else self.name


@dataclass
class ProjectScript:
    project_name: str | None = None
    language: str | None = None
    families: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    strict: bool = True
    preserve_case: bool = False
    client: str | None = None
    year: str | None = None
    credits: str | None = None
    category: str | None = None
    sections: list[ScriptSection] = field(default_factory=list)
    issues: list[ScriptIssue] = field(default_factory=list)
    excluded_asset_ids: set[str] = field(default_factory=set)
    source_format: str = "text"

    @property
    def has_sections(self) -> bool:
        return bool(self.sections)

    @property
    def errors(self) -> list[ScriptIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def all_text(self) -> str:
        parts = []
        for s in self.sections:
            parts.extend(p for p in (s.title, s.subtitle, s.text) if p)
        return "\n".join(parts)

    def referenced_asset_ids(self) -> set[str]:
        return {aid for s in self.sections for img in s.images for aid in img.asset_ids}


# --------------------------------------------------------------- parsing
_HEADING_RE = re.compile(r"^\s*(#{2,6})\s*(.+?)\s*#*\s*$")
_BRACKET_RE = re.compile(r"^\s*\[(.+?)\]\s*$")
_EQUALS_RE = re.compile(r"^\s*={2,}\s*(.+?)\s*={2,}\s*$")
_KEY_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 _/\-]{0,40}?)\s*[:：]\s*(.*)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+(.*)$")


def _section_heading(line: str) -> str | None:
    for regex in (_HEADING_RE, _BRACKET_RE, _EQUALS_RE):
        m = regex.match(line)
        if m:
            return m.group(m.lastindex or 1).strip()
    m = _KEY_RE.match(line)
    if m:
        key = _norm(m.group(1))
        if key in _KEY_LOOKUP:  # e.g. "Section type: logo" is a field, not a heading
            return None
        first = key.split()[0] if key else ""
        if first in {_norm(w) for w in _SECTION_WORDS}:
            # "SECTION: Cover", "SECÇÃO 2: Capa", "Section 3 - Packaging"
            name = m.group(2).strip()
            rest = key[len(first):].strip()
            if not name and rest:
                name = rest
            return name or rest or "Section"
    stripped = line.strip()
    m2 = re.match(r"^(?:section|secção|seccao|seção|secao|chapter|capítulo|capitulo)\s+\d+\s*[-–—.]\s*(.+)$", stripped, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None


def _split_list(value: str) -> list[str]:
    parts = re.split(r"\s*[,;]\s*", value.strip())
    return [p.strip().strip('"').strip("'") for p in parts if p.strip()]


def _strip_quotes(value: str) -> str:
    v = value.strip()
    for open_q, close_q in (('"', '"'), ("“", "”"), ("«", "»")):
        if len(v) >= 2 and v.startswith(open_q) and v.endswith(close_q) and v.count(open_q) == (1 if open_q != close_q else 2):
            return v[1:-1]
    return value.strip()


def _parse_image_entry(entry: str, line_no: int) -> ScriptImage:
    caption = None
    for sep in (" | ", "|", " :: ", " — "):
        if sep in entry:
            ref, caption = entry.split(sep, 1)
            return ScriptImage(ref=ref.strip().strip('"'), caption=caption.strip() or None, line=line_no)
    return ScriptImage(ref=entry.strip().strip('"'), caption=None, line=line_no)


def parse_script(text: str) -> ProjectScript:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    if text.strip().startswith("{"):
        try:
            return parse_script_json(json.loads(text))
        except ValueError as exc:
            script = ProjectScript()
            script.issues.append(ScriptIssue("error", f"The script looks like JSON but is not valid: {exc}", code="json"))
            return script

    script = ProjectScript()
    current: ScriptSection | None = None
    block_key: str | None = None  # multi-line field being collected
    block_scope: str | None = None
    block_lines: list[str] = []
    block_line_no = 0

    def flush_block() -> None:
        nonlocal block_key, block_lines, block_scope
        if block_key is None:
            return
        lines = block_lines
        while lines and not lines[0].strip():
            lines = lines[1:]
        while lines and not lines[-1].strip():
            lines = lines[:-1]
        value = "\n".join(lines)
        _assign(script, current, block_scope or "section", block_key, value, block_line_no, multiline=True)
        block_key, block_lines, block_scope = None, [], None

    for line_no, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip()
        # Comments (lines starting with //) are ignored outside text blocks.
        if block_key is None and line.strip().startswith("//"):
            continue
        if line.strip().startswith("# ") and not line.strip().startswith("## ") and current is None and block_key is None:
            continue  # top-level document title
        heading = _section_heading(line)
        if heading is not None and (block_key is None or not _is_plain_text_line(line)):
            flush_block()
            name = heading.strip().strip(":").strip()
            current = ScriptSection(index=len(script.sections), name=name, type=section_type_from_name(name), line=line_no)
            script.sections.append(current)
            continue
        key_match = _KEY_RE.match(line)
        key_info = None
        if key_match:
            key_info = _KEY_LOOKUP.get(_norm(key_match.group(1)))
            if key_info and block_key is not None:
                # Inside a text block only UPPERCASE keys end the block, so
                # sentences like "Note: ..." stay part of the text.
                raw_key = key_match.group(1).strip()
                if raw_key != raw_key.upper():
                    key_info = None
            if key_info and key_info[0] == "doc" and current is not None and key_info[1] not in ("exclude",):
                # a doc-level key name inside a section ("Name:") is treated as text
                if key_info[1] not in ("language",):
                    key_info = None
        if key_info:
            flush_block()
            scope, canon = key_info
            value = key_match.group(2)
            if value.strip() == "" or canon in ("images", "captions") and value.strip() == "":
                block_key, block_scope, block_lines, block_line_no = canon, scope, [], line_no
            else:
                if canon in ("text",) and value.strip() in ('"""', "<<<"):
                    block_key, block_scope, block_lines, block_line_no = canon, scope, [], line_no
                    continue
                _assign(script, current, scope, canon, value, line_no, multiline=False)
            continue
        if block_key is not None:
            if line.strip() in ('"""', ">>>"):
                flush_block()
                continue
            block_lines.append(raw.rstrip("\n"))
            continue
        if line.strip():
            if current is not None and current.text is None:
                # Free text directly under a heading is the section text.
                block_key, block_scope, block_lines, block_line_no = "text", "section", [raw], line_no
            elif current is not None:
                current.text = (current.text + "\n" + raw) if current.text else raw
            else:
                script.issues.append(
                    ScriptIssue("info", f"Line {line_no} is outside any section and was ignored: {line.strip()[:60]}", line=line_no, code="stray")
                )
    flush_block()

    for section in script.sections:
        for ref, caption in section.captions.items():
            for img in section.images:
                if img.ref == ref and not img.caption:
                    img.caption = caption
    _check_structure(script)
    return script


def _is_plain_text_line(line: str) -> bool:
    """Inside a text block, '[x]' or '== x ==' could be literal; '##' is a heading."""
    return not _HEADING_RE.match(line)


def _assign(script: ProjectScript, section: ScriptSection | None, scope: str, key: str, value: str, line_no: int, multiline: bool) -> None:
    if scope == "doc" or section is None:
        if key == "project":
            script.project_name = _strip_quotes(value) or None
        elif key == "language":
            lang = normalize_language(value)
            if lang:
                script.language = lang
            else:
                script.issues.append(ScriptIssue("warning", f"Unknown language '{value.strip()}'. Use EN or PT.", line=line_no, code="language"))
        elif key == "exclude":
            items = []
            for ln in value.split("\n"):
                m = _BULLET_RE.match(ln)
                items.extend(_split_list(m.group(1) if m else ln))
            script.exclude.extend(i for i in items if i)
        elif key == "families":
            script.families = [_norm(f) for f in _split_list(value.replace("\n", ","))]
        elif key == "strict":
            script.strict = _norm(value) in _YES
        elif key == "auto_sections":
            script.strict = _norm(value) not in _YES
        elif key == "preserve_case":
            script.preserve_case = _norm(value) in _YES
        elif key in ("client", "year", "credits", "category"):
            setattr(script, key, _strip_quotes(value) or None)
        elif section is None and scope == "section":
            script.issues.append(
                ScriptIssue("warning", f"'{key.upper()}' appears before any section (line {line_no}); add a section heading such as '## Cover'.", line=line_no, code="orphan_key")
            )
        return

    if key == "type":
        t = _norm(value).replace(" ", "_")
        section.type = t if t in SECTION_TYPES else section_type_from_name(value)
    elif key == "title":
        section.title = value.strip("\n") if multiline else _strip_quotes(value)
    elif key == "subtitle":
        section.subtitle = value.strip("\n") if multiline else _strip_quotes(value)
    elif key == "eyebrow":
        section.eyebrow = _strip_quotes(value)
    elif key == "text":
        section.text = value if multiline else _strip_quotes(value)
    elif key == "images":
        lines = value.split("\n") if multiline else [value]
        for offset, ln in enumerate(lines):
            if not ln.strip():
                continue
            m = _BULLET_RE.match(ln)
            entry = m.group(1) if m else ln
            if m or "|" in entry or not multiline:
                if not m and "|" not in entry and ("," in entry or ";" in entry):
                    for part in _split_list(entry):
                        section.images.append(ScriptImage(ref=part, line=line_no + offset))
                else:
                    section.images.append(_parse_image_entry(entry, line_no + offset))
            else:
                for part in _split_list(entry):
                    section.images.append(ScriptImage(ref=part, line=line_no + offset))
    elif key == "captions":
        lines = value.split("\n") if multiline else [value]
        for ln in lines:
            m = _BULLET_RE.match(ln)
            entry = (m.group(1) if m else ln).strip()
            if not entry:
                continue
            for sep in (" | ", "|", ": ", " = ", " — "):
                if sep in entry:
                    ref, cap = entry.split(sep, 1)
                    section.captions[ref.strip()] = cap.strip()
                    break
    elif key == "layout":
        section.layout_raw = value.strip()
        section.layout = normalize_layout_hint(value)
        if section.layout is None and value.strip():
            script.issues.append(
                ScriptIssue("warning", f"Layout '{value.strip()}' in section '{section.name}' is not recognised; the layout family will decide.", line=line_no, section=section.name, code="layout")
            )
    elif key == "background":
        section.background = value.strip()
    elif key == "notes":
        section.notes = value


def _check_structure(script: ProjectScript) -> None:
    seen: dict[str, int] = {}
    for s in script.sections:
        key = _norm(s.name)
        if key in seen:
            script.issues.append(ScriptIssue("info", f"Section name '{s.name}' is used more than once.", line=s.line, section=s.name, code="dup_section"))
        seen[key] = s.index
        if not (s.title or s.text or s.images or s.subtitle) and s.type not in ("closing", "palette", "typography"):
            script.issues.append(
                ScriptIssue("warning", f"Section '{s.name}' has no title, text or images.", line=s.line, section=s.name, code="empty_section")
            )


def parse_script_json(data: dict[str, Any]) -> ProjectScript:
    script = ProjectScript(source_format="json")
    script.project_name = data.get("project") or data.get("projeto")
    script.language = normalize_language(data.get("language") or data.get("idioma"))
    script.exclude = list(data.get("exclude") or data.get("excluir") or [])
    script.families = [_norm(f) for f in data.get("families", data.get("family", [])) or []] if not isinstance(data.get("family"), str) else [_norm(data["family"])]
    if "strict" in data:
        script.strict = bool(data["strict"])
    for key in ("client", "year", "credits", "category"):
        if data.get(key):
            setattr(script, key, str(data[key]))
    for index, item in enumerate(data.get("sections") or data.get("seccoes") or []):
        name = item.get("name") or item.get("title") or item.get("type") or f"Section {index + 1}"
        section = ScriptSection(index=index, name=name, type=item.get("type") or section_type_from_name(name))
        if section.type not in SECTION_TYPES:
            section.type = section_type_from_name(section.type)
        section.title = item.get("title")
        section.subtitle = item.get("subtitle")
        section.eyebrow = item.get("eyebrow")
        section.text = item.get("text")
        section.layout_raw = item.get("layout")
        section.layout = normalize_layout_hint(item.get("layout"))
        section.background = item.get("background")
        for img in item.get("images") or []:
            if isinstance(img, str):
                section.images.append(_parse_image_entry(img, 0))
            elif isinstance(img, dict) and img.get("file"):
                section.images.append(ScriptImage(ref=img["file"], caption=img.get("caption")))
        script.sections.append(section)
    _check_structure(script)
    return script


# ----------------------------------------------------- reference resolution
def _ref_norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip().lower().replace("\\", "/")


def resolve_references(script: ProjectScript, assets: Iterable[Any]) -> ProjectScript:
    """Match file references to project assets.

    Never guesses: a missing or ambiguous reference produces an error issue
    with suggestions, and the section simply does not receive that image.
    """
    assets = [a for a in assets]
    by_name: dict[str, list[Any]] = {}
    by_stem: dict[str, list[Any]] = {}
    by_path: dict[str, Any] = {}
    for a in assets:
        by_name.setdefault(_ref_norm(a.filename), []).append(a)
        by_stem.setdefault(_ref_norm(a.filename.rsplit(".", 1)[0]), []).append(a)
        rel = _ref_norm(a.rel_path)
        by_path[rel] = a
        if rel.startswith("assets/"):
            by_path[rel[len("assets/"):]] = a
        if a.import_group:
            by_path[_ref_norm(f"{a.import_group}/{a.filename}")] = a
    all_names = [a.filename for a in assets]

    def match(ref: str) -> tuple[list[Any], str]:
        norm = _ref_norm(ref)
        if any(ch in norm for ch in "*?["):
            hits = [a for a in assets if fnmatch.fnmatch(_ref_norm(a.filename), norm) or fnmatch.fnmatch(_ref_norm(a.rel_path), norm) or fnmatch.fnmatch(_ref_norm(a.rel_path), "assets/" + norm)]
            return hits, "pattern"
        if norm in by_path:
            return [by_path[norm]], "path"
        if norm in by_name:
            return by_name[norm], "name"
        base = PurePosixPath(norm).name
        if base in by_name and "/" in norm:
            return by_name[base], "name"
        if norm in by_stem:
            return by_stem[norm], "stem"
        return [], "none"

    excluded: set[str] = set()
    for pattern in script.exclude:
        hits, _how = match(pattern)
        if not hits:
            script.issues.append(ScriptIssue("info", f"EXCLUDE entry '{pattern}' does not match any asset.", ref=pattern, code="exclude_unmatched"))
        excluded.update(a.id for a in hits)
    script.excluded_asset_ids = excluded

    for section in script.sections:
        for img in section.images:
            hits, how = match(img.ref)
            if not hits:
                suggestions = difflib.get_close_matches(img.ref, all_names, n=3, cutoff=0.5)
                script.issues.append(
                    ScriptIssue(
                        "error",
                        f"Section '{section.name}': the file '{img.ref}' was not found among the imported assets.",
                        line=img.line,
                        section=section.name,
                        ref=img.ref,
                        suggestions=suggestions,
                        code="missing_ref",
                    )
                )
                continue
            if how != "pattern" and len(hits) > 1:
                script.issues.append(
                    ScriptIssue(
                        "error",
                        f"Section '{section.name}': '{img.ref}' matches {len(hits)} files. Use the folder path to choose one.",
                        line=img.line,
                        section=section.name,
                        ref=img.ref,
                        suggestions=[h.rel_path for h in hits],
                        code="ambiguous_ref",
                    )
                )
                continue
            usable = [h for h in hits if h.id not in excluded]
            if len(usable) < len(hits):
                script.issues.append(
                    ScriptIssue("warning", f"Section '{section.name}': '{img.ref}' is also listed in EXCLUDE; the exclusion wins.", section=section.name, ref=img.ref, code="ref_excluded")
                )
            bad = [h for h in usable if getattr(h, "status", "ok") != "ok"]
            for h in bad:
                script.issues.append(
                    ScriptIssue("error", f"Section '{section.name}': the file '{h.filename}' is {h.status}.", section=section.name, ref=img.ref, code="ref_unusable")
                )
            img.asset_ids = [h.id for h in usable if getattr(h, "status", "ok") == "ok"]
    return script


def apply_resolution(script: ProjectScript, ref: str, asset_id: str) -> None:
    """Explicit user choice for a missing/ambiguous reference."""
    for section in script.sections:
        for img in section.images:
            if img.ref == ref:
                img.asset_ids = [asset_id]
    script.issues = [i for i in script.issues if not (i.ref == ref and i.code in ("missing_ref", "ambiguous_ref"))]


SCRIPT_TEMPLATE_EN = """# PROJECT SCRIPT — {name}
# Lines starting with // are comments. Keys can be written in English or Portuguese.
PROJECT: {name}
LANGUAGE: en
// EXCLUDE: draft-*.jpg, old-logo.png

## Cover
TITLE: {name}
SUBTITLE: A short line that introduces the project
// IMAGES: hero-image.jpg
// LAYOUT: full-bleed

## Introduction
TEXT:
Write the introduction exactly as it should appear.
Paragraph breaks are preserved.

## Brand Identity
// IMAGES:
// - logo-primary.png | Primary logo
// - logo-secondary.png | Secondary logo

## Closing
TITLE: Thank you
"""

SCRIPT_TEMPLATE_PT = """# GUIÃO DO PROJETO — {name}
# Linhas começadas por // são comentários. As chaves podem ser em português ou inglês.
PROJETO: {name}
IDIOMA: pt
// EXCLUIR: rascunho-*.jpg, logo-antigo.png

## Capa
TÍTULO: {name}
SUBTÍTULO: Uma frase curta que apresenta o projeto
// IMAGENS: imagem-principal.jpg
// COMPOSIÇÃO: largura total

## Introdução
TEXTO:
Escreva a introdução exatamente como deve aparecer.
As mudanças de parágrafo são mantidas.

## Identidade Visual
// IMAGENS:
// - logotipo-principal.png | Logótipo principal
// - logotipo-secundario.png | Logótipo secundário

## Encerramento
TÍTULO: Obrigado
"""


def script_template(name: str, language: str = "en") -> str:
    return (SCRIPT_TEMPLATE_PT if language == "pt" else SCRIPT_TEMPLATE_EN).format(name=name)
