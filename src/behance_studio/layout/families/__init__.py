"""Registry of layout families: the five 2.0 concepts and the six classic layouts."""

from __future__ import annotations

from behance_studio.layout.families.base import FamilyInfo, LayoutFamily

_REGISTRY: dict[str, type[LayoutFamily]] = {}


def register(cls: type[LayoutFamily]) -> type[LayoutFamily]:
    _REGISTRY[cls.info.id] = cls
    return cls


def _load() -> None:
    if _REGISTRY:
        return
    import importlib

    try:
        concepts = importlib.import_module("behance_studio.layout.families.concepts")
        for cls_name in ("MinimalConcept", "BoldConcept", "PhotoConcept", "LayeredConcept", "StoryConcept"):
            register(getattr(concepts, cls_name))
    except ModuleNotFoundError:  # pragma: no cover
        pass
    modules = {
        "editorial": "EditorialFamily",
        "cinematic": "CinematicFamily",
        "split": "SplitFamily",
        "posters": "PostersFamily",
        "gallery": "GalleryFamily",
        "modular": "ModularFamily",
    }
    for module, cls_name in modules.items():
        try:
            mod = importlib.import_module(f"behance_studio.layout.families.{module}")
        except ModuleNotFoundError:  # pragma: no cover - during incremental development
            continue
        register(getattr(mod, cls_name))


CONCEPT_FAMILIES = ["minimal", "bold", "photo", "layered", "story"]
CLASSIC_FAMILIES = ["editorial", "cinematic", "split", "posters", "gallery", "modular"]
FAMILY_ORDER = CONCEPT_FAMILIES + CLASSIC_FAMILIES


def is_concept(family_id: str) -> bool:
    return family_id in CONCEPT_FAMILIES


def get_family(family_id: str) -> LayoutFamily:
    _load()
    cls = _REGISTRY.get(family_id)
    if cls is None:
        raise KeyError(f"Unknown layout family: {family_id}")
    return cls()


def family_info(family_id: str) -> FamilyInfo:
    _load()
    return _REGISTRY[family_id].info


def available_families() -> list[str]:
    _load()
    return [f for f in FAMILY_ORDER if f in _REGISTRY]
