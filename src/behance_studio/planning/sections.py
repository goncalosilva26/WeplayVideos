"""Catalogue of presentation section types.

Each type knows its display titles (EN/PT), name aliases used to recognise
script sections ("Capa" → cover), and which asset kinds it naturally shows.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SectionType:
    id: str
    title_en: str
    title_pt: str
    aliases: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    textual: bool = False  # mostly text (intro, concept)
    identity: bool = False  # part of the identity system

    def title(self, language: str) -> str:
        return self.title_pt if language == "pt" else self.title_en


_TYPES = [
    SectionType("cover", "Cover", "Capa", ("hero", "capa", "cover", "abertura", "opening", "title", "titulo")),
    SectionType("intro", "Introduction", "Introdução", ("introduction", "introducao", "intro", "about", "sobre", "apresentacao", "presentation"), textual=True),
    SectionType("overview", "Project Overview", "Visão Geral", ("overview", "visao geral", "resumo", "summary", "the project", "o projeto", "o projecto", "project overview"), textual=True),
    SectionType("concept", "The Concept", "O Conceito", ("concept", "conceito", "the concept", "o conceito", "idea", "ideia"), textual=True),
    SectionType("creative_direction", "Creative Direction", "Direção Criativa", ("creative direction", "direcao criativa", "art direction", "direcao de arte", "mood", "moodboard"), textual=True),
    SectionType("brand_story", "Brand Story", "História da Marca", ("brand story", "historia da marca", "story", "historia", "narrative", "narrativa"), textual=True),
    SectionType("logo", "Logo Identity", "Logótipo", ("logo", "logotipo", "logotype", "logo identity", "identidade", "brand identity", "identidade visual", "marca", "the logo", "o logotipo", "brand mark"), ("logo", "monogram", "logo_variant"), identity=True),
    SectionType("logo_construction", "Logo Construction", "Construção do Logótipo", ("construction", "construcao", "grid", "grelha", "logo construction"), ("logo",), identity=True),
    SectionType("logo_variations", "Logo Variations", "Variações do Logótipo", ("variations", "variacoes", "variants", "versoes", "logo variations", "secondary logos", "monogram", "monograma"), ("logo_variant", "monogram", "logo"), identity=True),
    SectionType("palette", "Colour Palette", "Paleta de Cores", ("colour", "color", "colours", "colors", "palette", "paleta", "cores", "cor", "colour palette", "color palette", "paleta de cores", "paleta cromatica"), ("palette",), identity=True),
    SectionType("typography", "Typography", "Tipografia", ("typography", "tipografia", "type", "typefaces", "fonts", "fontes"), ("typography",), identity=True),
    SectionType("visual_language", "Visual Language", "Linguagem Visual", ("visual language", "linguagem visual", "graphic elements", "elementos graficos", "patterns", "padroes", "graphics", "grafismos", "iconography", "iconografia"), ("pattern", "illustration"), identity=True),
    SectionType("applications", "Brand Applications", "Aplicações", ("applications", "aplicacoes", "brand applications", "stationery", "papelaria", "collateral", "touchpoints", "merchandise", "merch"), ("stationery", "mockup")),
    SectionType("packaging", "Packaging", "Embalagem", ("packaging", "embalagem", "embalagens", "pack", "packs"), ("packaging",)),
    SectionType("product", "Product", "Produto", ("product", "produto", "products", "produtos", "product photography", "fotografia de produto"), ("product",)),
    SectionType("campaign", "Advertising Campaign", "Campanha", ("campaign", "campanha", "advertising", "publicidade", "advertising campaign", "campanha publicitaria", "ads", "anuncios"), ("poster", "outdoor", "social")),
    SectionType("posters", "Posters", "Cartazes", ("posters", "poster", "cartazes", "cartaz", "print"), ("poster",)),
    SectionType("outdoor", "Outdoor", "Exterior", ("outdoor", "billboard", "billboards", "ooh", "mupis", "out of home", "exterior"), ("outdoor",)),
    SectionType("social", "Social Media", "Redes Sociais", ("social", "social media", "redes sociais", "redes", "instagram", "posts", "stories", "digital"), ("social",)),
    SectionType("website", "Website", "Website", ("website", "web", "site", "web design", "landing page"), ("website",)),
    SectionType("mobile", "Mobile App", "Aplicação Móvel", ("mobile", "app", "mobile app", "aplicacao movel", "aplicacao", "ios", "android"), ("mobile",)),
    SectionType("ui_screens", "Interface Design", "Design de Interface", ("ui", "ux", "ui/ux", "interface", "screens", "ecras", "ui screens", "design system", "sistema de design"), ("ui", "website", "mobile")),
    SectionType("motion", "Motion Design", "Motion Design", ("motion", "animation", "animacao", "motion design", "motion graphics"), ("motion", "video")),
    SectionType("video", "Video", "Vídeo", ("video", "film", "filme", "showreel", "reel", "video showcase"), ("video",)),
    SectionType("photography", "Photography", "Fotografia", ("photography", "fotografia", "photos", "fotos", "imagery", "imagem", "gallery", "galeria", "lifestyle"), ("photo", "lifestyle", "product", "portrait")),
    SectionType("before_after", "Before & After", "Antes e Depois", ("before after", "before & after", "before and after", "antes e depois", "antes depois", "retouching", "retoque", "retouch"), ("before_after",)),
    SectionType("illustration", "Illustration", "Ilustração", ("illustration", "ilustracao", "ilustracoes", "illustrations", "artwork", "drawings"), ("illustration",)),
    SectionType("editorial", "Editorial", "Editorial", ("editorial", "magazine", "revista", "book", "livro", "spreads", "publication", "publicacao", "catalogue", "catalogo"), ("editorial",)),
    SectionType("mockups", "Mockups", "Mockups", ("mockups", "mockup", "mock-ups"), ("mockup",)),
    SectionType("final", "Final Presentation", "Apresentação Final", ("final", "final presentation", "apresentacao final", "highlights", "destaques", "selected work", "trabalho selecionado"), ()),
    SectionType("gallery", "Gallery", "Galeria", ("gallery", "galeria", "more", "mais", "selection", "selecao", "details", "detalhes"), ()),
    SectionType("closing", "Thank You", "Obrigado", ("closing", "thank you", "thanks", "obrigado", "obrigada", "fim", "end", "the end", "encerramento", "credits", "creditos", "fecho"), ()),
    SectionType("custom", "Section", "Secção", ()),
]

SECTION_TYPES: dict[str, SectionType] = {t.id: t for t in _TYPES}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    for ch in "_-–—:./()[]#*\"'":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def section_type_from_name(name: str) -> str:
    """Map a free-text section name (EN/PT) to a section type id."""
    norm = _norm(name)
    # drop leading numbering: "1 capa", "01 brand identity", "section 2 ..."
    words = [w for w in norm.split() if not w.isdigit()]
    for prefix in ("section", "seccao", "secao", "seção", "parte", "part", "chapter", "capitulo"):
        if words and words[0] == prefix:
            words = words[1:]
    norm = " ".join(w for w in words if not w.isdigit())
    if not norm:
        return "custom"
    for t in _TYPES:
        if norm == t.id.replace("_", " ") or norm in t.aliases:
            return t.id
    # partial matches: longest alias contained in the name
    best, best_len = "custom", 0
    for t in _TYPES:
        for alias in t.aliases:
            if len(alias) >= 3 and (f" {alias} " in f" {norm} ") and len(alias) > best_len:
                best, best_len = t.id, len(alias)
    return best


def section_type(type_id: str) -> SectionType:
    return SECTION_TYPES.get(type_id, SECTION_TYPES["custom"])
