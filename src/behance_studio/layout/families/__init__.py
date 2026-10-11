"""Registry of the six layout families."""

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


FAMILY_ORDER = ["editorial", "cinematic", "split", "posters", "gallery", "modular"]


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
