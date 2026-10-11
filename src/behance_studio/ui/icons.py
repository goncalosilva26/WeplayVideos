"""Minimal stroke icon set (24×24), rendered to QIcon in any colour."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from behance_studio.ui.theme import T

ICONS: dict[str, str] = {
    "home": '<path d="M4 11.5 12 5l8 6.5"/><path d="M6 10v9h12v-9"/><path d="M10 19v-5h4v5"/>',
    "folder": '<path d="M3.5 7.5a1.5 1.5 0 0 1 1.5-1.5h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    "folder-plus": '<path d="M3.5 7.5a1.5 1.5 0 0 1 1.5-1.5h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M12 11v5M9.5 13.5h5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "image": '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m20.5 16-5-5-8 8"/>',
    "images": '<rect x="6.5" y="3.5" width="14" height="12" rx="2"/><path d="M3.5 8v10a2 2 0 0 0 2 2h11"/><path d="m20.5 12.5-4-4-6 6"/>',
    "layers": '<path d="m12 4 8.5 4.5L12 13 3.5 8.5z"/><path d="m3.5 12.5 8.5 4.5 8.5-4.5"/><path d="m3.5 16.5 8.5 4.5 8.5-4.5"/>',
    "grid": '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    "compare": '<rect x="3.5" y="4.5" width="7" height="15" rx="1.5"/><rect x="13.5" y="4.5" width="7" height="15" rx="1.5"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    "export": '<path d="M12 15V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M5 13.5V18a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 18v-4.5"/>',
    "download": '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 19.5h14"/>',
    "trash": '<path d="M4.5 7h15"/><path d="M9.5 7V5h5v2"/><path d="M6.5 7l1 12.5h9l1-12.5"/><path d="M10 11v5M14 11v5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
    "sparkles": '<path d="M12 3.5l1.6 4.4 4.4 1.6-4.4 1.6L12 15.5l-1.6-4.4L6 9.5l4.4-1.6z"/><path d="M18.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "star": '<path d="m12 4 2.5 5.2 5.7.8-4.1 4 1 5.6L12 17l-5.1 2.6 1-5.6-4.1-4 5.7-.8z"/>',
    "star-filled": '<path d="m12 4 2.5 5.2 5.7.8-4.1 4 1 5.6L12 17l-5.1 2.6 1-5.6-4.1-4 5.7-.8z" fill="currentColor"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "check-circle": '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.3 2.4 2.4 4.8-5"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "chevron-left": '<path d="m14.5 6-6 6 6 6"/>',
    "chevron-right": '<path d="m9.5 6 6 6-6 6"/>',
    "chevron-down": '<path d="m6 9.5 6 6 6-6"/>',
    "arrow-up": '<path d="M12 19V5M6.5 10.5 12 5l5.5 5.5"/>',
    "arrow-down": '<path d="M12 5v14M6.5 13.5 12 19l5.5-5.5"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
    "restore": '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    "edit": '<path d="M15 5.5l3.5 3.5L9 18.5H5.5V15z"/><path d="M13 7.5l3.5 3.5"/>',
    "more": '<circle cx="6" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="18" cy="12" r="1.2" fill="currentColor"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.6-4.6"/>',
    "file-text": '<path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3.5V8h4.5"/><path d="M9 12.5h6M9 16h6"/>',
    "upload": '<path d="M12 15V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M5 19.5h14"/>',
    "maximize": '<path d="M4.5 9V4.5H9M15 4.5h4.5V9M19.5 15v4.5H15M9 19.5H4.5V15"/>',
    "minimize": '<path d="M9 4.5V9H4.5M19.5 9H15V4.5M15 19.5V15h4.5M4.5 15H9v4.5"/>',
    "zoom-in": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.6-4.6M11 8.5v5M8.5 11h5"/>',
    "zoom-out": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.6-4.6M8.5 11h5"/>',
    "fit-width": '<path d="M3.5 5v14M20.5 5v14"/><path d="M7 12h10M9.5 9.5 7 12l2.5 2.5M14.5 9.5 17 12l-2.5 2.5"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.6v.4"/>',
    "alert": '<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 16.9v.3"/>',
    "undo": '<path d="M9 7.5 4.5 12 9 16.5"/><path d="M4.5 12H15a4.5 4.5 0 0 1 0 9h-2"/>',
    "redo": '<path d="M15 7.5 19.5 12 15 16.5"/><path d="M19.5 12H9a4.5 4.5 0 0 0 0 9h2"/>',
    "external": '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5 11 13"/><path d="M17 13.5V18a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 18V8.5A1.5 1.5 0 0 1 6 7h4.5"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "palette": '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.4 0 2-1 2-2s-.7-1.5-.7-2.4.8-1.6 1.7-1.6h2a3.5 3.5 0 0 0 3.5-3.5c0-4.2-3.8-7.5-8.5-7.5z"/><circle cx="8" cy="11" r="1.1" fill="currentColor"/><circle cx="11" cy="7.5" r="1.1" fill="currentColor"/><circle cx="15.5" cy="8.5" r="1.1" fill="currentColor"/>',
    "type": '<path d="M5 7V5h14v2"/><path d="M12 5v14M9 19h6"/>',
    "monitor": '<rect x="3.5" y="4.5" width="17" height="11.5" rx="1.5"/><path d="M9 20h6M12 16v4"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z"/>',
    "heart": '<path d="M12 19.5s-7.5-4.4-7.5-10A4 4 0 0 1 12 7a4 4 0 0 1 7.5 2.5c0 5.6-7.5 10-7.5 10z"/>',
    "flag": '<path d="M5.5 20.5v-16"/><path d="M5.5 4.5h11l-2 4 2 4h-11"/>',
    "drag": '<circle cx="9" cy="7" r="1" fill="currentColor"/><circle cx="15" cy="7" r="1" fill="currentColor"/><circle cx="9" cy="12" r="1" fill="currentColor"/><circle cx="15" cy="12" r="1" fill="currentColor"/><circle cx="9" cy="17" r="1" fill="currentColor"/><circle cx="15" cy="17" r="1" fill="currentColor"/>',
    "eye-off": '<path d="M4 4l16 16"/><path d="M9.9 6A9.6 9.6 0 0 1 12 5.5C18 5.5 21.5 12 21.5 12a17 17 0 0 1-3 3.8M6.4 7.6A17 17 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 4-.9"/>',
    "wand": '<path d="m4.5 19.5 11-11"/><path d="m14 6 2.5 2.5"/><path d="M17.5 3.5v2M16.5 4.5h2M20 9v1.6M19.2 9.8h1.6"/>',
    "cpu": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/><path d="M10 3v3.5M14 3v3.5M10 17.5V21M14 17.5V21M3 10h3.5M3 14h3.5M17.5 10H21M17.5 14H21"/>',
}

LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="4" y="4" width="56" height="56" rx="16" fill="#5B7CFA"/>
<rect x="17" y="15" width="14" height="34" rx="3" fill="#FFFFFF"/>
<rect x="35" y="15" width="13" height="15" rx="6.5" fill="#FFFFFF" fill-opacity="0.92"/>
<rect x="35" y="34" width="13" height="15" rx="3" fill="#FFFFFF" fill-opacity="0.65"/>
</svg>"""


def _svg(name: str, color: str) -> bytes:
    body = ICONS.get(name, ICONS["info"]).replace("currentColor", color)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


def _render(svg: bytes, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QPixmap.fromImage(image)


@lru_cache(maxsize=512)
def icon(name: str, color: str = T.text2, active: str | None = None) -> QIcon:
    result = QIcon()
    for size in (16, 20, 24, 32, 48):
        result.addPixmap(_render(_svg(name, color), size), QIcon.Mode.Normal, QIcon.State.Off)
        result.addPixmap(_render(_svg(name, active or T.text), size), QIcon.Mode.Active, QIcon.State.Off)
        result.addPixmap(_render(_svg(name, active or T.text), size), QIcon.Mode.Normal, QIcon.State.On)
        result.addPixmap(_render(_svg(name, T.text3), size), QIcon.Mode.Disabled, QIcon.State.Off)
    return result


def pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    return _render(_svg(name, color), size)


@lru_cache(maxsize=4)
def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(_render(LOGO_SVG.encode(), size))
    return result


def logo_pixmap(size: int) -> QPixmap:
    return _render(LOGO_SVG.encode(), size)


ICON_SIZE = QSize(18, 18)
