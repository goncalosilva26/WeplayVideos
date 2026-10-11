"""Shared pytest fixtures. All tests run against an isolated temporary home."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(os, "geteuid") and os.geteuid() == 0:
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")  # Chromium refuses to sandbox as root

_APP = None


def pytest_configure(config):
    """Create one full QApplication for the session (widgets, SVG and WebEngine)."""
    global _APP
    try:
        from behance_studio.ui.app import create_application

        _APP = create_application(["pytest"])
    except Exception:  # noqa: BLE001 - GUI stack unavailable; headless tests still run
        _APP = None


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("bs_home")
    monkeypatch.setenv("BEHANCE_STUDIO_HOME", str(home))
    from behance_studio.core import settings

    settings.reset_settings_store_for_tests()
    yield home
    settings.reset_settings_store_for_tests()


@pytest.fixture
def projects_dir(tmp_path):
    path = tmp_path / "Projects"
    path.mkdir()
    return path


@pytest.fixture(scope="session")
def demo_assets_dir(tmp_path_factory):
    """Synthetic Butter & Bean asset folder (generated once per session)."""
    from make_demo_assets import build_demo_assets

    target = tmp_path_factory.mktemp("demo") / "Butter & Bean assets"
    build_demo_assets(target, include_video=True)
    return target


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        pytest.skip("Qt widgets are not available in this environment")
    yield app
