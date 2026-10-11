"""Very small English/Portuguese language identification by stop-words."""

from __future__ import annotations

import re
import unicodedata

SUPPORTED_LANGUAGES = {"en": "English", "pt": "Português"}

_EN = set(
    "the and of to in is for with on that this a an are as by from be at or it our your we their its "
    "new specialty freshly baked brand identity design project".split()
)
_PT = set(
    "o a os as de da do das dos e é em para com por que um uma uns umas no na nos nas ao à pelo pela "
    "nosso nossa seu sua são marca projeto projecto identidade design visual café não mais".split()
)
_PT_CHARS = set("ãõçáéíóúâêôà")


def detect_language(text: str, default: str = "en") -> str:
    if not text or not text.strip():
        return default
    lowered = text.lower()
    words = re.findall(r"[a-zà-ÿ]+", lowered)
    if not words:
        return default
    en = sum(1 for w in words if w in _EN)
    pt = sum(1 for w in words if w in _PT)
    pt += sum(1 for c in lowered if c in _PT_CHARS) * 0.5
    if pt > en * 1.15 and pt >= 2:
        return "pt"
    if en > pt and en >= 2:
        return "en"
    return default


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    v = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().strip().lower()
    if v in ("en", "eng", "english", "ingles", "en-us", "en-gb"):
        return "en"
    if v in ("pt", "pt-pt", "pt-br", "por", "portuguese", "portugues", "portugues europeu"):
        return "pt"
    if v.startswith("en"):
        return "en"
    if v.startswith("pt") or v.startswith("portug"):
        return "pt"
    return None
