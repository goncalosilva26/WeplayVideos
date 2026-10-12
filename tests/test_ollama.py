"""Free local AI through Ollama: detection, setup guidance, the native API
client, design-purpose recognition, section assignment and the end-to-end
flow — against a local stand-in for Ollama's HTTP API (no model, no GPU).

The same code paths are exercised with a real model by
``tests/test_ollama_live.py`` whenever Ollama is available."""

from __future__ import annotations

import io
import json
import socket
import time

import pytest
from PIL import Image

from ollama_mock import MockOllama
from behance_studio.ai import ollama as O
from behance_studio.ai.costs import SpendMeter, resolve_prices
from behance_studio.ai.providers import ImagePart, OllamaProvider
from behance_studio.ai.service import service_for_project
from behance_studio.ai.vision import SCHEMA as VISION_SCHEMA
from behance_studio.assets.importer import import_paths
from behance_studio.core.errors import ProviderError
from behance_studio.core.settings import AppSettings, SettingsStore
from behance_studio.generation.pipeline import GenerationRequest, generate
from behance_studio.planning.models import PresentationPlan, SectionPlan
from behance_studio.projects.store import Project
from behance_studio.projects.versions import VersionManager


@pytest.fixture
def mock():
    server = MockOllama()
    yield server
    server.close()


def _free_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def _settings(url: str, model: str = "qwen3-vl:8b") -> AppSettings:
    s = AppSettings()
    assert s.ai.provider == "ollama"  # free local AI is the default
    s.ai.base_url, s.ai.model = url, model
    return s


def _jpeg(w: int = 320, h: int = 240) -> ImagePart:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 60)).save(buf, "JPEG")
    return ImagePart(buf.getvalue(), "image/jpeg", w, h)


# -------------------------------------------------------------- detection
def test_detection_states_and_setup_steps(mock, monkeypatch):
    monkeypatch.setattr(O, "find_binary", lambda: "")
    absent = O.detect(_free_port_url(), "qwen3-vl:8b", timeout=1.0)
    assert absent.state == "not_installed" and not absent.ready
    steps = " ".join(O.setup_steps(absent))
    assert "ollama.com/download" in steps and "ollama pull qwen3-vl:8b" in steps and "winget install Ollama.Ollama" in steps

    monkeypatch.setattr(O, "find_binary", lambda: r"C:\Users\me\AppData\Local\Programs\Ollama\ollama.exe")
    stopped = O.detect(_free_port_url(), "qwen3-vl:8b", timeout=1.0)
    assert stopped.state == "not_running" and "Start Ollama" in " ".join(O.setup_steps(stopped))

    ready = O.detect(mock.url, "qwen3-vl:8b")
    assert ready.state == "ready" and ready.version == "0.12.9" and ready.vision and O.setup_steps(ready) == []

    missing = O.detect(mock.url, "qwen3-vl:4b")
    assert missing.state == "model_missing" and "ollama pull qwen3-vl:4b" in " ".join(O.setup_steps(missing))
    assert "run:  ollama pull" in " ".join(O.setup_steps(missing, cli=True))

    mock.capabilities = ["completion"]  # a text-only model
    blind = O.detect(mock.url, "qwen3-vl:8b")
    assert blind.state == "no_vision" and "vision model" in " ".join(O.setup_steps(blind))


def test_model_names_match_like_ollama():
    assert O.same_model("qwen3-vl:latest", "qwen3-vl")
    assert O.same_model("qwen3-vl:8b", "QWEN3-VL:8b")
    assert not O.same_model("qwen3-vl:4b", "qwen3-vl:8b")
    assert O.RECOMMENDED[0].name == O.DEFAULT_MODEL == "qwen3-vl:8b"
    assert all(m.vram_gb <= 12 for m in O.RECOMMENDED)  # every recommendation fits an RTX 3060 12 GB


def test_pull_reports_progress_and_errors(mock):
    seen: list[float] = []
    O.pull_model(mock.url, "qwen3-vl:4b", progress=lambda f, m: seen.append(f))
    assert seen[-1] == 1.0 and max(seen) == 1.0 and "qwen3-vl:4b" in mock.models
    assert O.detect(mock.url, "qwen3-vl:4b").ready
    mock.pull_error = "pull model manifest: file does not exist"
    with pytest.raises(RuntimeError, match="does not exist"):
        O.pull_model(mock.url, "nope:1b")


# ----------------------------------------------------------------- client
def test_native_request_shape_is_free_and_structured(mock):
    provider = OllamaProvider(mock.url, "qwen3-vl:8b", None, timeout=10, max_retries=0)
    assert provider.is_local and not provider.may_bill and provider.parallel == 1
    prices = resolve_prices("ollama", provider.model, provider.is_local)
    provider.meter = SpendMeter("ollama", provider.model, prices, provider.may_bill, run_limit=0.01)
    data = provider.complete_json("system", "Allowed kinds\nFile name: coffee-bag.jpg", [_jpeg()], max_tokens=240, schema=VISION_SCHEMA)
    assert data["kind"] == "packaging"
    body = mock.chats()[-1]
    assert body["format"] == VISION_SCHEMA and body["stream"] is False and body["keep_alive"]
    user = body["messages"][1]
    assert isinstance(user["images"][0], str) and not user["images"][0].startswith("data:")
    assert body["options"]["num_ctx"] >= 8192 and "think" not in body
    assert provider.last_usage.reported and provider.last_usage.input_tokens == 900
    assert provider.meter.spent == 0.0  # local: never billed, limits never block

    big = provider.context_for(200_000, [_jpeg(1008, 1152)], 4000)
    assert big > 8192  # the creative-direction prompt gets a larger context window

    # Plain JSON (no schema) still asks Ollama for JSON.
    provider.complete_json("system", "write a caption")
    assert mock.chats()[-1]["format"] == "json"


def test_thinking_models_are_asked_not_to_think(mock):
    mock.capabilities = ["completion", "vision", "thinking"]
    provider = OllamaProvider(mock.url, "qwen3-vl:8b", None, timeout=10, max_retries=0)
    provider.complete("system", "hello")
    assert mock.chats()[-1]["think"] is False


def test_helpful_errors(mock):
    provider = OllamaProvider(mock.url, "qwen3-vl:32b", None, timeout=10, max_retries=0)
    with pytest.raises(ProviderError, match="ollama pull qwen3-vl:32b"):
        provider.complete("system", "hello")
    down = OllamaProvider(_free_port_url(), "qwen3-vl:8b", None, timeout=5, max_retries=0)
    with pytest.raises(ProviderError, match="Ollama is not running"):
        down.complete("system", "hello")


# --------------------------------------------------------------- settings
def test_settings_default_and_migration(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"settings_version": 2, "ai": {"provider": "none"}}))
    assert SettingsStore(path).settings.ai.provider == "ollama"
    path.write_text(json.dumps({"settings_version": 2, "ai": {"provider": "anthropic", "model": "claude-opus-5-5"}}))
    assert SettingsStore(path).settings.ai.provider == "anthropic"  # a paid choice is never changed
    path.write_text(json.dumps({"settings_version": 3, "ai": {"provider": "none"}}))
    assert SettingsStore(path).settings.ai.provider == "none"  # an explicit "off" after the upgrade stays off


def test_without_ollama_the_app_works_offline(projects_dir, demo_assets_dir):
    project = Project.create(projects_dir, "Offline")
    import_paths(project, [demo_assets_dir / "01 Logo", demo_assets_dir / "04 Packaging"])
    started = time.monotonic()
    assert service_for_project(project, _settings(_free_port_url())) is None
    assert time.monotonic() - started < 5
    result = generate(project, GenerationRequest(families=["minimal"], render_previews=False))
    assert len(result.versions) == 1


# ------------------------------------------------------------- end to end
def test_local_ai_recognises_plans_and_stays_free(mock, projects_dir, demo_assets_dir):
    project = Project.create(projects_dir, "Butter & Bean")
    import_paths(project, [demo_assets_dir])
    assert not project.config.ai_consent  # nothing leaves the PC: no consent needed
    settings = _settings(mock.url)
    assert not settings.ai.allow_image_upload
    service = service_for_project(project, settings)
    assert service is not None and service.content_allowed and service.images_allowed
    est = service.estimate_generation(project, settings.families, render_previews=False)
    assert est.requests and not est.needs_confirmation and est.expected_cost == 0.0
    assert "no charge" in est.summary()

    result = generate(project, GenerationRequest(seed=4, render_previews=False), ai_service=service)
    assert len(result.versions) == 5 and result.ai_used
    recognised = mock.chats("Allowed kinds")
    stills = [a for a in project.list_assets() if a.is_visual]
    assert recognised and all(isinstance(b["messages"][1]["images"][0], str) for b in recognised)
    assert len(mock.chats("CONCEPT TO DEVELOP")) == 5
    assert all(r["path"].startswith("/api/") for r in mock.requests)  # only the local Ollama API
    analysed = [a for a in project.list_assets() if ((a.analysis or {}).get("ai") or {}).get("presentation")]
    assert len(analysed) >= 10  # design purpose and presentation stored for each recognised image
    vm = VersionManager(project)
    for record in result.versions:
        data = vm.load(record.id)
        assert data.sources["director"] == "ai"
        assert not [i for i in data.quality.issues if i.code == "section_mismatch"]
    assert any("local, no charge" in n for n in result.notes)
    assert len(stills) >= len(recognised)


def test_implausible_answers_never_move_images(mock, projects_dir, demo_assets_dir):
    project = Project.create(projects_dir, "Guard")
    import_paths(project, [demo_assets_dir / "01 Logo"])
    logo = next(a for a in project.list_assets() if a.filename == "butter-bean-logo-primary.png")
    assert (logo.analysis or {}).get("background") == "transparent"
    mock.overrides[logo.filename.lower()] = ("photo", "photograph")  # a confidently wrong answer
    service = service_for_project(project, _settings(mock.url))
    service.classify_assets(project, project.list_assets())
    logo = project.get_asset(logo.id)
    assert logo.effective_kind == "logo" and logo.kind_source != "ai"
    assert "transparent" in logo.analysis["ai"]["rejected"]


def test_ai_presentation_decides_crop_or_stage(projects_dir, demo_assets_dir):
    from behance_studio.assets.understanding import asset_nature

    project = Project.create(projects_dir, "Nature")
    import_paths(project, [demo_assets_dir / "04 Packaging"])
    bag = next(a for a in project.list_assets() if a.filename == "coffee-bag-mockup.jpg")
    bag.kind = "packaging"
    bag.analysis["ai"] = {"kind": "packaging", "presentation": "flat_artwork", "confidence": 0.9}
    assert asset_nature(bag) == "artwork"  # finished artwork: staged, never cropped
    bag.analysis["ai"]["presentation"] = "photographed_scene"
    assert asset_nature(bag) == "photo"
    ai = bag.analysis.pop("ai")
    measured = asset_nature(bag)
    ai.update(confidence=0.3, presentation="flat_artwork" if measured == "photo" else "photographed_scene")
    bag.analysis["ai"] = ai
    assert asset_nature(bag) == measured  # unsure answers fall back to the measurements


# ------------------------------------------------------- section assignment
def test_section_fit_moves_misplaced_images(projects_dir, demo_assets_dir):
    from behance_studio.planning.fit import enforce_section_fit, mismatches

    project = Project.create(projects_dir, "Fit")
    import_paths(project, [demo_assets_dir])
    by_name = {a.filename: a for a in project.list_assets()}
    assets = {a.id: a for a in by_name.values()}
    bag, cups, post1, post2, post3, dsc = (by_name[n].id for n in ("coffee-bag-mockup.jpg", "takeaway-cups.jpg", "instagram-post-01.jpg",
                                                                   "instagram-post-02.jpg", "instagram-post-03.jpg", "DSC_0142.jpg"))
    plan = PresentationPlan(sections=[
        SectionPlan(type="cover", title="Butter & Bean"),
        SectionPlan(type="packaging", title="Packaging", asset_ids=[bag, post1]),
        SectionPlan(type="photography", title="Photography", asset_ids=[dsc, cups]),
        SectionPlan(type="logo", title="Logo", asset_ids=[post2]),
        SectionPlan(type="packaging", title="Script packaging", asset_ids=[post3], source="script", exact_text=True),
        SectionPlan(type="closing", title="Thank you"),
    ], language="en", project_title="Fit", category="brand_identity", category_label="Brand identity")
    kinds = {aid: a.effective_kind for aid, a in assets.items()}
    report = enforce_section_fit(plan, assets)
    by_type = {}
    for s in plan.sections:
        by_type.setdefault(s.type, []).append(s)
    packaging = [s for s in by_type["packaging"] if s.source != "script"][0]
    assert packaging.asset_ids == [bag, cups]  # the cups joined the packaging section
    assert post1 in by_type["social"][0].asset_ids  # the post got a section of its own kind
    assert any(s.asset_ids == [post2] for s in by_type["social"])  # "Logo" holding a post was re-labelled
    assert by_type["photography"][0].asset_ids == [dsc]
    script = next(s for s in plan.sections if s.source == "script")
    assert script.asset_ids == [post3] and report.kept == [(post3, "Script packaging")]  # the script is never changed
    used = [aid for s in plan.sections for aid in s.asset_ids]
    assert sorted(used) == sorted([bag, cups, post1, post2, post3, dsc])  # nothing dropped, nothing swapped
    assert sum(len(mismatches(s, kinds)) for s in plan.sections if s.source != "script") == 0
    assert report.notes({a.id: a.filename for a in assets.values()})


def test_section_fit_keeps_2_0_modules_valid(projects_dir, demo_assets_dir):
    from behance_studio.ai.director import CATALOGUE
    from behance_studio.planning.fit import enforce_section_fit

    project = Project.create(projects_dir, "Fit2")
    import_paths(project, [demo_assets_dir / "04 Packaging", demo_assets_dir / "06 Social Media"])
    by_name = {a.filename: a for a in project.list_assets()}
    assets = {a.id: a for a in by_name.values()}
    bag, post = by_name["coffee-bag-mockup.jpg"].id, by_name["instagram-post-01.jpg"].id
    sp = SectionPlan(type="packaging", title="Packaging", asset_ids=[bag, post])
    sp.meta.update({"module": "duo", "params": {}, "alternatives": ["duo"]})
    plan = PresentationPlan(sections=[sp], language="en", project_title="Fit2", category="brand_identity", category_label="Brand identity")
    enforce_section_fit(plan, assets)
    for s in plan.sections:
        spec = CATALOGUE[s.meta["module"]]
        assert spec.min <= len(s.asset_ids) <= spec.max, (s.meta["module"], s.asset_ids)
    assert {s.type for s in plan.sections} == {"packaging", "social"}


# ------------------------------------------------------------ verification
def test_ai_check_runs_the_real_pipeline_against_ollama(mock, monkeypatch, capsys):
    from behance_studio import cli
    from behance_studio.ai.verify import verify_local_ai
    from behance_studio.core.settings import get_settings_store

    report = verify_local_ai(_settings(mock.url), hide_names=False)
    assert report.status.ready and report.failures == 0
    assert report.accuracy == 1.0  # the stand-in answers from file names, so this checks scoring, not a model
    assert report.director_ok is True and report.gpu
    text = "\n".join(report.lines())
    assert "Accuracy on labelled test images" in text and "Creative direction" in text

    store = get_settings_store()
    store.settings.ai.base_url = mock.url
    store.save()
    assert cli.main(["ai-check"]) == 0
    assert cli.main(["ai-check", "--model", "qwen3-vl:4b"]) == 1  # missing model: steps are printed
    assert "ollama pull qwen3-vl:4b" in capsys.readouterr().out
    assert cli.main(["ai-check", "--model", "qwen3-vl:4b", "--pull"]) == 0
