"""Generated presentation copy (English / Portuguese).

Content-integrity rules applied here:

* Generated sentences only *describe what the presentation shows* (its
  sections and the material supplied). They never state client facts,
  results, metrics, awards or a design process.
* User-authored text (script, brief description, quoted brand messages) is
  always preferred and is never rewritten.
* Every string is stored in the plan, so it is inspectable and editable.
"""

from __future__ import annotations

from behance_studio.design.category import CATEGORIES
from behance_studio.planning.sections import section_type

# What each section "shows", for honest summaries (EN, PT with article).
SHOWN_ITEMS: dict[str, tuple[str, str]] = {
    "logo": ("the logo", "o logótipo"),
    "logo_variations": ("logo variations", "as variações do logótipo"),
    "palette": ("the colour palette", "a paleta de cores"),
    "typography": ("typography", "a tipografia"),
    "visual_language": ("graphic elements", "os elementos gráficos"),
    "applications": ("brand applications", "as aplicações da marca"),
    "packaging": ("packaging", "a embalagem"),
    "product": ("product imagery", "as imagens de produto"),
    "campaign": ("the advertising campaign", "a campanha publicitária"),
    "posters": ("posters", "os cartazes"),
    "outdoor": ("outdoor advertising", "a publicidade exterior"),
    "social": ("social media", "as redes sociais"),
    "website": ("the website", "o website"),
    "mobile": ("the mobile app", "a aplicação móvel"),
    "ui_screens": ("interface screens", "os ecrãs de interface"),
    "motion": ("motion design", "o motion design"),
    "video": ("video", "o vídeo"),
    "photography": ("photography", "a fotografia"),
    "before_after": ("before-and-after comparisons", "comparações antes e depois"),
    "illustration": ("illustration", "a ilustração"),
    "editorial": ("editorial design", "o design editorial"),
    "mockups": ("mockups", "os mockups"),
}

KIND_CAPTIONS: dict[str, tuple[str, str]] = {
    "logo": ("Logo", "Logótipo"),
    "logo_variant": ("Logo variation", "Variação do logótipo"),
    "monogram": ("Monogram", "Monograma"),
    "palette": ("Colour palette", "Paleta de cores"),
    "typography": ("Typography", "Tipografia"),
    "pattern": ("Pattern", "Padrão"),
    "illustration": ("Illustration", "Ilustração"),
    "packaging": ("Packaging", "Embalagem"),
    "poster": ("Poster", "Cartaz"),
    "outdoor": ("Outdoor", "Exterior"),
    "social": ("Social media", "Redes sociais"),
    "stationery": ("Stationery", "Papelaria"),
    "editorial": ("Editorial", "Editorial"),
    "mockup": ("Application", "Aplicação"),
    "website": ("Website", "Website"),
    "mobile": ("Mobile", "Mobile"),
    "ui": ("Interface", "Interface"),
    "video": ("Video", "Vídeo"),
    "motion": ("Motion", "Motion"),
    "before_after": ("Before / After", "Antes / Depois"),
}

STRINGS: dict[str, tuple[str, str]] = {
    "thank_you": ("Thank you", "Obrigado"),
    "thanks_for_watching": ("Thank you for watching", "Obrigado pela atenção"),
    "intro_title": ("About the project", "Sobre o projeto"),
    "colour": ("Colour", "Cor"),
    "primary": ("Primary", "Principal"),
    "secondary": ("Secondary", "Secundária"),
    "accent": ("Accent", "Destaque"),
    "dark": ("Dark", "Escura"),
    "light": ("Light", "Clara"),
    "neutral": ("Neutral", "Neutra"),
    "headlines": ("Headlines", "Títulos"),
    "body_copy": ("Body copy", "Texto corrido"),
    "before": ("Before", "Antes"),
    "after": ("After", "Depois"),
    "project": ("Project", "Projeto"),
    "category": ("Category", "Categoria"),
    "contents": ("Contents", "Conteúdos"),
    "chapter": ("Chapter", "Capítulo"),
    "section": ("Section", "Secção"),
    "palette_body": ("The core colours of the identity, with their reference values.", "As cores principais da identidade, com os respetivos valores de referência."),
    "type_body": ("{display} for headlines and {text} for supporting text.", "{display} para títulos e {text} para o texto de apoio."),
    "type_body_single": ("{display} across headlines and supporting text.", "{display} em títulos e texto de apoio."),
}


class Copywriter:
    def __init__(self, language: str = "en") -> None:
        self.language = "pt" if language == "pt" else "en"
        self._i = 1 if self.language == "pt" else 0

    def s(self, key: str, **kwargs: str) -> str:
        text = STRINGS[key][self._i]
        return text.format(**kwargs) if kwargs else text

    def section_title(self, type_id: str) -> str:
        return section_type(type_id).title(self.language)

    def category_label(self, category: str) -> str:
        en, pt = CATEGORIES.get(category, CATEGORIES["mixed"])
        return pt if self.language == "pt" else en

    def kind_caption(self, kind: str) -> str | None:
        pair = KIND_CAPTIONS.get(kind)
        return pair[self._i] if pair else None

    def _join(self, items: list[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        conj = " e " if self.language == "pt" else " and "
        return ", ".join(items[:-1]) + conj + items[-1]

    def intro_text(self, project: str, category: str, section_types: list[str]) -> str:
        items = []
        for t in section_types:
            pair = SHOWN_ITEMS.get(t)
            if pair and pair[self._i] not in items:
                items.append(pair[self._i])
        cat = self.category_label(category).lower()
        if self.language == "pt":
            base = f"Um projeto de {cat} para {project}"
            return f"{base}, que inclui {self._join(items)}." if items else f"{base}."
        article = "An" if cat[:1] in "aeiou" else "A"
        base = f"{article} {cat} project for {project}"
        return f"{base}, covering {self._join(items)}." if items else f"{base}."

    def palette_body(self) -> str:
        return self.s("palette_body")

    def typography_body(self, display: str, text: str) -> str:
        if display == text:
            return self.s("type_body_single", display=display)
        return self.s("type_body", display=display, text=text)

    def swatch_role(self, role: str) -> str:
        return self.s(role) if role in STRINGS else role.title()
