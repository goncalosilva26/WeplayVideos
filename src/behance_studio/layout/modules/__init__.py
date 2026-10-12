"""Art-directed composition modules (Design Spec v2 engine)."""

from behance_studio.layout.modules import imagery as _imagery  # noqa: F401 - registers modules
from behance_studio.layout.modules.identity import MODULES

# Modules that render the section's own text fields (title/subtitle/body).
TEXT_MODULES = {"cover_logo", "cover_hero", "cover_split", "statement", "quote_band", "chapter", "split_feature", "closing", "mark_feature", "collage", "type_specimen"}

__all__ = ["MODULES", "TEXT_MODULES"]
