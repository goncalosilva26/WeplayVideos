"""Structured logging to a rotating diagnostics file.

Ordinary users never see tracebacks; dialogs show friendly messages and the
technical details are written here (Settings → Diagnostics opens the folder).
"""

from __future__ import annotations

import logging
import logging.handlers
import platform
import sys

from behance_studio import APP_NAME, __version__
from behance_studio.core.paths import logs_dir

_CONFIGURED = False


def log_file_path():
    return logs_dir() / "behance_studio.log"


def setup_logging(level: int = logging.INFO, console: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("behance_studio")
    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
    )
    try:
        handler = logging.handlers.RotatingFileHandler(
            log_file_path(), maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except OSError:  # pragma: no cover - read-only profile, etc.
        pass
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        root.addHandler(stream)
    _CONFIGURED = True
    root.info(
        "%s %s starting on %s, Python %s",
        APP_NAME,
        __version__,
        platform.platform(),
        sys.version.split()[0],
    )


def get_logger(name: str) -> logging.Logger:
    if not name.startswith("behance_studio"):
        name = f"behance_studio.{name}"
    return logging.getLogger(name)
