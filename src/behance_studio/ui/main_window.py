"""Main window: sidebar navigation, page stack and global shortcuts."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from behance_studio import APP_NAME, __version__
from behance_studio.core.logging_setup import get_logger
from behance_studio.ui.actions import Actions
from behance_studio.ui.dialogs.messages import confirm
from behance_studio.ui.icons import icon, logo_pixmap
from behance_studio.ui.pages.compare import ComparePage
from behance_studio.ui.pages.dashboard import DashboardPage
from behance_studio.ui.pages.export_page import ExportPage
from behance_studio.ui.pages.gallery import GalleryPage
from behance_studio.ui.pages.settings_page import SettingsPage
from behance_studio.ui.pages.trash_page import TrashPage
from behance_studio.ui.pages.viewer import ViewerPage
from behance_studio.ui.pages.workspace import WorkspacePage
from behance_studio.ui.state import AppState
from behance_studio.ui.theme import T
from behance_studio.ui.widgets.common import Toast, label

log = get_logger(__name__)

# (page id, label, icon, needs an open project, shortcut)
NAV = [
    ("dashboard", "Home", "home", False, "Ctrl+1"),
    ("workspace", "Project", "folder", True, "Ctrl+2"),
    ("gallery", "Proposals", "grid", True, "Ctrl+3"),
    ("viewer", "Viewer", "eye", True, "Ctrl+4"),
    ("compare", "Compare", "compare", True, "Ctrl+5"),
    ("export", "Export", "export", True, "Ctrl+6"),
    ("trash", "Trash", "trash", True, "Ctrl+7"),
    ("settings", "Settings", "settings", False, "Ctrl+8"),
]


class ProjectChip(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ProjectChip")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(1)
        lay.addWidget(label("CURRENT PROJECT", "Eyebrow"))
        self.name = label("No project open", "H3")
        self.meta = label("", "Faint")
        lay.addWidget(self.name)
        lay.addWidget(self.meta)

    def set_project(self, project, assets: int = 0, proposals: int = 0) -> None:
        if project is None:
            self.name.setText("No project open")
            self.meta.setText("Create or open a project")
            return
        metrics = self.name.fontMetrics()
        self.name.setText(metrics.elidedText(project.name, Qt.TextElideMode.ElideRight, 180))
        self.name.setToolTip(str(project.root))
        self.meta.setText(f"{assets} asset{'s' if assets != 1 else ''} · {proposals} proposal{'s' if proposals != 1 else ''}")


class Sidebar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(232)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(2)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(30))
        logo.setFixedSize(30, 30)
        brand.addWidget(logo)
        words = QVBoxLayout()
        words.setSpacing(0)
        title = label("Behance Studio", "H3")
        words.addWidget(title)
        words.addWidget(label("Presentation generator", "Faint"))
        brand.addLayout(words, 1)
        lay.addLayout(brand)
        lay.addSpacing(16)

        self.chip = ProjectChip()
        lay.addWidget(self.chip)
        lay.addSpacing(8)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        sections = {"dashboard": "", "workspace": "WORK", "trash": "LIBRARY"}
        for page_id, text, icon_name, _needs, shortcut in NAV:
            if sections.get(page_id):
                lay.addWidget(label(sections[page_id], "NavSection"))
            btn = QPushButton(f"  {text}")
            btn.setObjectName("NavButton")
            btn.setIcon(icon(icon_name, T.text2, T.text))
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{text}  ({shortcut})")
            self.group.addButton(btn)
            self.buttons[page_id] = btn
            lay.addWidget(btn)
        lay.addStretch(1)
        self.status = label("", "Faint", wrap=True)
        lay.addWidget(self.status)
        lay.addWidget(label(f"Version {__version__}", "Faint"))


class MainWindow(QMainWindow):
    def __init__(self, state: AppState | None = None) -> None:
        super().__init__()
        self.state = state or AppState()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 700)
        self.toast_widget: Toast | None = None

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.toast_widget = Toast(central)

        self.actions = Actions(self.state, self, self.toast)
        s, a = self.state, self.actions
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(s, a),
            "workspace": WorkspacePage(s, a),
            "gallery": GalleryPage(s, a),
            "viewer": ViewerPage(s, a),
            "compare": ComparePage(s, a, self.toast),
            "export": ExportPage(s, a, self.toast),
            "trash": TrashPage(s, a, self.toast),
            "settings": SettingsPage(s, a, self.toast),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        for page_id, btn in self.sidebar.buttons.items():
            btn.clicked.connect(lambda _c=False, p=page_id: self.show_page(p))

        s.navigate.connect(self.show_page)
        s.open_version.connect(self._open_version)
        s.compare_versions.connect(self._compare)
        s.export_versions.connect(self._export)
        s.project_changed.connect(self._project_changed)
        s.assets_changed.connect(self._update_chip)
        s.versions_changed.connect(self._update_chip)
        s.busy_changed.connect(self._busy)

        for page_id, _t, _i, _n, shortcut in NAV:
            QShortcut(QKeySequence(shortcut), self, activated=lambda p=page_id: self.show_page(p))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=a.new_project)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=a.open_project_dialog)
        QShortcut(QKeySequence("Ctrl+I"), self, activated=lambda: s.project and a.add_assets_dialog())
        QShortcut(QKeySequence("Ctrl+G"), self, activated=lambda: s.project and a.generate())
        QShortcut(QKeySequence("Ctrl+E"), self, activated=lambda: s.project and self.show_page("export"))

        self._project_changed(None)
        self.show_page("dashboard")
        self._restore_geometry()

    # ------------------------------------------------------------ helpers
    def toast(self, text: str) -> None:
        if self.toast_widget is not None:
            self.toast_widget.show_message(text)

    def current_page_id(self) -> str:
        current = self.stack.currentWidget()
        return next((k for k, v in self.pages.items() if v is current), "dashboard")

    def show_page(self, page_id: str) -> None:
        if page_id not in self.pages:
            return
        needs = next(n for p, _t, _i, n, _s in NAV if p == page_id)
        if needs and self.state.project is None:
            page_id = "dashboard"
        self.stack.setCurrentWidget(self.pages[page_id])
        self.sidebar.buttons[page_id].setChecked(True)

    def _open_version(self, version_id: str) -> None:
        self.show_page("viewer")
        self.pages["viewer"].show_version(version_id)

    def _compare(self, ids: list) -> None:
        self.pages["compare"].show_versions(list(ids))
        self.show_page("compare")

    def _export(self, ids: list) -> None:
        self.pages["export"].preselect(list(ids))
        self.show_page("export")

    def _project_changed(self, project) -> None:
        for page_id, _t, _i, needs, _s in NAV:
            self.sidebar.buttons[page_id].setEnabled(not needs or project is not None)
        title = f"{project.name} — {APP_NAME}" if project is not None else APP_NAME
        self.setWindowTitle(title)
        self._update_chip()
        if project is None and self.current_page_id() not in ("dashboard", "settings"):
            self.show_page("dashboard")

    def _update_chip(self) -> None:
        project = self.state.project
        if project is None:
            self.sidebar.chip.set_project(None)
            return
        try:
            assets = len(project.list_assets())
            manager = self.state.versions
            proposals = len(manager.list()) if manager else 0
        except Exception as exc:  # noqa: BLE001 - the chip is informational
            log.warning("Could not count project contents: %s", exc)
            assets = proposals = 0
        self.sidebar.chip.set_project(project, assets, proposals)

    def _busy(self, busy: bool) -> None:
        self.sidebar.status.setText("Working in the background…" if busy else "")

    # ----------------------------------------------------------- geometry
    def _restore_geometry(self) -> None:
        geometry = self.state.settings.window_geometry
        restored = False
        if geometry:
            try:
                restored = self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception:  # noqa: BLE001 - corrupt value, ignore
                restored = False
        if not restored:
            self.resize(1440, 900)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.toast_widget is not None and self.toast_widget.isVisible():
            QTimer.singleShot(0, self.toast_widget.reposition)

    def closeEvent(self, event) -> None:  # noqa: N802
        runner = self.state.runner
        if runner.busy:
            if not confirm(self, "Work in progress", "A task is still running. Stop it and quit?", "Stop and quit", destructive=True):
                event.ignore()
                return
            runner.cancel_all()
            runner.wait(5000)
        try:
            self.state.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.state.settings_store.save()
            self.state.touch_library()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not save window state: %s", exc)
        super().closeEvent(event)
