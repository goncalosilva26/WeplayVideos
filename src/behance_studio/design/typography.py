"""Bundled font catalogue, personality-based pairing and substitution.

All bundled fonts are open-source (SIL OFL) and ship with the application so
previews and exports render identically everywhere, offline.

Personality vectors use six axes in -1..1::

    warmth (cool→warm), energy (calm→playful), refinement (casual→luxury),
    boldness (subtle→bold), modernity (classic→contemporary),
    organic (geometric→organic)
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from behance_studio.core.paths import FONTS_DIR

AXES = ("warmth", "energy", "refinement", "boldness", "modernity", "organic")


@dataclass(frozen=True)
class FontFamily:
    name: str
    category: str  # serif | sans | display | condensed | mono
    regular: str
    italic: str | None = None
    weight_min: int = 400
    weight_max: int = 400
    personality: tuple[float, ...] = (0, 0, 0, 0, 0, 0)
    uppercase_only: bool = False
    fallback: str = "sans-serif"
    width_axis: tuple[int, int] | None = None  # (min, max) of 'wdth' when variable

    @property
    def variable(self) -> bool:
        return self.weight_min != self.weight_max

    def clamp_weight(self, weight: int) -> int:
        return max(self.weight_min, min(self.weight_max, int(weight)))

    def path(self, italic: bool = False) -> Path:
        return FONTS_DIR / (self.italic if italic and self.italic else self.regular)

    @property
    def css_stack(self) -> str:
        return f"'{self.name}', {self.fallback}"


FONTS: dict[str, FontFamily] = {
    f.name: f
    for f in [
        FontFamily("Fraunces", "serif", "Fraunces-VF.ttf", "Fraunces-Italic-VF.ttf", 100, 900, (0.7, 0.4, 0.3, 0.2, 0.0, 0.7), fallback="Georgia, serif"),
        FontFamily("Playfair Display", "serif", "PlayfairDisplay-VF.ttf", "PlayfairDisplay-Italic-VF.ttf", 400, 900, (0.2, -0.2, 0.9, 0.3, -0.5, 0.0), fallback="Georgia, serif"),
        FontFamily("Cormorant Garamond", "serif", "CormorantGaramond-VF.ttf", "CormorantGaramond-Italic-VF.ttf", 300, 700, (0.2, -0.6, 1.0, -0.5, -0.6, 0.2), fallback="Georgia, serif"),
        FontFamily("DM Serif Display", "serif", "DMSerifDisplay-Regular.ttf", "DMSerifDisplay-Italic.ttf", 400, 400, (0.3, 0.0, 0.6, 0.5, -0.1, 0.1), fallback="Georgia, serif"),
        FontFamily("Instrument Serif", "serif", "InstrumentSerif-Regular.ttf", "InstrumentSerif-Italic.ttf", 400, 400, (0.0, -0.3, 0.7, -0.2, 0.6, 0.0), fallback="Georgia, serif"),
        FontFamily("EB Garamond", "serif", "EBGaramond-VF.ttf", "EBGaramond-Italic-VF.ttf", 400, 800, (0.3, -0.5, 0.7, -0.4, -0.9, 0.3), fallback="Georgia, serif"),
        FontFamily("Manrope", "sans", "Manrope-VF.ttf", None, 200, 800, (0.2, 0.1, 0.3, 0.0, 0.6, -0.2)),
        FontFamily("Inter", "sans", "Inter-VF.ttf", None, 100, 900, (0.0, 0.0, 0.2, 0.0, 0.8, -0.6)),
        FontFamily("DM Sans", "sans", "DMSans-VF.ttf", None, 100, 1000, (0.2, 0.2, 0.2, 0.0, 0.6, -0.3)),
        FontFamily("Space Grotesk", "sans", "SpaceGrotesk-VF.ttf", None, 300, 700, (-0.2, 0.3, 0.0, 0.3, 0.9, -0.4)),
        FontFamily("Work Sans", "sans", "WorkSans-VF.ttf", None, 100, 900, (0.1, 0.2, 0.0, 0.1, 0.4, -0.2)),
        FontFamily("Archivo", "sans", "Archivo-VF.ttf", None, 100, 900, (-0.1, 0.4, 0.0, 0.6, 0.5, -0.6), width_axis=(62, 125)),
        FontFamily("Syne", "display", "Syne-VF.ttf", None, 400, 800, (0.0, 0.8, 0.1, 0.6, 0.8, 0.2)),
        FontFamily("Anton", "condensed", "Anton-Regular.ttf", None, 400, 400, (0.0, 0.7, -0.2, 1.0, 0.3, -0.4), fallback="Impact, sans-serif"),
        FontFamily("Bebas Neue", "condensed", "BebasNeue-Regular.ttf", None, 400, 400, (0.0, 0.5, 0.0, 0.8, 0.2, -0.5), uppercase_only=True, fallback="Impact, sans-serif"),
        FontFamily("Oswald", "condensed", "Oswald-VF.ttf", None, 200, 700, (0.0, 0.4, 0.0, 0.6, 0.3, -0.4)),
        FontFamily("Bricolage Grotesque", "display", "BricolageGrotesque-VF.ttf", None, 200, 800, (0.4, 0.7, 0.0, 0.5, 0.6, 0.6)),
        FontFamily("JetBrains Mono", "mono", "JetBrainsMono-VF.ttf", None, 100, 800, (-0.3, 0.0, 0.0, 0.0, 0.9, -0.8), fallback="Consolas, monospace"),
        FontFamily("Outfit", "sans", "Outfit-VF.ttf", None, 100, 900, (0.2, 0.3, 0.1, 0.2, 0.7, -0.3)),
        FontFamily("Plus Jakarta Sans", "sans", "PlusJakartaSans-VF.ttf", None, 200, 800, (0.2, 0.2, 0.3, 0.0, 0.7, -0.2)),
        FontFamily("Unbounded", "display", "Unbounded-VF.ttf", None, 200, 900, (0.1, 0.9, -0.1, 0.8, 0.8, 0.1)),
        FontFamily("Big Shoulders Display", "condensed", "BigShouldersDisplay-VF.ttf", None, 100, 900, (-0.2, 0.5, -0.1, 0.8, 0.3, -0.5)),
    ]
}


@dataclass(frozen=True)
class Pairing:
    display: str
    text: str
    label: str
    personality: tuple[float, ...]
    display_weight: int = 500
    voice: str = "editorial"  # editorial | expressive | technical | condensed


PAIRINGS = [
    Pairing("Fraunces", "Manrope", "Manrope", (0.7, 0.4, 0.3, 0.2, 0.1, 0.6), 500, "editorial"),
    Pairing("Playfair Display", "Inter", "Inter", (0.2, -0.3, 0.9, 0.2, -0.5, 0.0), 500, "editorial"),
    Pairing("Cormorant Garamond", "Manrope", "Manrope", (0.2, -0.6, 1.0, -0.4, -0.4, 0.2), 500, "editorial"),
    Pairing("DM Serif Display", "DM Sans", "DM Sans", (0.3, 0.0, 0.6, 0.4, 0.1, 0.1), 400, "editorial"),
    Pairing("Instrument Serif", "Inter", "Inter", (0.0, -0.3, 0.7, -0.1, 0.6, 0.0), 400, "editorial"),
    Pairing("EB Garamond", "Work Sans", "Work Sans", (0.3, -0.5, 0.7, -0.3, -0.8, 0.3), 500, "editorial"),
    Pairing("Space Grotesk", "Inter", "JetBrains Mono", (-0.2, 0.2, 0.1, 0.3, 0.9, -0.5), 500, "technical"),
    Pairing("Syne", "Manrope", "Manrope", (0.1, 0.8, 0.1, 0.6, 0.8, 0.2), 700, "expressive"),
    Pairing("Anton", "Work Sans", "Work Sans", (0.0, 0.7, -0.2, 1.0, 0.3, -0.3), 400, "condensed"),
    Pairing("Archivo", "Archivo", "JetBrains Mono", (-0.1, 0.4, 0.0, 0.6, 0.6, -0.6), 800, "condensed"),
    Pairing("Unbounded", "Manrope", "Manrope", (0.2, 0.9, -0.1, 0.8, 0.8, 0.2), 600, "expressive"),
    Pairing("Bricolage Grotesque", "DM Sans", "DM Sans", (0.4, 0.7, 0.0, 0.5, 0.6, 0.6), 700, "expressive"),
    Pairing("Outfit", "Outfit", "Outfit", (0.2, 0.3, 0.1, 0.2, 0.7, -0.3), 600, "technical"),
    Pairing("Big Shoulders Display", "Inter", "Inter", (-0.2, 0.5, -0.1, 0.8, 0.3, -0.5), 800, "condensed"),
    Pairing("Oswald", "Manrope", "Manrope", (0.0, 0.4, 0.0, 0.6, 0.3, -0.3), 500, "condensed"),
    Pairing("Plus Jakarta Sans", "Plus Jakarta Sans", "Plus Jakarta Sans", (0.2, 0.2, 0.3, 0.0, 0.7, -0.2), 700, "technical"),
    Pairing("Bebas Neue", "Manrope", "Manrope", (0.0, 0.5, 0.0, 0.8, 0.2, -0.4), 400, "condensed"),
]

# Well-known commercial/system fonts mapped to the closest bundled family.
SUBSTITUTES: dict[str, str] = {
    "helvetica": "Inter", "helvetica neue": "Inter", "arial": "Inter", "neue haas grotesk": "Inter", "neue haas": "Inter",
    "aktiv grotesk": "Inter", "roboto": "Inter", "sf pro": "Inter", "san francisco": "Inter", "segoe ui": "Inter",
    "futura": "Outfit", "gotham": "Outfit", "montserrat": "Outfit", "poppins": "Outfit", "circular": "Outfit", "brandon grotesque": "Outfit",
    "avenir": "Manrope", "avenir next": "Manrope", "proxima nova": "Manrope", "lato": "Manrope", "gilroy": "Manrope", "nunito": "Manrope",
    "open sans": "Work Sans", "source sans": "Work Sans", "source sans pro": "Work Sans", "noto sans": "Work Sans",
    "garamond": "EB Garamond", "adobe garamond": "EB Garamond", "times": "EB Garamond", "times new roman": "EB Garamond",
    "baskerville": "EB Garamond", "libre baskerville": "EB Garamond", "caslon": "EB Garamond", "lora": "EB Garamond", "georgia": "EB Garamond",
    "bodoni": "Playfair Display", "didot": "Playfair Display", "canela": "Instrument Serif", "tiempos": "Instrument Serif",
    "gt sectra": "Instrument Serif", "recoleta": "Fraunces", "cooper": "Fraunces", "cooper black": "Fraunces", "windsor": "Fraunces",
    "cormorant": "Cormorant Garamond", "playfair": "Playfair Display", "dm serif": "DM Serif Display",
    "din": "Archivo", "din pro": "Archivo", "univers": "Archivo", "akzidenz grotesk": "Archivo",
    "impact": "Anton", "league gothic": "Anton", "druk": "Anton", "bebas": "Bebas Neue", "knockout": "Big Shoulders Display",
    "courier": "JetBrains Mono", "space mono": "JetBrains Mono", "ibm plex mono": "JetBrains Mono", "roboto mono": "JetBrains Mono",
    "ibm plex sans": "Inter", "graphik": "Inter", "suisse": "Inter", "suisse intl": "Inter", "apercu": "DM Sans",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.split(r"[^a-z0-9]+", text)).strip()


def get_font(name: str) -> FontFamily:
    return FONTS.get(name) or FONTS["Inter"]


@dataclass
class FontMention:
    requested: str
    family: str  # bundled family actually used
    role: str | None  # display | text | None
    substituted: bool


_DISPLAY_WORDS = re.compile(r"\b(head|headline|headlines|heading|headings|title|titles|display|titulo|titulos|destaque|destaques|cabecalho)")
_TEXT_WORDS = re.compile(r"\b(body|text|copy|supporting|paragraph|paragraphs|texto|textos|corpo|leitura|secondary|secundaria)")


def find_font_mentions(text: str) -> list[FontMention]:
    """Find font names mentioned in free text (e.g. a brief), with their role.

    Roles come from nearby words in the same clause: "Fraunces for headings,
    Manrope for body copy" → Fraunces=display, Manrope=text.
    """
    candidates: list[tuple[str, str, bool]] = [(_norm(n), n, False) for n in FONTS]
    candidates += [(k, v, True) for k, v in SUBSTITUTES.items()]
    candidates.sort(key=lambda c: -len(c[0]))
    found: list[FontMention] = []
    seen: set[str] = set()
    for clause in re.split(r"[.;,\n]+", text or ""):
        norm = " " + _norm(clause) + " "
        hits: list[tuple[int, int, str, str, bool]] = []
        for key, family, substituted in candidates:
            if len(key) < 3:
                continue
            start = norm.find(f" {key} ")
            if start < 0:
                continue
            span = (start, start + len(key) + 2)
            if any(not (span[1] <= h[0] or span[0] >= h[1]) for h in hits):
                continue
            hits.append((span[0], span[1], key, family, substituted))
        hits.sort()
        for i, (s0, s1, key, family, substituted) in enumerate(hits):
            after = norm[s1: hits[i + 1][0] if i + 1 < len(hits) else len(norm)]
            before = norm[hits[i - 1][1] if i > 0 else 0: s0]
            # A conjunction starts a new phrase: "Futura e texto em Garamond".
            after = re.split(r" (?:and|e|while|enquanto|plus|mais) ", " " + after + " ")[0]
            before = re.split(r" (?:and|e|while|enquanto|plus|mais) ", " " + before + " ")[-1]
            role = None
            for segment in (after, before):
                d = _DISPLAY_WORDS.search(segment)
                t = _TEXT_WORDS.search(segment)
                if d and (not t or d.start() < t.start()):
                    role = "display"
                elif t:
                    role = "text"
                if role:
                    break
            if key in seen:
                continue
            seen.add(key)
            found.append(FontMention(requested=key, family=family, role=role, substituted=substituted))
    return found


AXIS_WEIGHTS = (1.4, 1.0, 1.0, 0.8, 0.8, 0.7)


def personality_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum(w * (x - y) ** 2 for x, y, w in zip(a, b, AXIS_WEIGHTS)))


def rank_pairings(personality: dict[str, float], voices: set[str] | None = None) -> list[Pairing]:
    vec = tuple(personality.get(a, 0.0) for a in AXES)
    pool = [p for p in PAIRINGS if voices is None or p.voice in voices] or PAIRINGS
    return sorted(pool, key=lambda p: personality_distance(vec, p.personality))


@dataclass
class TypeSystem:
    """Fonts used by a presentation."""

    display: str
    text: str
    label: str
    display_weight: int = 500
    text_weight: int = 400
    source: str = "inferred"  # brief | inferred
    notes: list[str] = field(default_factory=list)

    def families(self) -> list[str]:
        return list(dict.fromkeys([self.display, self.text, self.label]))

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "TypeSystem":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
