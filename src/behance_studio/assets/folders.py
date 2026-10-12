"""How the designer organised the files: folders → presentation sections.

A professionally organised project already says which images belong
together::

    Butter & Bean/
      01 Logo/…
      02 Brand Elements/…
      03 Packaging/Cups/…   03 Packaging/Bags/…
      04 Campaign/Posters/… 04 Campaign/Outdoor/…
      05 Social Media/…

:func:`build_folder_map` turns that structure into ordered sections:

* the folder that wraps the whole project ("Butter & Bean") is recognised and
  skipped; a single section folder imported on its own still counts;
* numbering is kept for the order ("01 …", "02 …") and removed from titles;
* utility folders ("JPG", "Export", "Final", "Hi-res", "v2") are skipped;
* a broad group folder ("Brand Identity", "Applications") whose subfolders are
  real sections ("Logo", "Stationery") is descended into and kept as a chapter;
* subfolders of a section ("Campaign/Posters") stay inside that section as
  groups.

Folder names are mapped to section types with the same vocabulary the
script parser uses (EN/PT), so "03 Packaging", "Embalagens" and "Packaging
Design" all become Packaging. A folder with a name the app does not know
("Brand in Use") is still a section: it keeps the designer's name.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from behance_studio.planning.sections import section_type_from_name

# Folder names that organise files technically, not by section.
GENERIC_FOLDERS = {
    "assets", "asset", "files", "ficheiros", "arquivos", "jpg", "jpeg", "png", "pdf", "svg", "tif", "tiff", "psd", "ai",
    "eps", "webp", "gif", "export", "exports", "exported", "exportacao", "exportacoes", "final", "finals", "finais", "hi res",
    "hires", "high res", "highres", "low res", "lowres", "web", "print", "impressao", "rgb", "cmyk", "originals", "original",
    "source", "sources", "edited", "editadas", "selects", "selected", "selecao", "seleccao", "new folder", "nova pasta",
    "untitled folder", "misc", "other", "others", "outros", "desktop", "downloads", "documents", "documentos", "pictures",
    "imagens", "onedrive", "dropbox", "google drive", "temp", "tmp", "old", "archive", "arquivo", "backup", "resized",
    "compressed", "optimized", "optimised", "for behance", "behance", "upload", "uploads", "mockup files", "renders",
}
# Folder names that group several sections (descended into when they contain real section folders).
BROAD_NAMES = {
    "brand identity", "identity", "visual identity", "branding", "brand", "identidade", "identidade visual", "marca",
    "deliverables", "entregaveis", "project", "projeto", "projecto", "work", "trabalho", "design", "case study",
    "applications", "aplicacoes", "brand applications", "presentation", "apresentacao",
}
NON_SECTION_TYPES = {"custom", "final", "gallery", "cover", "closing", "intro", "overview", "concept", "creative_direction", "brand_story"}


def _norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[_\-–—.]+", " ", text)
    text = re.sub(r"^\s*(\d+|[a-z](?=\s))\s*[).:]?\s*", "", text)  # leading "01 ", "1. ", "a ) "
    return re.sub(r"\s+", " ", text).strip()


def clean_name(name: str) -> str:
    """Folder name as a section title: numbering and separators removed."""
    text = re.sub(r"^\s*(?:\d+|[A-Za-z](?=\s*[-.)]))\s*[-._)]*\s*", "", name or "")
    if " " not in text and ("_" in text or "-" in text):
        text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s*_+\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_.")
    if not text:
        return (name or "").strip()
    return text.title() if text.islower() else text


# Asset kinds that belong in a folder of each section type (used as a prior
# when guessing an asset's kind; the folder itself decides the section).
_LOGOS = {"logo", "logo_variant", "monogram"}
FOLDER_KINDS: dict[str, set[str]] = {
    "logo": _LOGOS, "logo_variations": _LOGOS, "logo_construction": _LOGOS,
    "palette": {"palette"}, "typography": {"typography"},
    "visual_language": {"pattern", "illustration", "palette", "typography"} | _LOGOS,
    "packaging": {"packaging", "product", "mockup"}, "product": {"product", "packaging", "photo"},
    "campaign": {"poster", "outdoor", "social", "illustration", "editorial"}, "posters": {"poster", "illustration"},
    "outdoor": {"outdoor", "poster"}, "social": {"social"},
    "website": {"website", "mobile", "ui"}, "mobile": {"mobile", "ui", "website"}, "ui_screens": {"ui", "website", "mobile"},
    "photography": {"photo", "lifestyle", "product", "portrait", "before_after"}, "illustration": {"illustration", "poster"},
    "editorial": {"editorial"}, "applications": {"stationery", "mockup", "packaging", "outdoor", "editorial"},
    "mockups": {"mockup", "packaging", "stationery", "product"}, "motion": {"video", "motion"}, "video": {"video", "motion"},
    "before_after": {"before_after"},
}
PRIMARY_KIND = {"logo": "logo", "logo_variations": "logo_variant", "logo_construction": "logo", "palette": "palette",
                "typography": "typography", "visual_language": "pattern", "packaging": "packaging", "product": "product",
                "campaign": "poster", "posters": "poster", "outdoor": "outdoor", "social": "social", "website": "website",
                "mobile": "mobile", "ui_screens": "ui", "photography": "photo", "illustration": "illustration",
                "editorial": "editorial", "applications": "stationery", "mockups": "mockup", "motion": "motion", "video": "video",
                "before_after": "before_after"}


def is_generic(name: str) -> bool:
    norm = _norm(name)
    if not norm:
        return True
    if norm in GENERIC_FOLDERS:
        return True
    return bool(re.fullmatch(r"(v\d+(\s\d+)*|\d{1,4}|\d+x|@\d+x|version \d+|versao \d+)", norm))


def is_broad(name: str) -> bool:
    norm = _norm(name)
    return norm in BROAD_NAMES or any(f" {b} " in f" {norm} " for b in BROAD_NAMES if len(b) > 6)


def section_type_for(name: str) -> str:
    return section_type_from_name(clean_name(name))


def is_specific(name: str) -> bool:
    """Does the folder name clearly name a presentation section?"""
    if is_generic(name) or is_broad(name):
        return False
    return section_type_for(name) not in NON_SECTION_TYPES


def folder_parts(asset) -> list[str]:
    """The asset's folder path as the designer organised it."""
    path = (getattr(asset, "source_folder", "") or getattr(asset, "import_group", "") or "").replace("\\", "/")
    return [p for p in path.split("/") if p.strip() and p not in (".", "..")]


def section_type_of_path(folder: str) -> str | None:
    """Section type named by a folder path (deepest specific folder wins)."""
    parts = [p for p in (folder or "").replace("\\", "/").split("/") if p.strip()]
    for part in reversed(parts):
        if is_specific(part):
            return section_type_for(part)
    return None


# Presentation order for folders the designer did not number.
CANONICAL_ORDER = ["logo", "logo_construction", "logo_variations", "palette", "typography", "visual_language", "illustration",
                   "applications", "packaging", "product", "mockups", "campaign", "posters", "outdoor", "social", "editorial",
                   "website", "mobile", "ui_screens", "photography", "before_after", "motion", "video"]


def _order_key(key: str) -> list:
    """Numbered folders keep their number; others follow the presentation order."""
    out: list = []
    for part in key.split("/"):
        m = re.match(r"\s*(\d+)", part)
        if m:
            out.append((int(m.group(1)), 0, part.lower()))
        else:
            kind = section_type_for(part)
            rank = CANONICAL_ORDER.index(kind) if kind in CANONICAL_ORDER else len(CANONICAL_ORDER)
            out.append((10_000 + rank, 0, part.lower()))
    return out


@dataclass
class FolderSection:
    key: str  # folder path relative to the project root, e.g. "03 Packaging"
    title: str  # designer's name without numbering, e.g. "Packaging"
    type: str  # section type id ("custom" when the name is not a known section)
    order: int = 0
    chapter: str = ""  # broad parent folder, e.g. "Brand Identity"
    specific: bool = True

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "type": self.type, "order": self.order, "chapter": self.chapter}


@dataclass
class FolderMap:
    sections: list[FolderSection] = field(default_factory=list)
    by_asset: dict[str, FolderSection] = field(default_factory=dict)
    subgroup: dict[str, str] = field(default_factory=dict)  # asset id -> subfolder inside its section
    root: str = ""  # wrapper folder that was skipped (project folder)
    organized: bool = False

    def section(self, key: str) -> FolderSection | None:
        return next((s for s in self.sections if s.key == key), None)


def _common_prefix(paths: list[list[str]]) -> list[str]:
    if not paths:
        return []
    prefix = list(paths[0])
    for p in paths[1:]:
        n = 0
        while n < len(prefix) and n < len(p) and prefix[n] == p[n]:
            n += 1
        prefix = prefix[:n]
    return prefix


def _pick_level(rel: list[str]) -> tuple[int, str] | None:
    """Index of the folder that names the section, and its chapter."""
    chapter = ""
    i = 0
    while i < len(rel):
        comp = rel[i]
        if is_generic(comp):
            i += 1
            continue
        deeper = any(is_specific(c) for c in rel[i + 1:])
        if deeper and (is_broad(comp) or not is_specific(comp)):
            chapter = clean_name(comp)
            i += 1
            continue
        return i, chapter
    return None


def build_folder_map(assets) -> FolderMap:
    """Sections defined by the folders of ``assets`` (see module docstring)."""
    fmap = FolderMap()
    items = [(a, folder_parts(a)) for a in assets]
    if not items:
        return fmap
    common = _common_prefix([p for _, p in items])
    if all(len(p) == len(common) for _, p in items) and common:
        keep_from = len(common) - 1  # every file sits in one folder: that folder may itself be the section
    else:
        keep_from = len(common)
    fmap.root = "/".join(common[:keep_from])
    found: dict[str, FolderSection] = {}
    for asset, parts in items:
        rel = parts[keep_from:]
        picked = _pick_level(rel)
        if picked is None:
            continue
        level, chapter = picked
        key = "/".join(rel[: level + 1])
        name = rel[level]
        if key not in found:
            kind = section_type_for(name)
            found[key] = FolderSection(key, clean_name(name), kind, chapter=chapter, specific=is_specific(name))
        fmap.by_asset[asset.id] = found[key]
        sub = [c for c in rel[level + 1:] if not is_generic(c)]
        if sub:
            fmap.subgroup[asset.id] = clean_name(sub[0])
    fmap.sections = sorted(found.values(), key=lambda s: _order_key(s.key))
    for i, s in enumerate(fmap.sections):
        s.order = i
    only = fmap.sections[0] if len(fmap.sections) == 1 else None
    fmap.organized = len(fmap.sections) >= 2 or bool(only and only.specific and not is_broad(only.key.split("/")[-1]))
    return fmap
