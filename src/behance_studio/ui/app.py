"""Desktop application bootstrap."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from behance_studio import APP_ID, APP_NAME, __version__
from behance_studio.core.logging_setup import get_logger, log_file_path, setup_logging

log = get_logger(__name__)


def _windows_app_id() -> None:
    """Give the process its own taskbar identity (icon grouping on Windows)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.Desktop.{__version__}")
        except Exception:  # noqa: BLE001
            pass


def _fatal(message: str) -> None:
    """Report a startup failure even without a console (pythonw.exe)."""
    log.critical(message)
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, f"{message}\n\nLog: {log_file_path()}", APP_NAME, 0x10)
        except Exception:  # noqa: BLE001
            pass


def _excepthook(exc_type, exc, tb) -> None:
    log.critical("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
    if issubclass(exc_type, KeyboardInterrupt):
        return
    try:
        from PySide6.QtWidgets import QApplication

        from behance_studio.ui.dialogs.messages import show_error

        if QApplication.instance() is not None:
            show_error(QApplication.activeWindow(), exc, "Unexpected error")
    except Exception:  # noqa: BLE001 - never raise from the hook
        pass


def create_application(argv: list[str]):
    """Create the QApplication with the settings Qt WebEngine needs."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    # Local preview pages load fonts and images from the project folder.
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-gpu-shader-disk-cache" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu-shader-disk-cache").strip()

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401 - must load before QApplication
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    from behance_studio.ui.icons import app_icon
    from behance_studio.ui.theme import apply_theme

    apply_theme(app)
    app.setWindowIcon(app_icon())
    return app


def run(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    setup_logging(console=bool(os.environ.get("BEHANCE_STUDIO_CONSOLE_LOG")))
    log.info("Starting %s %s (Python %s, %s)", APP_NAME, __version__, sys.version.split()[0], sys.platform)
    _windows_app_id()
    try:
        app = create_application(argv)
    except ImportError as exc:
        log.exception("Startup import failure")
        _fatal(f"{APP_NAME} could not start because a component is missing ({exc}).\nRun setup_windows.bat again to repair the installation.")
        return 2
    sys.excepthook = _excepthook

    from behance_studio.ui.main_window import MainWindow
    from behance_studio.ui.state import AppState

    try:
        state = AppState()
        window = MainWindow(state)
    except Exception as exc:  # noqa: BLE001
        log.exception("Main window failed to open")
        _fatal(f"{APP_NAME} could not open its window: {exc}")
        return 3
    window.show()
    state.refresh_local_ai()

    # Ctrl+C in a console (BehanceStudio_debug.bat) closes the window normally.
    import signal

    from PySide6.QtCore import QTimer

    signal.signal(signal.SIGINT, lambda *_a: window.close())
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)  # lets Python handle signals during the Qt loop
    heartbeat.start(400)

    # Open a project folder passed on the command line (e.g. "Open with").
    paths = [Path(a) for a in argv[1:] if not a.startswith("-")]
    if paths and (paths[0] / "project.json").exists():
        window.actions.open_project(paths[0])
    elif paths and paths[0].exists():
        window.actions.new_project([str(p) for p in paths], name=paths[0].stem)

    code = app.exec()
    log.info("Exiting (%s); log: %s", code, log_file_path())
    if state.runner.busy:
        # A task that ignored cancellation would keep Qt's thread pool (and a
        # windowless process) alive. Project data and PDFs are written
        # atomically; at worst an interrupted image export leaves an
        # incomplete file in the export folder (the user chose "Stop and quit").
        import logging

        log.warning("Background work still running at exit; ending the process.")
        logging.shutdown()
        os._exit(code)
    return code
