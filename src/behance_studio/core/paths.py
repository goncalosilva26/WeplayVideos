"""Filesystem locations used by the application.

All locations can be redirected with the ``BEHANCE_STUDIO_HOME`` environment
variable, which the test-suite uses to keep runs isolated from real user data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from behance_studio import APP_ID

PACKAGE_DIR = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PACKAGE_DIR / "resources"
FONTS_DIR = RESOURCES_DIR / "fonts"
ICONS_DIR = RESOURCES_DIR / "icons"


def _home_override() -> Path | None:
    value = os.environ.get("BEHANCE_STUDIO_HOME")
    return Path(value).expanduser().resolve() if value else None


def user_data_dir() -> Path:
    """Directory for settings, the project library database and logs."""
    override = _home_override()
    if override:
        path = override / "appdata"
    elif sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_ID
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_ID
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_cache_dir() -> Path:
    override = _home_override()
    if override:
        path = override / "cache"
    elif sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_ID / "Cache"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def documents_dir() -> Path:
    if sys.platform.startswith("win"):
        try:  # Resolve the real (possibly redirected) Documents folder.
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5, SHGFP_TYPE_CURRENT = 0
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            if buf.value:
                return Path(buf.value)
        except Exception:  # pragma: no cover - platform specific
            pass
    return Path.home() / "Documents"


def default_projects_dir() -> Path:
    override = _home_override()
    if override:
        return override / "Behance Studio Projects"
    return documents_dir() / "Behance Studio Projects"
