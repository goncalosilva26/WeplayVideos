"""New project: name, assets, optional brief and script — nothing else."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from behance_studio.assets.formats import FILE_DIALOG_FILTER
from behance_studio.brief.script import script_template
from behance_studio.core.fsutil import read_text_file
from behance_studio.ui.icons import icon
from behance_studio.ui.widgets.common import DropZone, button, label


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None, projects_dir: Path, initial_paths: list[str] | None = None, name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.setMinimumSize(640, 640)
        self.projects_dir = projects_dir
        self.paths: list[str] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(12)
        lay.addWidget(label("New project", "H1"))
        lay.addWidget(label("Add your raw project material. Behance Studio organises, analyses and designs the presentation for you.", "Muted", wrap=True))

        lay.addWidget(label("Project name", "H3"))
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("e.g. Butter & Bean")
        lay.addWidget(self.name)

        loc = QHBoxLayout()
        self.location = label(str(projects_dir), "Faint")
        loc.addWidget(self.location, 1)
        change = QPushButton("Change…")
        change.setObjectName("Ghost")
        change.clicked.connect(self._choose_location)
        loc.addWidget(change)
        lay.addLayout(loc)

        tabs = QTabWidget()
        assets_tab = QWidget()
        at = QVBoxLayout(assets_tab)
        at.setContentsMargins(0, 10, 0, 0)
        self.drop = DropZone(height=130)
        self.drop.paths_dropped.connect(self.add_paths)
        self.drop.clicked.connect(self._add_files)
        at.addWidget(self.drop)
        row = QHBoxLayout()
        row.addWidget(button("Add files…", "image", on_click=self._add_files))
        row.addWidget(button("Add folder…", "folder", on_click=self._add_folder))
        row.addStretch(1)
        self.count = label("", "Faint")
        row.addWidget(self.count)
        at.addLayout(row)
        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        at.addWidget(self.list)
        tabs.addTab(assets_tab, "Assets")

        brief_tab = QWidget()
        bt = QVBoxLayout(brief_tab)
        bt.setContentsMargins(0, 10, 0, 0)
        bt.addWidget(label("Optional. Describe the brand, audience, mood, colours and fonts — it guides the visual direction.", "Faint", wrap=True))
        self.brief = QPlainTextEdit()
        self.brief.setPlaceholderText("Brand personality: warm, welcoming, slightly playful\nColours: #2E1F17, #F4C95D\nTypography: Fraunces for headings, Manrope for body copy")
        bt.addWidget(self.brief, 1)
        bt.addWidget(button("Load brief.txt…", "file-text", on_click=lambda: self._load_text(self.brief)), 0, Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(brief_tab, "Creative brief")

        script_tab = QWidget()
        st = QVBoxLayout(script_tab)
        st.setContentsMargins(0, 10, 0, 0)
        st.addWidget(label("Optional. A GUIAO_PROJETO.txt script fixes sections, exact text, image assignments and order.", "Faint", wrap=True))
        self.script = QPlainTextEdit()
        self.script.setPlaceholderText("## Cover\nTITLE: …\nIMAGES: hero.jpg")
        st.addWidget(self.script, 1)
        srow = QHBoxLayout()
        srow.addWidget(button("Load GUIAO_PROJETO.txt…", "file-text", on_click=lambda: self._load_text(self.script)))
        srow.addWidget(button("Insert template", "plus", "Ghost", on_click=self._template))
        srow.addStretch(1)
        st.addLayout(srow)
        tabs.addTab(script_tab, "Project script")
        lay.addWidget(tabs, 1)

        opts = QHBoxLayout()
        opts.addWidget(label("Presentation language", "Muted"))
        self.language = QComboBox()
        self.language.addItem("Automatic", "auto")
        self.language.addItem("English", "en")
        self.language.addItem("Português", "pt")
        opts.addWidget(self.language)
        opts.addStretch(1)
        self.generate = QCheckBox("Generate proposals right away")
        self.generate.setChecked(True)
        opts.addWidget(self.generate)
        lay.addLayout(opts)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.create = QPushButton("Create project")
        self.create.setObjectName("Primary")
        self.create.setIcon(icon("sparkles", "#FFFFFF", "#FFFFFF"))
        self.create.clicked.connect(self._accept)
        buttons.addWidget(self.create)
        lay.addLayout(buttons)
        if initial_paths:
            self.add_paths(initial_paths)
        self.name.textChanged.connect(self._validate)
        self._validate()

    def _validate(self) -> None:
        self.create.setEnabled(bool(self.name.text().strip()))

    def _choose_location(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Projects folder", str(self.projects_dir))
        if folder:
            self.projects_dir = Path(folder)
            self.location.setText(folder)

    def add_paths(self, paths: list[str]) -> None:
        for p in paths:
            if p not in self.paths:
                self.paths.append(p)
                item_text = f"📁  {p}" if Path(p).is_dir() else Path(p).name
                self.list.addItem(item_text)
        if not self.name.text().strip() and len(paths) == 1 and Path(paths[0]).is_dir():
            self.name.setText(Path(paths[0]).name)
        self.count.setText(f"{len(self.paths)} item(s)")

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add assets", "", FILE_DIALOG_FILTER)
        if files:
            self.add_paths(files)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a folder of assets")
        if folder:
            self.add_paths([folder])

    def _load_text(self, editor: QPlainTextEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open text file", "", "Text (*.txt *.md *.json);;All files (*)")
        if path:
            editor.setPlainText(read_text_file(Path(path)))

    def _template(self) -> None:
        lang = self.language.currentData()
        self.script.setPlainText(script_template(self.name.text().strip() or "My project", "pt" if lang == "pt" else "en"))

    def _accept(self) -> None:
        if self.name.text().strip():
            self.accept()

    def values(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "projects_dir": self.projects_dir,
            "paths": list(self.paths),
            "brief": self.brief.toPlainText(),
            "script": self.script.toPlainText(),
            "language": self.language.currentData(),
            "generate": self.generate.isChecked(),
        }
