"""Heuristic (non-AI) asset classification.

Combines two honest signals:

1. Words in file and folder names (English and Portuguese), which designers
   very often use ("logo-primary.png", "Embalagem/caixa.jpg").
2. Measured visual features from :mod:`analysis` (transparency, flatness,
   colour count, aspect ratio, swatch-like regions, faces...).

The result is an *estimate* with a confidence value and the reasons that led
to it. The UI labels it as such and the user can override it; an optional AI
provider can replace it with a multimodal classification.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from behance_studio.projects.models import MEDIA_GIF, MEDIA_SVG, MEDIA_VIDEO

KEYWORDS: dict[str, list[str]] = {
    "logo": ["logo", "logos", "logotipo", "logotype", "logomark", "wordmark", "brandmark", "marca", "lockup", "logotipos"],
    "logo_variant": ["variant", "variants", "variation", "variations", "alt", "alternative", "alternativo", "alternativa",
                      "secondary", "secundario", "negative", "negativo", "mono", "monochrome", "inverse", "inverted",
                      "reverse", "horizontal", "vertical", "stacked", "versao", "versoes", "reduced", "reduzido"],
    "monogram": ["monogram", "monograma", "symbol", "simbolo", "isotipo", "isotype", "favicon", "emblem", "emblema", "seal", "selo", "badge"],
    "palette": ["palette", "paleta", "colors", "colours", "cores", "color", "colour", "swatch", "swatches", "cromatica"],
    "typography": ["typography", "tipografia", "typeface", "typefaces", "font", "fonts", "fonte", "fontes", "specimen", "type"],
    "pattern": ["pattern", "patterns", "padrao", "padroes", "texture", "textura", "grafismo", "grafismos", "element", "elements", "elemento", "elementos", "shapes", "formas"],
    "illustration": ["illustration", "illustrations", "ilustracao", "ilustracoes", "drawing", "desenho", "artwork", "sketch", "esboco", "character", "personagem"],
    "packaging": ["packaging", "package", "pack", "embalagem", "embalagens", "box", "caixa", "bag", "saco", "label", "rotulo", "cup", "cups", "copo", "copos", "bottle", "garrafa", "can", "lata", "jar", "frasco", "pouch", "sleeve", "wrapper", "tag", "etiqueta", "sticker", "autocolante"],
    "poster": ["poster", "posters", "cartaz", "cartazes", "flyer", "flyers", "folheto", "affiche", "print"],
    "outdoor": ["outdoor", "billboard", "billboards", "ooh", "mupi", "mupis", "busstop", "abribus", "signage", "sinaletica", "facade", "fachada", "storefront", "montra", "banner", "banners", "totem", "street"],
    "social": ["social", "socialmedia", "instagram", "insta", "ig", "post", "posts", "story", "stories", "feed", "facebook", "linkedin", "tiktok", "reel", "reels", "carousel", "carrossel", "redes", "redessociais"],
    "stationery": ["stationery", "papelaria", "businesscard", "businesscards", "card", "cards", "cartao", "cartoes", "letterhead", "envelope", "menu", "ementa", "invoice", "fatura", "notebook", "caderno"],
    "editorial": ["editorial", "magazine", "revista", "book", "livro", "spread", "spreads", "catalogue", "catalog", "catalogo", "brochure", "brochura", "zine", "publication", "publicacao", "annualreport"],
    "mockup": ["mockup", "mockups", "mock", "application", "applications", "aplicacao", "aplicacoes", "merch", "merchandise", "tshirt", "apron", "avental", "uniform", "uniforme", "tote", "totebag", "mug", "caneca"],
    "website": ["website", "web", "site", "landing", "landingpage", "homepage", "desktop", "webpage", "webdesign"],
    "mobile": ["mobile", "app", "iphone", "android", "ios", "phone", "telemovel", "smartphone"],
    "ui": ["ui", "ux", "interface", "dashboard", "screen", "screens", "ecra", "ecras", "wireframe", "wireframes", "prototype", "prototipo", "component", "components"],
    "photo": ["photo", "photos", "foto", "fotos", "photography", "fotografia", "img", "dsc", "dscf", "dji", "shoot", "shot", "shots", "raw"],
    # Subject words (coffee, bread...) are deliberately absent: they describe
    # what is shown, not how it is presented.
    "product": ["product", "products", "produto", "produtos", "packshot", "still", "stilllife"],
    "lifestyle": ["lifestyle", "ambiente", "ambience", "interior", "interiors", "shop", "loja", "store", "space", "espaco", "people", "pessoas", "barista", "customer", "cliente", "venue"],
    "portrait": ["portrait", "portraits", "retrato", "retratos", "headshot", "model", "modelo"],
    "before_after": ["before", "after", "antes", "depois", "retouch", "retouching", "retoque", "retoques", "edited", "editado", "original"],
    "motion": ["motion", "animation", "animacao", "anim", "animated", "loop", "gif"],
    "video": ["video", "videos", "film", "filme", "reel", "teaser", "trailer"],
}

# Words that only make sense together with a logo signal.
_VARIANT_NEEDS_LOGO = True

# Generic words get a lower weight so more specific kinds win ties
# ("coffee-bag-mockup" is packaging; "mockup" alone is a generic application).
KIND_KEYWORD_WEIGHT = {"mockup": 0.85, "photo": 0.8, "product": 0.9, "ui": 0.9}

# Folder words get a lower weight than file-name words.
_FILE_WEIGHT = 1.0
_FOLDER_WEIGHT = 0.7


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return text


def tokenize(text: str) -> list[str]:
    text = _normalize(text)
    # split camelCase before lowercasing would be nicer, but names are lowercased
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t]
    out: list[str] = []
    for token in tokens:
        out.append(token)
        stripped = re.sub(r"\d+$", "", token)  # logo01 -> logo
        if stripped and stripped != token:
            out.append(stripped)
    return out


@dataclass
class Classification:
    kind: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    pair_role: str | None = None  # "before" / "after" for before-after pairs


def keyword_scores(filename: str, folder: str) -> tuple[dict[str, float], list[str]]:
    scores: dict[str, float] = {}
    reasons: list[str] = []
    for text, weight, label in ((filename.rsplit(".", 1)[0], _FILE_WEIGHT, "name"), (folder, _FOLDER_WEIGHT, "folder")):
        tokens = set(tokenize(text))
        joined = "".join(tokenize(text))
        for kind, words in KEYWORDS.items():
            hit = None
            for word in words:
                if word in tokens or (len(word) >= 6 and word in joined):
                    hit = word
                    break
            if hit:
                w = weight * KIND_KEYWORD_WEIGHT.get(kind, 1.0)
                if scores.get(kind, 0) < w:
                    scores[kind] = w
                reasons.append(f"{label} contains '{hit}'")
    if "logo_variant" in scores and "logo" not in scores and "monogram" not in scores:
        scores.pop("logo_variant")
    return scores, reasons


def visual_scores(media_type: str, width: int, height: int, has_alpha: bool, a: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    s: dict[str, float] = {}
    reasons: list[str] = []
    if not a:
        return s, reasons
    aspect = width / height if width and height else 1.0
    flat = a.get("flat_ratio", 0.0)
    n90 = a.get("n90_colors", 100)
    graphic = min(1.0, max(0.0, (flat - 0.35) / 0.45)) * 0.6 + (0.4 if n90 < 24 else 0.2 if n90 < 70 else 0.0)
    photo = max(0.0, 1.0 - graphic)
    if n90 > 150:
        photo = min(1.0, photo + 0.2)
    bbox_area = a.get("content_bbox_area", 1.0)
    fill = a.get("fill_ratio", 1.0)
    background = a.get("background")
    axis = a.get("axis_alignment", 0.0)

    if has_alpha and a.get("transparent_fraction", 0) > 0.15:
        s["logo"] = 0.55 + (0.2 if n90 < 20 else 0)
        s["monogram"] = 0.3 if 0.75 < aspect < 1.33 else 0.1
        s["illustration"] = 0.3
        reasons.append("transparent background")
    elif background and background != "transparent" and fill < 0.32 and graphic > 0.5:
        s["logo"] = 0.5 + (0.15 if n90 < 16 else 0)
        s["monogram"] = 0.25 if 0.75 < aspect < 1.33 else 0.05
        reasons.append("small graphic mark on plain background")

    if a.get("palette_like", 0) >= 0.34 and graphic > 0.45:
        s["palette"] = 0.45 + 0.4 * a["palette_like"]
        reasons.append("large flat colour swatches")

    if photo > 0.55:
        s["photo"] = 0.35 + 0.3 * photo
        reasons.append("photographic texture")
        faces = a.get("faces") or []
        if faces:
            largest = max(f[2] * f[3] for f in faces)
            if largest > 0.04:
                s["portrait"] = 0.45 + min(0.4, largest * 4)
                reasons.append("face detected")
        if background and background != "transparent" and 0.12 < fill < 0.75:
            s["product"] = 0.45
            reasons.append("object isolated on plain background")

    ui_like = graphic > 0.45 and axis > 0.45
    if ui_like and aspect < 0.62 and aspect > 0.4:
        s["mobile"] = 0.5
        reasons.append("phone-screen proportions with interface structure")
    if ui_like and aspect <= 0.55 and height > 2200:
        s["website"] = 0.55
        reasons.append("long page screenshot")
    if ui_like and 1.3 < aspect < 1.9:
        s["website"] = max(s.get("website", 0), 0.35)
        s["ui"] = 0.3
    if aspect >= 2.4:
        s["outdoor"] = 0.35 if graphic > 0.3 else 0.2
        reasons.append("very wide format")
    if 0.64 <= aspect <= 0.76 and graphic > 0.3 and not has_alpha:
        s["poster"] = 0.35
        reasons.append("poster proportions")
    if any(abs(aspect - r) < 0.03 for r in (1.0, 0.8, 0.5625)) and 0.25 < graphic < 0.95 and not has_alpha and width <= 2200:
        s["social"] = 0.3
        reasons.append("social-media proportions")
    if graphic > 0.55 and not has_alpha and a.get("colorfulness", 0) > 25 and axis < 0.35 and n90 > 18:
        s["illustration"] = max(s.get("illustration", 0), 0.3)
    if a.get("grayscale") and graphic > 0.6 and a.get("edge_density", 0) > 0.06 and n90 < 12:
        s["typography"] = 0.3
    if media_type == MEDIA_VIDEO:
        s["video"] = 0.9
    if media_type == MEDIA_GIF and a.get("animated"):
        s["motion"] = 0.85
    if media_type == MEDIA_SVG:
        s["logo"] = max(s.get("logo", 0), 0.45)
        s["illustration"] = max(s.get("illustration", 0), 0.3)
    return s, reasons


# Folders (or file names) the designer uses for reference material: imported
# for the AI director to look at, never placed in a presentation.
REFERENCE_WORDS = {"reference", "references", "referencia", "referencias", "inspiration", "inspiracao", "inspiracoes",
                   "moodboard", "moodboards", "benchmark", "benchmarks"}


def is_reference_path(filename: str, folder: str) -> bool:
    tokens = set(tokenize(folder)) | set(tokenize(filename.rsplit(".", 1)[0]))
    return bool(tokens & REFERENCE_WORDS)


def classify(
    filename: str,
    folder: str,
    media_type: str,
    width: int,
    height: int,
    has_alpha: bool,
    analysis: dict[str, Any],
    animated: bool = False,
) -> Classification:
    if is_reference_path(filename, folder):
        return Classification("reference", 0.95, ["folder or name marks reference material"], {"reference": 0.95}, None)
    kw, kw_reasons = keyword_scores(filename, folder)
    analysis = dict(analysis or {})
    analysis["animated"] = animated
    vis, vis_reasons = visual_scores(media_type, width, height, has_alpha, analysis)

    combined: dict[str, float] = {}
    for kind in set(kw) | set(vis):
        k = kw.get(kind, 0.0)
        v = vis.get(kind, 0.0)
        combined[kind] = 0.62 * k + 0.38 * v + (0.12 if k and v else 0.0)

    # Media type is a fact, not an estimate.
    if media_type == MEDIA_VIDEO:
        combined["video"] = max(combined.get("video", 0), 0.95)
    elif media_type == MEDIA_GIF and animated:
        combined["motion"] = max(combined.get("motion", 0), 0.9)

    # A "logo variant" is a logo first.
    if "logo_variant" in combined and "logo" in combined:
        combined["logo_variant"] += 0.05
    # Before/after are strongly name-driven.
    pair_role = None
    tokens = set(tokenize(filename))
    if tokens & {"before", "antes", "original", "raw"} and "before_after" in kw:
        pair_role = "before"
    elif tokens & {"after", "depois", "edited", "editado", "retouched", "final"} and "before_after" in kw:
        pair_role = "after"
    if "before_after" in combined and pair_role is None and "before_after" not in kw:
        combined.pop("before_after")

    if not combined:
        fallback = "photo" if analysis.get("n90_colors", 0) > 120 else "other"
        return Classification(fallback, 0.15, ["no strong signals"], {}, None)

    ranked = sorted(combined.items(), key=lambda kv: -kv[1])
    best_kind, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = max(0.05, min(0.95, best * 0.75 + (best - second) * 0.6))
    reasons = kw_reasons + vis_reasons
    return Classification(best_kind, round(confidence, 3), reasons[:6], {k: round(v, 3) for k, v in ranked[:5]}, pair_role)
