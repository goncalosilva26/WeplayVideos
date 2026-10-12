"""Supported file formats and content sniffing."""

from __future__ import annotations

from pathlib import Path

from behance_studio.projects.models import (
    MEDIA_DOCUMENT,
    MEDIA_GIF,
    MEDIA_IMAGE,
    MEDIA_SVG,
    MEDIA_VIDEO,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
GIF_EXTENSIONS = {".gif"}
SVG_EXTENSIONS = {".svg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
DOCUMENT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".pdf"}

# Formats Chromium renders natively in <img>.
BROWSER_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg"}

SUPPORTED_EXTENSIONS = (
    IMAGE_EXTENSIONS | GIF_EXTENSIONS | SVG_EXTENSIONS | VIDEO_EXTENSIONS | DOCUMENT_EXTENSIONS
)

FILE_DIALOG_FILTER = (
    "Supported files (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp *.gif *.svg "
    "*.mp4 *.mov *.webm *.m4v *.txt *.md *.json *.pdf *.zip);;"
    "ZIP archives (*.zip);;"
    "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp *.gif *.svg);;"
    "Video (*.mp4 *.mov *.webm *.m4v);;"
    "Documents (*.txt *.md *.json *.pdf);;All files (*)"
)

BRIEF_NAMES = {"brief", "briefing", "creative brief", "creative-brief", "creative_brief", "brief do projeto"}
SCRIPT_NAMES = {
    "guiao_projeto",
    "guiao projeto",
    "guião_projeto",
    "guião projeto",
    "guiao",
    "guião",
    "project script",
    "project_script",
    "script",
    "roteiro",
}


def media_type_for(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return MEDIA_IMAGE
    if ext in GIF_EXTENSIONS:
        return MEDIA_GIF
    if ext in SVG_EXTENSIONS:
        return MEDIA_SVG
    if ext in VIDEO_EXTENSIONS:
        return MEDIA_VIDEO
    if ext in DOCUMENT_EXTENSIONS:
        return MEDIA_DOCUMENT
    return None


def sniff_media_type(path: Path) -> str | None:
    """Detect the real type from the file header (extensions can lie)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
    except OSError:
        return None
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG") or head[:4] in (b"II*\x00", b"MM\x00*"):
        return MEDIA_IMAGE
    if head.startswith(b"BM"):
        return MEDIA_IMAGE
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return MEDIA_IMAGE
    if head.startswith((b"GIF87a", b"GIF89a")):
        return MEDIA_GIF
    if head[4:8] == b"ftyp" or head[4:8] in (b"moov", b"mdat", b"wide", b"free"):
        return MEDIA_VIDEO
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return MEDIA_VIDEO
    if head.startswith(b"%PDF"):
        return MEDIA_DOCUMENT
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith((b"<svg", b"<?xml", b"<!DOCTYPE svg", b"<!--")):
        return MEDIA_SVG if path.suffix.lower() == ".svg" or b"svg" in head.lower() else None
    return None


def classify_text_file(path: Path) -> str | None:
    """Return 'brief' or 'script' when a text file is a recognised project document."""
    if path.suffix.lower() not in {".txt", ".md", ".markdown", ".json"}:
        return None
    stem = path.stem.strip().lower().replace("-", "_")
    normalized = stem.replace("_", " ")
    if stem in SCRIPT_NAMES or normalized in SCRIPT_NAMES or stem.startswith(("guiao", "guião")):
        return "script"
    if stem in BRIEF_NAMES or normalized in BRIEF_NAMES or stem.startswith("brief"):
        return "brief"
    return None
