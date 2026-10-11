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

    app = QApplication.instance() or QApplication(["pytest"])
    yield app
