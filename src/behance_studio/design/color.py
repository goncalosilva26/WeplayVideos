"""Colour utilities: parsing, CIE Lab, WCAG contrast, mixing and adjustment."""

from __future__ import annotations

import colorsys
import math
import re

RGB = tuple[int, int, int]

# Common colour names (EN + PT) used only when a brief names colours without
# giving exact values. Values are generic, recognisable defaults.
NAMED_COLORS: dict[str, str] = {
    "black": "#111111", "preto": "#111111", "white": "#FFFFFF", "branco": "#FFFFFF",
    "ivory": "#F6F1E6", "marfim": "#F6F1E6", "cream": "#F5ECDD", "creme": "#F5ECDD", "beige": "#E8DCC6", "bege": "#E8DCC6",
    "sand": "#D9C7A7", "areia": "#D9C7A7", "grey": "#8A8A8A", "gray": "#8A8A8A", "cinza": "#8A8A8A", "cinzento": "#8A8A8A",
    "charcoal": "#2B2B2B", "carvao": "#2B2B2B", "navy": "#1C2541", "azul marinho": "#1C2541", "blue": "#2F5DD3", "azul": "#2F5DD3",
    "sky blue": "#8EC5E8", "azul ceu": "#8EC5E8", "teal": "#1E7A7A", "turquoise": "#2EC4B6", "turquesa": "#2EC4B6",
    "green": "#2E8B57", "verde": "#2E8B57", "sage": "#9CAF88", "salvia": "#9CAF88", "olive": "#6B6B2E", "azeitona": "#6B6B2E",
    "forest green": "#1F4D36", "verde floresta": "#1F4D36", "mint": "#BDE5D3", "menta": "#BDE5D3",
    "yellow": "#F2C230", "amarelo": "#F2C230", "mustard": "#D4A017", "mostarda": "#D4A017", "butter": "#F4C95D", "manteiga": "#F4C95D",
    "orange": "#EE7A2F", "laranja": "#EE7A2F", "terracotta": "#D9663F", "terracota": "#D9663F", "rust": "#A9472A", "ferrugem": "#A9472A",
    "red": "#D63A3A", "vermelho": "#D63A3A", "burgundy": "#6D1A2E", "bordeaux": "#6D1A2E", "bordo": "#6D1A2E", "wine": "#6D1A2E",
    "pink": "#F2A7B8", "rosa": "#F2A7B8", "blush": "#F3D3CF", "coral": "#F27059", "lilac": "#C8A2C8", "lilas": "#C8A2C8",
    "purple": "#6A3FA0", "roxo": "#6A3FA0", "violet": "#7F5AF0", "violeta": "#7F5AF0", "lavender": "#D7CCF2", "lavanda": "#D7CCF2",
    "brown": "#6B4226", "castanho": "#6B4226", "marrom": "#6B4226", "espresso": "#2E1F17", "chocolate": "#4A2C1D", "coffee": "#5C3B28", "cafe": "#5C3B28",
    "gold": "#C9A227", "dourado": "#C9A227", "silver": "#C0C0C0", "prateado": "#C0C0C0", "copper": "#B87333", "cobre": "#B87333",
}


def clamp8(v: float) -> int:
    return int(max(0, min(255, round(v))))


def parse_hex(value: str) -> RGB | None:
    if not value:
        return None
    v = value.strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", v):
        v = "".join(c * 2 for c in v)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", v):
        return None
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(clamp8(c) for c in rgb))


def normalize_hex(value: str) -> str | None:
    rgb = parse_hex(value)
    return to_hex(rgb) if rgb else None


def parse_color(value: str) -> str | None:
    """Accept #hex, rgb(r,g,b) or a common colour name."""
    value = (value or "").strip()
    h = normalize_hex(value)
    if h:
        return h
    m = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", value, re.I)
    if m:
        return to_hex(tuple(int(x) for x in m.groups()))  # type: ignore[arg-type]
    return NAMED_COLORS.get(value.lower())


# ---------------------------------------------------------------- Lab
def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    v = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return v * 255.0


def rgb_to_lab(rgb: RGB) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lab_to_rgb(lab: tuple[float, float, float]) -> RGB:
    l, a, b = lab
    fy = (l + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200

    def finv(t: float) -> float:
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787

    x, y, z = finv(fx) * 0.95047, finv(fy), finv(fz) * 1.08883
    r = x * 3.2406 + y * -1.5372 + z * -0.4986
    g = x * -0.9689 + y * 1.8758 + z * 0.0415
    bb = x * 0.0557 + y * -0.2040 + z * 1.0570
    return (clamp8(_linear_to_srgb(r)), clamp8(_linear_to_srgb(g)), clamp8(_linear_to_srgb(bb)))


def hex_to_lab(value: str) -> tuple[float, float, float]:
    return rgb_to_lab(parse_hex(value) or (0, 0, 0))


def lab_to_hex(lab: tuple[float, float, float]) -> str:
    return to_hex(lab_to_rgb(lab))


def delta_e(a: str, b: str) -> float:
    la, lb = hex_to_lab(a), hex_to_lab(b)
    return math.dist(la, lb)


def lightness(value: str) -> float:
    return hex_to_lab(value)[0]


def chroma(value: str) -> float:
    _l, a, b = hex_to_lab(value)
    return math.hypot(a, b)


def hue_deg(value: str) -> float:
    _l, a, b = hex_to_lab(value)
    return math.degrees(math.atan2(b, a)) % 360


def warmth(value: str) -> float:
    """-1 (cool) .. +1 (warm), weighted by chroma."""
    h = hue_deg(value)
    c = min(1.0, chroma(value) / 60)
    # warm hues ≈ 0-100° in Lab (reds, oranges, yellows)
    w = math.cos(math.radians(h - 50))
    return max(-1.0, min(1.0, w * c))


# ----------------------------------------------------------- WCAG
def relative_luminance(value: str) -> float:
    r, g, b = (_srgb_to_linear(c) for c in (parse_hex(value) or (0, 0, 0)))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def contrast_with_luminance(color: str, luminance: float) -> float:
    lc = relative_luminance(color)
    hi, lo = max(lc, luminance), min(lc, luminance)
    return (hi + 0.05) / (lo + 0.05)


def is_dark(value: str) -> bool:
    return relative_luminance(value) < 0.18


# ------------------------------------------------------- adjustment
def mix(a: str, b: str, t: float) -> str:
    """Linear mix in Lab space: t=0 → a, t=1 → b."""
    la, lb = hex_to_lab(a), hex_to_lab(b)
    return lab_to_hex(tuple(la[i] + (lb[i] - la[i]) * t for i in range(3)))  # type: ignore[arg-type]


def with_lightness(value: str, target_l: float, chroma_scale: float = 1.0) -> str:
    l, a, b = hex_to_lab(value)
    return lab_to_hex((max(0.0, min(100.0, target_l)), a * chroma_scale, b * chroma_scale))


def tint(value: str, amount: float) -> str:
    return mix(value, "#FFFFFF", amount)


def shade(value: str, amount: float) -> str:
    return mix(value, "#000000", amount)


def ensure_contrast(fg: str, bg: str, minimum: float = 4.5) -> str:
    """Adjust ``fg`` lightness (keeping hue) until it reaches the contrast."""
    if contrast_ratio(fg, bg) >= minimum:
        return fg
    l, a, b = hex_to_lab(fg)
    bg_dark = is_dark(bg)
    step = 4 if bg_dark else -4
    for _ in range(30):
        l = max(0.0, min(100.0, l + step))
        candidate = lab_to_hex((l, a, b))
        if contrast_ratio(candidate, bg) >= minimum:
            return candidate
    return "#FFFFFF" if bg_dark else "#111111"


def readable_on(bg: str, light: str = "#FFFFFF", dark: str = "#111111") -> str:
    return light if contrast_ratio(light, bg) >= contrast_ratio(dark, bg) else dark


def hsv_rotate(value: str, degrees: float) -> str:
    r, g, b = (c / 255 for c in (parse_hex(value) or (0, 0, 0)))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + degrees / 360) % 1.0
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return to_hex((r2 * 255, g2 * 255, b2 * 255))  # type: ignore[arg-type]


def rgb_string(value: str) -> str:
    r, g, b = parse_hex(value) or (0, 0, 0)
    return f"{r} {g} {b}"


def cmyk_string(value: str) -> str:
    """Naive (uncalibrated) CMYK approximation for swatch labels."""
    r, g, b = (c / 255 for c in (parse_hex(value) or (0, 0, 0)))
    k = 1 - max(r, g, b)
    if k >= 1:
        return "0 0 0 100"
    c = (1 - r - k) / (1 - k)
    m = (1 - g - k) / (1 - k)
    y = (1 - b - k) / (1 - k)
    return " ".join(str(round(v * 100)) for v in (c, m, y, k))
