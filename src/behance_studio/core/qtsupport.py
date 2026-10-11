"""Helpers for using Qt's non-widget modules (QtSvg, QtGui) from the core.

QtSvg needs a ``QGuiApplication`` for font handling. The desktop app already
creates a ``QApplication``; command-line and test runs create a headless one.
"""

from __future__ import annotations

import os
import sys
import threading

_lock = threading.Lock()


def ensure_gui_application() -> bool:
    """Make sure a Q(Gui)Application exists. Returns False if impossible here."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QGuiApplication

    with _lock:
        app = QCoreApplication.instance()
        if app is not None:
            return isinstance(app, QGuiApplication)
        if threading.current_thread() is not threading.main_thread():
            return False
        if not sys.platform.startswith("win") and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QGuiApplication(sys.argv[:1] or ["behance-studio"])
        return True
