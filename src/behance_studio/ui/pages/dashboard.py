"""Dashboard: start new work, reopen projects, recent presentations and exports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QScrollArea, QVBoxLayout, QWidget

from behance_studio.core.errors import UserFacingError
from behance_studio.export.exporter import open_folder
from behance_studio.layout.families import family_info
from behance_studio.projects.library import LibraryEntry
from behance_studio.projects.store import Project
from behance_studio.projects.versions import VersionManager
from behance_studio.ui.dialogs.messages import confirm, show_error
from behance_studio.ui.icons import logo_pixmap, pixmap
from behance_studio.ui.theme import FAMILY_COLORS, T
from behance_studio.ui.widgets.common import Badge, Card, EmptyState, FlowLayout, Thumb, button, clear_layout, label


def _when(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return ""
    delta = datetime.now(dt.tzinfo) - dt
    if delta.days == 0:
        return f"Today, {dt:%H:%M}"
    if delta.days == 1:
        return "Yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    return f"{dt:%d %b %Y}"


class ActionCard(Card):
    def __init__(self, icon_name: str, title: str, text: str, primary: bool = False) -> None:
        super().__init__()
        self.setFixedSize(250, 128)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        ic = label()
        ic.setPixmap(pixmap(icon_name, "#FFFFFF" if primary else T.text, 22))
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(f"background:{T.accent if primary else T.surface3};border-radius:11px;")
        lay.addWidget(ic)
        lay.addSpacing(4)
        lay.addWidget(label(title, "H3"))
        lay.addWidget(label(text, "Faint", wrap=True))


class ProjectCard(Card):
    def __init__(self, entry: LibraryEntry) -> None:
        super().__init__()
        self.entry = entry
        self.setFixedSize(264, 248)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 12)
        lay.setSpacing(6)
        thumb = Thumb(244, 160, radius=8)
        if entry.thumbnail and Path(entry.thumbnail).exists():
            thumb.set_path(entry.thumbnail)
        else:
            thumb.set_overlay("No proposals yet")
        lay.addWidget(thumb)
        lay.addSpacing(2)
        lay.addWidget(label(entry.name, "H3"))
        meta = f"{entry.proposals} proposal{'s' if entry.proposals != 1 else ''} · {_when(entry.last_opened)}"
        lay.addWidget(label(meta, "Faint"))


class PresentationCard(Card):
    def __init__(self, project_path: str, version_id: str, name: str, family: str, thumb_path: Path) -> None:
        super().__init__()
        self.project_path, self.version_id = project_path, version_id
        self.setFixedSize(220, 196)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 10)
        lay.setSpacing(5)
        t = Thumb(204, 132, radius=7)
        t.set_path(thumb_path)
        lay.addWidget(t)
        lay.addWidget(label(name, "H3"))
        row = QHBoxLayout()
        row.addWidget(Badge(family_info(family).name, FAMILY_COLORS.get(family)))
        row.addStretch(1)
        lay.addLayout(row)


class DashboardPage(QWidget):
    def __init__(self, state, actions) -> None:
        super().__init__()
        self.state, self.actions = state, actions
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(40, 34, 40, 40)
        self.lay.setSpacing(14)

        hero = QHBoxLayout()
        logo = label()
        logo.setPixmap(logo_pixmap(52))
        hero.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        hero.addSpacing(10)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(label("BEHANCE STUDIO", "Eyebrow"))
        texts.addWidget(label("Raw material in. Portfolio-ready presentations out.", "Display"))
        count = max(1, int(getattr(self.state.settings, "proposal_count", 5) or 5))
        texts.addWidget(label(f"Import a project folder, let the studio design {count} complete presentations, compare them, refine, export.", "Muted", wrap=True))
        hero.addLayout(texts, 1)
        self.lay.addLayout(hero)
        self.lay.addSpacing(14)

        cards = FlowLayout(spacing=14)
        holder = QWidget()
        holder.setLayout(cards)
        for icon_name, title, text, primary, fn in (
            ("sparkles", "New project", "Name it, drop your assets, generate.", True, lambda: self.actions.new_project()),
            ("folder", "Open project", "Continue an existing project.", False, self.actions.open_project_dialog),
            ("folder-plus", "Import a folder", "Turn a delivery folder into a project.", False, self.actions.import_folder_as_project),
            ("wand", "Demo project", "Try the Butter & Bean showcase.", False, self.actions.create_demo),
        ):
            card = ActionCard(icon_name, title, text, primary)
            card.clicked.connect(fn)
            cards.addWidget(card)
        self.lay.addWidget(holder)

        self.lay.addSpacing(18)
        head = QHBoxLayout()
        head.addWidget(label("Recent projects", "H2"))
        head.addStretch(1)
        self.lay.addLayout(head)
        self.projects_holder = QWidget()
        self.projects_flow = FlowLayout(spacing=16)
        self.projects_holder.setLayout(self.projects_flow)
        self.lay.addWidget(self.projects_holder)

        self.lay.addSpacing(18)
        self.lay.addWidget(label("Recent presentations", "H2"))
        self.presentations_holder = QWidget()
        self.presentations_flow = FlowLayout(spacing=14)
        self.presentations_holder.setLayout(self.presentations_flow)
        self.lay.addWidget(self.presentations_holder)

        self.lay.addSpacing(18)
        self.lay.addWidget(label("Recent exports", "H2"))
        self.exports_box = QVBoxLayout()
        self.exports_box.setSpacing(4)
        self.lay.addLayout(self.exports_box)
        self.lay.addStretch(1)
        state.project_changed.connect(lambda _p: self.refresh())
        state.versions_changed.connect(self.refresh)

    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(event)

    def refresh(self) -> None:
        self.projects_flow.clear()
        self.presentations_flow.clear()
        clear_layout(self.exports_box)
        entries = self.state.library.recent(limit=24)
        if not entries:
            self.projects_flow.addWidget(EmptyState("folder", "No projects yet", "Create a project or try the Butter & Bean demo to see what Behance Studio can do."))
        recent_versions = []
        exports = []
        for entry in entries:
            card = ProjectCard(entry)
            card.clicked.connect(lambda e=entry: self.actions.open_project(Path(e.path)))
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(lambda pos, e=entry, c=card: self._project_menu(e, c.mapToGlobal(pos)))
            self.projects_flow.addWidget(card)
            if len(recent_versions) < 8:
                try:
                    project = Project.open(Path(entry.path))
                    manager = VersionManager(project)
                    for v in sorted(manager.list(), key=lambda v: v.created_at, reverse=True)[:3]:
                        recent_versions.append((entry, v, manager.thumb_path(v)))
                    for rec in project.list_exports()[:3]:
                        exports.append((entry, rec))
                except Exception:  # noqa: BLE001 - a broken project must not break the dashboard
                    continue
        for entry, v, thumb in recent_versions[:8]:
            card = PresentationCard(entry.path, v.id, v.name, v.family, thumb)
            card.clicked.connect(lambda e=entry, vid=v.id: self._open_version(e, vid))
            self.presentations_flow.addWidget(card)
        if not recent_versions:
            self.presentations_flow.addWidget(label("Generated proposals will appear here.", "Faint"))
        exports.sort(key=lambda er: er[1].created_at, reverse=True)
        for entry, rec in exports[:6]:
            row = QHBoxLayout()
            row.addWidget(label(f"{rec.format.upper():7}", "Badge"))
            row.addWidget(label(f"{Path(rec.path).name}", None), 1)
            row.addWidget(label(f"{entry.name} · {_when(rec.created_at)}", "Faint"))
            folder = Path(rec.path).parent if Path(rec.path).is_file() or not Path(rec.path).is_dir() else Path(rec.path)
            row.addWidget(button("Open folder", "folder", "Ghost", on_click=lambda _=False, f=folder: open_folder(f)))
            self.exports_box.addLayout(row)
        if not exports:
            self.exports_box.addWidget(label("Exports will be listed here for quick access.", "Faint"))

    def _open_version(self, entry: LibraryEntry, version_id: str) -> None:
        self.actions.open_project(Path(entry.path))
        if self.state.project is not None:
            self.state.open_version.emit(version_id)

    def _project_menu(self, entry: LibraryEntry, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.actions.open_project(Path(entry.path)))
        menu.addAction("Show in folder", lambda: open_folder(Path(entry.path)))
        menu.addSeparator()
        menu.addAction("Remove from recent list", lambda: (self.state.library.forget(entry.path), self.refresh()))
        menu.addAction("Delete project…", lambda: self._delete_project(entry))
        menu.exec(pos)

    def _delete_project(self, entry: LibraryEntry) -> None:
        if not confirm(self, "Delete project", f"Move the project “{entry.name}” to the Recycle Bin?", "Move to Recycle Bin", destructive=True,
                       detail="The whole project folder (copied assets, proposals and exports) is moved to the system Recycle Bin and can be restored from there. Your original source files are not affected."):
            return
        try:
            from send2trash import send2trash

            if self.state.project is not None and Path(self.state.project.root).resolve() == Path(entry.path).resolve():
                self.state.set_project(None)
            send2trash(entry.path)
            self.state.library.forget(entry.path)
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            show_error(self, UserFacingError("The project could not be moved to the Recycle Bin.", str(exc)))
