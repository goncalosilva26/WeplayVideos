"""Design Spec v2: JSON schema, validation and (de)serialisation.

The Design Spec is the single machine-readable representation of a
presentation: an ordered list of sections (artboards) of exact height, each
holding layers with absolute geometry, z-order, asset references and fitting
rules, typography, shapes, masks, transforms, effects and device frames.

One schema serves three purposes:

* validating any spec before it is rendered — including specs produced or
  modified by an AI provider, which are never trusted blindly;
* documenting the format (``docs/design-spec.schema.json`` is generated
  from :func:`schema`);
* the structured-output contract given to AI providers.

The validator implements the JSON-Schema subset used here (types, enums,
ranges, required properties, nested objects and arrays) without extra
dependencies, then adds semantic checks the schema cannot express (asset
references, colours, fonts, finite geometry, layer ids).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from behance_studio.layout.devices import DEVICES
from behance_studio.layout.model import Presentation

SPEC_VERSION = 2

LAYER_KINDS = ["image", "video", "text", "shape"]
FITS = ["cover", "contain"]
CLIPS = ["circle", "oval", "pill", "arch", "rounded"]
FADES = ["top", "bottom", "left", "right"]
SHADOWS = ["soft", "lifted", "float", "hard", "glow"]
FILTERS = ["grayscale", "muted", "dim"]
BLENDS = ["normal", "multiply", "screen", "overlay", "darken", "lighten", "soft-light", "luminosity"]
SHAPES = ["rect", "circle", "line", "ring"]
ALIGNS = ["left", "center", "right"]
ROLES = ["display", "title", "subtitle", "eyebrow", "body", "caption", "label", "numeral", "quote", "marquee", ""]
EDGES = ["outline", "soft"]

_NUM = {"type": "number"}
_COLOR = {"type": ["string", "null"], "maxLength": 400}

TEXT_STYLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["family", "size"],
    "properties": {
        "family": {"type": "string", "minLength": 1, "maxLength": 80},
        "size": {"type": "number", "minimum": 4, "maximum": 2000},
        "weight": {"type": "integer", "minimum": 100, "maximum": 1000},
        "line_height": {"type": "number", "minimum": 0.5, "maximum": 4},
        "tracking": {"type": "number", "minimum": -0.2, "maximum": 1.5},
        "color": {"type": "string", "maxLength": 64},
        "italic": {"type": "boolean"},
        "uppercase": {"type": "boolean"},
        "stretch": {"type": "integer", "minimum": 50, "maximum": 200},
        "stroke": _COLOR,
        "opacity": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

LAYER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["kind", "x", "y", "w", "h"],
    "properties": {
        "kind": {"type": "string", "enum": LAYER_KINDS},
        "id": {"type": "string", "maxLength": 40},
        "x": _NUM,
        "y": _NUM,
        "w": {"type": "number", "minimum": 0.5},
        "h": {"type": "number", "minimum": 0.5},
        "z": {"type": "integer", "minimum": -10, "maximum": 1000},
        "asset_id": {"type": ["string", "null"]},
        "fit": {"type": "string", "enum": FITS},
        "focal": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": 0, "maximum": 100}},
        "pad": {"type": "number", "minimum": 0},
        "mat": _COLOR,
        "radius": {"type": "number", "minimum": 0},
        "crop": {"type": "number", "minimum": 0, "maximum": 1},
        "edge": {"type": ["string", "null"], "enum": EDGES + [None]},
        "edge_color": _COLOR,
        "text": {"type": "string", "maxLength": 20000},
        "lines": {"type": "array", "items": {"type": "string"}},
        "style": {"anyOfNull": True, **TEXT_STYLE_SCHEMA},
        "align": {"type": "string", "enum": ALIGNS},
        "role": {"type": "string", "enum": ROLES},
        "para_gap": {"type": "number", "minimum": 0, "maximum": 4},
        "fill": _COLOR,
        "shape": {"type": "string", "enum": SHAPES},
        "stroke": _COLOR,
        "stroke_width": {"type": "number", "minimum": 0, "maximum": 200},
        "opacity": {"type": "number", "minimum": 0, "maximum": 1},
        "overlay": {"type": "boolean"},
        "decorative": {"type": "boolean"},
        "editable": {"type": ["string", "null"]},
        "meta": {"type": "object"},
        "rotate": {"type": "number", "minimum": -180, "maximum": 180},
        "perspective": {"type": ["array", "null"], "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": -60, "maximum": 60}},
        "clip": {"type": ["string", "null"], "enum": CLIPS + [None]},
        "fade": {"type": ["string", "null"], "enum": FADES + [None]},
        "shadow": {"type": ["string", "null"], "enum": SHADOWS + [None]},
        "shadow_color": _COLOR,
        "blend": {"type": ["string", "null"], "enum": BLENDS + [None]},
        "filter": {"type": ["string", "null"], "enum": FILTERS + [None]},
        "tint": _COLOR,
        "zoom": {"type": "number", "minimum": 1, "maximum": 4},
        "device": {"type": ["string", "null"], "enum": list(DEVICES) + [None]},
        "device_color": _COLOR,
        "fill_asset": {"type": ["string", "null"]},
        "fill_size": {"type": "number", "minimum": 0, "maximum": 4000},
        "group": {"type": ["string", "null"], "maxLength": 40},
    },
}

SECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "height", "background", "blocks"],
    "properties": {
        "id": {"type": "string", "maxLength": 40},
        "type": {"type": "string", "maxLength": 40},
        "height": {"type": "number", "minimum": 40, "maximum": 20000},
        "background": {"type": "string", "maxLength": 400},
        "gradient": _COLOR,
        "blocks": {"type": "array", "maxItems": 400, "items": LAYER_SCHEMA},
        "plan_id": {"type": "string"},
        "title": {"type": "string"},
        "theme": {"type": "string", "enum": ["light", "dark"]},
        "pattern": {"type": "string"},
        "breaks": {"type": "array", "items": {"type": "number"}},
        "meta": {"type": "object"},
    },
}

DOCUMENT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Behance Studio Design Spec",
    "type": "object",
    "required": ["width", "sections"],
    "properties": {
        "spec_version": {"type": "integer", "minimum": 1, "maximum": SPEC_VERSION},
        "family": {"type": "string"},
        "seed": {"type": "integer"},
        "width": {"type": "integer", "minimum": 320, "maximum": 10000},
        "title": {"type": "string"},
        "language": {"type": "string"},
        "page_background": {"type": "string"},
        "fonts": {"type": "array", "items": {"type": "string"}},
        "variant": {"type": "object"},
        "sections": {"type": "array", "minItems": 1, "maxItems": 200, "items": SECTION_SCHEMA},
    },
}


def schema() -> dict[str, Any]:
    """The document schema (JSON Schema draft 2020-12)."""
    import copy

    doc = copy.deepcopy(DOCUMENT_SCHEMA)

    def clean(node: Any) -> None:
        if isinstance(node, dict):
            if node.pop("anyOfNull", None):
                node["type"] = [node.get("type", "object"), "null"]
            for v in node.values():
                clean(v)
        elif isinstance(node, list):
            for v in node:
                clean(v)

    clean(doc)
    return doc


# ----------------------------------------------------------- validation
@dataclass
class SpecError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '$'}: {self.message}"


_TYPES = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, (list, tuple)),
    "null": lambda v: v is None,
}


def check_schema(value: Any, node: dict[str, Any], path: str = "", errors: list[SpecError] | None = None, limit: int = 50) -> list[SpecError]:
    """Validate ``value`` against the JSON-Schema subset used in this module."""
    errors = [] if errors is None else errors
    if len(errors) >= limit:
        return errors
    if node.get("anyOfNull") and value is None:
        return errors
    expected = node.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_TYPES[t](value) for t in types):
            errors.append(SpecError(path, f"expected {' or '.join(types)}, got {type(value).__name__}"))
            return errors
    if "enum" in node and value not in node["enum"]:
        errors.append(SpecError(path, f"must be one of {node['enum']}"))
    if _TYPES["number"](value):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            errors.append(SpecError(path, "must be a finite number"))
        if "minimum" in node and value < node["minimum"]:
            errors.append(SpecError(path, f"must be ≥ {node['minimum']}"))
        if "maximum" in node and value > node["maximum"]:
            errors.append(SpecError(path, f"must be ≤ {node['maximum']}"))
    if isinstance(value, str):
        if "minLength" in node and len(value) < node["minLength"]:
            errors.append(SpecError(path, f"must have at least {node['minLength']} characters"))
        if "maxLength" in node and len(value) > node["maxLength"]:
            errors.append(SpecError(path, f"must have at most {node['maxLength']} characters"))
        if "pattern" in node and not re.search(node["pattern"], value):
            errors.append(SpecError(path, f"must match {node['pattern']}"))
    if isinstance(value, dict):
        for key in node.get("required", []):
            if key not in value:
                errors.append(SpecError(f"{path}.{key}" if path else key, "is required"))
        props = node.get("properties", {})
        for key, sub in value.items():
            if key in props:
                check_schema(sub, props[key], f"{path}.{key}" if path else key, errors, limit)
            elif node.get("additionalProperties") is False:
                errors.append(SpecError(f"{path}.{key}" if path else key, "is not allowed"))
    if isinstance(value, (list, tuple)):
        if "minItems" in node and len(value) < node["minItems"]:
            errors.append(SpecError(path, f"needs at least {node['minItems']} items"))
        if "maxItems" in node and len(value) > node["maxItems"]:
            errors.append(SpecError(path, f"allows at most {node['maxItems']} items"))
        items = node.get("items")
        if items:
            for i, item in enumerate(value):
                check_schema(item, items, f"{path}[{i}]", errors, limit)
                if len(errors) >= limit:
                    break
    return errors


def validate_spec(data: dict[str, Any], asset_ids: set[str] | None = None, fonts: set[str] | None = None) -> list[SpecError]:
    """Schema + semantic validation of a spec document (as a dict)."""
    errors = check_schema(data, DOCUMENT_SCHEMA)
    if errors:
        return errors
    from behance_studio.design import color as C

    width = data["width"]
    seen_ids: set[str] = set()
    for si, sec in enumerate(data["sections"]):
        spath = f"sections[{si}]"
        if not C.parse_color(sec["background"]) and not str(sec["background"]).startswith(("linear-gradient", "radial-gradient")):
            errors.append(SpecError(f"{spath}.background", "is not a colour"))
        for bi, layer in enumerate(sec["blocks"]):
            lpath = f"{spath}.blocks[{bi}]"
            lid = layer.get("id")
            if lid:
                if lid in seen_ids:
                    errors.append(SpecError(f"{lpath}.id", f"duplicate layer id '{lid}'"))
                seen_ids.add(lid)
            kind = layer["kind"]
            if kind in ("image", "video") and not layer.get("asset_id"):
                errors.append(SpecError(f"{lpath}.asset_id", "media layers need an asset"))
            if asset_ids is not None:
                for key in ("asset_id", "fill_asset"):
                    ref = layer.get(key)
                    if ref and ref not in asset_ids:
                        errors.append(SpecError(f"{lpath}.{key}", f"unknown asset '{ref}'"))
            if kind == "text":
                if not layer.get("style"):
                    errors.append(SpecError(f"{lpath}.style", "text layers need a style"))
                elif fonts is not None and layer["style"]["family"] not in fonts:
                    errors.append(SpecError(f"{lpath}.style.family", f"font '{layer['style']['family']}' is not available"))
                if not layer.get("lines") and layer.get("text"):
                    errors.append(SpecError(f"{lpath}.lines", "text must be laid out into lines"))
            for key in ("fill", "mat", "tint", "edge_color", "shadow_color", "device_color"):
                value = layer.get(key)
                if value and not C.parse_color(value) and not str(value).startswith(("linear-gradient", "radial-gradient", "rgba(")):
                    errors.append(SpecError(f"{lpath}.{key}", f"'{value}' is not a colour"))
            # Generous bounds: bleeding layers may extend past the artboard,
            # but not absurdly far.
            x, y, w, h = layer["x"], layer["y"], layer["w"], layer["h"]
            if x < -width or x + w > 2 * width or y < -sec["height"] or y + h > 2 * sec["height"]:
                errors.append(SpecError(lpath, "layer lies far outside its section"))
    return errors


def to_spec(presentation: Presentation) -> dict[str, Any]:
    data = presentation.to_dict()
    data["spec_version"] = SPEC_VERSION
    return data


class SpecValidationError(ValueError):
    def __init__(self, errors: list[SpecError]) -> None:
        super().__init__("; ".join(str(e) for e in errors[:8]))
        self.errors = errors


def from_spec(data: dict[str, Any], asset_ids: set[str] | None = None, fonts: set[str] | None = None) -> Presentation:
    """Validated spec dict → Presentation (raises SpecValidationError)."""
    errors = validate_spec(data, asset_ids, fonts)
    if errors:
        raise SpecValidationError(errors)
    payload = {k: v for k, v in data.items() if k != "spec_version"}
    payload.setdefault("family", "custom")
    payload.setdefault("seed", 0)
    return Presentation.from_dict(payload)
