"""Real local-model verification (runs only when Ollama and a vision model are available).

On your PC, after installing Ollama and `ollama pull qwen3-vl:8b`:

    run_tests.bat tests\\test_ollama_live.py -s        (Windows)
    ./run.sh test tests/test_ollama_live.py -s        (Linux/macOS)

Optional: BEHANCE_STUDIO_OLLAMA_URL / BEHANCE_STUDIO_OLLAMA_MODEL to test
another server or model. Nothing here is simulated: every answer comes from
the model.
"""

from __future__ import annotations

import os

import pytest

from behance_studio.ai.ollama import DEFAULT_MODEL, DEFAULT_URL, detect

URL = os.environ.get("BEHANCE_STUDIO_OLLAMA_URL", DEFAULT_URL)
MODEL = os.environ.get("BEHANCE_STUDIO_OLLAMA_MODEL", DEFAULT_MODEL)
STATUS = detect(URL, MODEL, timeout=2.0)

pytestmark = [pytest.mark.ollama, pytest.mark.skipif(not STATUS.ready, reason=f"real local model not available: {STATUS.summary()}")]


def _settings():
    from behance_studio.core.settings import AppSettings

    s = AppSettings()
    s.ai.provider, s.ai.base_url, s.ai.model = "ollama", URL, MODEL
    return s


def test_real_model_recognises_design_purposes_and_directs():
    from behance_studio.ai.verify import verify_local_ai

    report = verify_local_ai(_settings(), hide_names=True, director=True)
    print("\n" + "\n".join(report.lines()))
    assert report.failures == 0, "the model must answer every image with usable structured JSON"
    assert report.accuracy is not None and report.accuracy >= 0.6, "design purposes recognised from the images alone"
    assert report.director_ok is not None


def test_real_model_generation_end_to_end(projects_dir, demo_assets_dir):
    from behance_studio.ai.service import service_for_project
    from behance_studio.assets.importer import import_paths
    from behance_studio.generation.pipeline import GenerationRequest, generate
    from behance_studio.projects.store import Project
    from behance_studio.projects.versions import VersionManager

    project = Project.create(projects_dir, "Live")
    import_paths(project, [demo_assets_dir])
    service = service_for_project(project, _settings())
    assert service is not None
    result = generate(project, GenerationRequest(families=["minimal", "story"], seed=3, render_previews=False), ai_service=service)
    print("\n".join(result.notes))
    assert len(result.versions) == 2
    for record in result.versions:
        data = VersionManager(project).load(record.id)
        assert not [i for i in data.quality.issues if i.code == "section_mismatch"]
        assert data.quality.errors == []
