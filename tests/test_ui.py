"""GUI smoke tests: the real main window driven through a complete workflow."""

from __future__ import annotations

import time

import pytest

from behance_studio.assets.importer import import_paths
from behance_studio.generation.pipeline import GenerationRequest, generate
from behance_studio.projects.store import Project
from behance_studio.render.browser import browser_available

pytestmark = [pytest.mark.gui]


def pump(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(state, timeout: float = 120) -> None:
    start = time.time()
    pump(50)
    while state.runner.busy and time.time() - start < timeout:
        pump(50)
    pump(100)


@pytest.fixture
def window(qapp):
    from behance_studio.ui.main_window import MainWindow
    from behance_studio.ui.state import AppState

    w = MainWindow(AppState())
    w.resize(1400, 860)
    w.show()
    pump(50)
    yield w
    w.state.runner.cancel_all()
    w.state.runner.wait(10000)
    w.close()
    w.deleteLater()
    pump(50)


def test_window_without_project(window):
    assert window.current_page_id() == "dashboard"
    assert not window.sidebar.buttons["gallery"].isEnabled()
    window.show_page("gallery")  # needs a project: stays on the dashboard
    assert window.current_page_id() == "dashboard"
    window.show_page("settings")
    assert window.current_page_id() == "settings"
    window.toast("Saved")
    assert window.toast_widget.isVisible()


@pytest.mark.skipif(not browser_available(), reason="needs a Chromium-based browser")
def test_full_workflow(window, projects_dir, demo_assets_dir):
    state = window.state
    project = Project.create(projects_dir, "UI Test")
    import_paths(project, [demo_assets_dir])
    generate(project, GenerationRequest(families=["editorial", "split"], count=2, seed=11))
    state.set_project(project)
    pump(50)
    assert window.sidebar.buttons["gallery"].isEnabled()
    assert "2 proposals" in window.sidebar.chip.meta.text()

    for page in ("workspace", "gallery", "export", "trash", "settings", "dashboard"):
        window.show_page(page)
        pump(30)
        assert window.current_page_id() == page

    versions = state.versions.list()
    state.open_version.emit(versions[0].id)
    assert window.current_page_id() == "viewer"
    viewer = window.pages["viewer"]
    wait_idle(state)
    assert viewer.version_id == versions[0].id
    assert viewer.sections.count() >= 3

    # Edit a section title through the inspector, then undo it.
    section = [s for s in viewer.proposal.presentation.sections if s.plan_id][1]
    viewer._on_select(section.id, "")
    viewer.inspector.title.setText("Edited from the UI")
    viewer.inspector._emit_apply()
    wait_idle(state)
    assert viewer.proposal.spec.overrides[section.plan_id]["title"] == "Edited from the UI"
    reopened = state.versions.load(versions[0].id)
    assert reopened.spec.overrides[section.plan_id]["title"] == "Edited from the UI"
    viewer.undo()
    wait_idle(state)
    assert "title" not in viewer.proposal.spec.overrides.get(section.plan_id, {})

    # Compare two proposals.
    state.compare_versions.emit([v.id for v in versions])
    assert window.current_page_id() == "compare"
    assert [p.version_id for p in window.pages["compare"].panes[:2]] == [v.id for v in versions]
    wait_idle(state)

    # Export a PDF from the Export Center.
    state.export_versions.emit([versions[1].id])
    assert window.current_page_id() == "export"
    export = window.pages["export"]
    assert export._checked_ids() == [versions[1].id]
    for fmt, box in export.format_checks.items():
        box.setChecked(fmt == "pdf")
    export.open_after.setChecked(False)
    export._export()
    wait_idle(state)
    pdfs = list(project.exports_dir.glob("*.pdf"))
    assert len(pdfs) == 1 and pdfs[0].stat().st_size > 10_000

    # Trash and restore from the Trash page (bypassing the confirmation box).
    state.versions.trash([versions[1].id])
    state.versions_changed.emit()
    window.show_page("trash")
    trash = window.pages["trash"]
    assert len(trash.rows) == 1
    trash.rows[0].check.setChecked(True)
    trash._restore()
    assert len(state.versions.list()) == 2 and not state.versions.trashed()
