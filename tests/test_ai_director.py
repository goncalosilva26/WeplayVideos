"""Behance Studio 2.0 AI layer: costs and limits, the AI Creative Director,
AI critique and reference material — against a local mock server (no
network, no cost)."""

from __future__ import annotations

import json

import pytest

from ai_mock import MockAI
from behance_studio.ai import costs
from behance_studio.ai import director as AD
from behance_studio.ai.costs import BudgetExceeded, PriceUnknown, RequestEstimate, SpendMeter, Usage, UsageLedger, resolve_prices
from behance_studio.ai.providers import AnthropicProvider, ImagePart, OpenAICompatibleProvider, anthropic_model_traits
from behance_studio.ai.service import service_for_project
from behance_studio.assets.importer import import_paths
from behance_studio.core.errors import ProviderError
from behance_studio.core.settings import AppSettings
from behance_studio.generation.pipeline import GenerationRequest, generate, understand
from behance_studio.planning.planner import PlanningContext
from behance_studio.projects.store import Project
from behance_studio.projects.versions import VersionManager

KEY = "sk-ant-test-SECRET-0001"
BRIEF = 'Project: Butter & Bean\nType: brand identity for a coffee shop\nMessages: "Good mornings, slowly."\nMood: warm and friendly'


@pytest.fixture
def mock():
    server = MockAI()
    yield server
    server.close()


@pytest.fixture
def settings(mock, monkeypatch):
    monkeypatch.setenv("BEHANCE_STUDIO_ANTHROPIC_API_KEY", KEY)
    s = AppSettings()
    s.ai.provider = "anthropic"
    s.ai.base_url = mock.url
    s.ai.model = "claude-opus-5-5"
    s.ai.timeout_s = 20
    s.ai.max_retries = 1
    s.ai.allow_image_upload = True
    s.ai.run_limit_usd = 5.0
    return s


@pytest.fixture
def project(projects_dir, demo_assets_dir):
    p = Project.create(projects_dir, "Butter & Bean")
    import_paths(p, [demo_assets_dir])
    p.write_text("brief", BRIEF)
    p.config.ai_consent = True
    p.save_config()
    return p


# ------------------------------------------------------------------ costs
def test_prices_are_known_only_where_documented():
    assert resolve_prices("anthropic", "claude-opus-5-5", False).input_per_mtok == 4.0
    assert resolve_prices("anthropic", "claude-haiku-5-5", False).output_per_mtok == 0.5
    assert resolve_prices("openai", "gpt-4.1-mini", False) is None  # never invented
    assert resolve_prices("local", "llava", True).source == "free"
    s = AppSettings()
    s.ai.price_input_per_mtok, s.ai.price_output_per_mtok = 0.4, 1.6
    assert resolve_prices("openai", "gpt-4.1-mini", False, s.ai).source == "settings"


def test_usage_parsing_and_cost():
    a = Usage.from_response({"usage": {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 2000}})
    o = Usage.from_response({"usage": {"prompt_tokens": 1000, "completion_tokens": 500}})
    assert a.reported and o.reported and a.output_tokens == o.output_tokens == 500
    prices = resolve_prices("anthropic", "claude-opus-5-5", False)
    assert a.cost(prices) == pytest.approx((1000 + 200) * 4 / 1e6 + 500 * 20 / 1e6)
    assert not Usage.from_response({}).reported


def test_spend_meter_enforces_limits(tmp_path):
    prices = resolve_prices("anthropic", "claude-opus-5-5", False)
    ledger = UsageLedger(tmp_path / "usage.json")
    meter = SpendMeter("anthropic", "claude-opus-5-5", prices, True, run_limit=0.05, ledger=ledger)
    est = RequestEstimate("x", 1000, 1000, 2000)  # ≈ $0.024 expected
    meter.authorize(est)
    meter.record(Usage(1000, 1000, reported=True), est)
    meter.authorize(est)
    meter.record(Usage(1000, 1000, reported=True), est)
    with pytest.raises(BudgetExceeded):
        meter.authorize(est)
    assert ledger.month()["requests"] == 2 and ledger.month_spent() == pytest.approx(0.048)
    # Monthly limit reads the persisted ledger.
    monthly = SpendMeter("anthropic", "claude-opus-5-5", prices, True, monthly_limit=0.06, ledger=ledger)
    with pytest.raises(BudgetExceeded):
        monthly.authorize(est)
    # Unknown price + a limit: paid requests are refused rather than guessed.
    with pytest.raises(PriceUnknown):
        SpendMeter("openai", "gpt-x", None, True, run_limit=1.0).authorize(est)
    SpendMeter("openai", "gpt-x", None, True).authorize(est)  # no limit: allowed (cost shown as unknown)
    SpendMeter("local", "llava", resolve_prices("local", "llava", True), False, run_limit=0.0001).authorize(est)  # free


def test_ledger_never_stores_content(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.json")
    ledger.add("anthropic", "claude-opus-5-5", Usage(10, 5, reported=True), 0.001)
    raw = (tmp_path / "usage.json").read_text()
    assert set(json.loads(raw)["months"][UsageLedger.month_key()]) <= {"requests", "input_tokens", "output_tokens", "cost", "models", "unpriced_requests"}


# --------------------------------------------------------------- provider
def test_anthropic_current_request_shape(mock):
    assert anthropic_model_traits("claude-opus-5-5") == {"modern": True, "no_sampling": True}
    assert anthropic_model_traits("claude-3-5-haiku")["modern"] is False
    provider = AnthropicProvider(mock.url, "claude-opus-5-5", "k", timeout=10, max_retries=0)
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
    data = provider.complete_json("sys", "write", [ImagePart(b"\xff\xd8x", "image/jpeg", 64, 64)], max_tokens=160,
                                  schema=schema, effort="low", shared="shared context")
    assert data == {"text": mock.copy_text}  # thinking blocks are ignored
    body = mock.requests[-1]["body"]
    assert "temperature" not in body  # rejected by current models
    assert body["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
    assert body["max_tokens"] > 160  # headroom for reasoning
    content = body["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "text", "text"]
    assert content[1]["cache_control"] == {"type": "ephemeral"} and content[1]["text"] == "shared context"
    assert provider.last_usage.reported and provider.last_usage.input_tokens == 1200


def test_anthropic_falls_back_when_output_config_is_refused(mock):
    mock.reject_output_config = True
    provider = AnthropicProvider(mock.url, "claude-sonnet-5-5", "k", timeout=10, max_retries=0)
    assert provider.complete_json("sys", "write", schema={"type": "object"})["text"] == mock.copy_text
    assert "output_config" in mock.requests[-2]["body"] and "output_config" not in mock.requests[-1]["body"]


def test_refusal_and_metering_through_provider(mock, tmp_path):
    provider = OpenAICompatibleProvider(mock.url + "/v1", "vision-model", "k", timeout=10, max_retries=0)
    prices = costs.Prices(1.0, 2.0, "settings")
    provider.meter = SpendMeter("openai", "vision-model", prices, True, run_limit=0.0012, ledger=UsageLedger(tmp_path / "u.json"))
    provider.complete("sys", "hello")  # 1200 in + 300 out = $0.0018 recorded from the reported usage
    assert provider.meter.spent == pytest.approx(0.0018)
    sent = len(mock.requests)
    with pytest.raises(BudgetExceeded):
        provider.complete("sys", "hello again")
    assert len(mock.requests) == sent  # nothing was sent once the limit was reached


# --------------------------------------------------------------- director
def _ctx(project):
    assets = project.list_assets()
    directives, direction = understand(project, assets)
    return PlanningContext(project.name, assets, directives, direction)


def test_storyboard_validation_repairs_and_rejects(project):
    ctx = _ctx(project)
    req = AD.build_request(project, ctx, "bold", 3, 0.5, ["minimal", "photo"], with_images=True, references=[])
    assert req.images and req.images[0].width > 0  # one contact sheet, not one image per asset
    assert "Good mornings, slowly." in req.shared and "BOLD" not in req.shared
    by_group = {}
    for g, a in req.groups:
        by_group.setdefault(g, []).append(req.handles[a.id])
    art = (by_group.get("poster") or by_group.get("social") or by_group.get("artwork"))[0]
    photo = (by_group.get("photo") or by_group.get("scene"))[0]
    story = {
        "idea": "Scale and colour.",
        "cover": {"module": "cover_logo", "assets": [], "message": 0},
        "sections": [
            {"module": "statement", "assets": [], "chapter": "none", "message": -1, "why": "context"},
            {"module": "statement", "assets": [], "chapter": "none", "message": -1, "why": "twice"},
            {"module": "fullbleed", "assets": [art], "chapter": "none", "message": -1, "why": "crop the poster"},
            {"module": "duo", "assets": [photo, "A404"], "chapter": "none", "message": -1, "why": "pair"},
            {"module": "quote_band", "assets": [], "chapter": "none", "message": 0, "why": "reuse tagline"},
            {"module": "chapter", "assets": [], "chapter": "nonsense", "message": -1, "why": "bad chapter"},
            {"module": "teleport", "assets": [photo], "chapter": "none", "message": -1, "why": "unknown"},
            {"module": "logo_hero", "assets": [req.handles[ctx.assets[0].id] if ctx.assets[0].id in req.handles else "A1"], "chapter": "none", "message": -1, "why": "identity"},
        ],
        "closing_message": 0,
        "left_out": [],
    }
    plan, report = AD.storyboard_to_plan(ctx, req.inventory, req.groups, req.handles, "bold", 3, story)
    assert plan is not None
    modules = [s.meta["module"] for s in plan.sections]
    assert modules[0] == "cover_logo" and modules[-1] == "closing"
    assert modules.count("statement") == 1
    assert "teleport" not in modules
    # Artwork asked for edge to edge is staged instead of cropped.
    art_id = next(aid for aid, h in req.handles.items() if h == art)
    art_section = next(s for s in plan.sections if art_id in s.asset_ids)
    assert art_section.meta["module"] == "stage"
    assert any("does not suit" in r for r in report) and any("unknown asset" in r for r in report)
    assert any("unknown module" in r for r in report) and any("chapter name" in r for r in report)
    assert any("quote_band" in r for r in report)  # message 0 is already the cover tagline
    # Text only comes from the brief or generic offline copy.
    cover = plan.sections[0]
    assert cover.subtitle == "Good mornings, slowly." and cover.exact_text
    assert plan.sections[-1].body == ""  # closing message 0 was already used
    assert plan.sections[0].meta["director"]["source"] == "ai"


def test_storyboard_with_too_little_falls_back(project):
    ctx = _ctx(project)
    req = AD.build_request(project, ctx, "minimal", 1, 0.5, [], with_images=False, references=[])
    assert req.images == []
    junk = {"idea": "", "cover": {"module": "cover_logo", "assets": [], "message": -1},
            "sections": [{"module": "nope", "assets": [], "chapter": "none", "message": -1, "why": ""}], "closing_message": -1, "left_out": []}
    plan, report = AD.storyboard_to_plan(ctx, req.inventory, req.groups, req.handles, "minimal", 1, junk)
    assert plan is None and report


def test_ai_directs_five_concepts_with_cache_and_estimate(settings, mock, project):
    service = service_for_project(project, settings)
    est = service.estimate_generation(project, settings.families, render_previews=False)
    labels = [label for label, _, _ in est.items]
    assert any("Creative direction" in l for l in labels) and est.expected_cost and est.expected_cost > 0
    assert "Expected cost" in est.summary() and not est.blocked_reason

    result = generate(project, GenerationRequest(seed=5, render_previews=False), ai_service=service)
    assert len(result.versions) == 5 and result.ai_used
    directed = mock.requests_for("CONCEPT TO DEVELOP")
    assert len(directed) == 5
    assert all("data" in json.dumps(r["body"]["messages"][0]["content"][0]) for r in directed)  # the contact sheet
    vm = VersionManager(project)
    for record in result.versions:
        data = vm.load(record.id)
        assert data.sources["director"] == "ai"
        assert data.quality.errors == []
        assert any("art-directed with AI" in n for n in data.notes)
    assert any(n.startswith("AI usage:") for n in result.notes)
    # Same material and seed: everything is cached, nothing is sent again.
    before = len(mock.requests)
    generate(project, GenerationRequest(seed=5, render_previews=False), ai_service=service_for_project(project, settings))
    assert mock.requests[before:] == []
    # The key never reaches project files.
    for path in project.root.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path


def test_director_without_preview_permission_sends_no_images(settings, mock, project):
    settings.ai.allow_image_upload = False
    generate(project, GenerationRequest(families=["minimal"], seed=2, render_previews=False), ai_service=service_for_project(project, settings))
    directed = mock.requests_for("CONCEPT TO DEVELOP")
    assert directed and all(c["type"] == "text" for r in directed for c in r["body"]["messages"][0]["content"])
    assert not any("image" in json.dumps(r["body"]) and '"type": "image"' in json.dumps(r["body"]) for r in mock.requests)


def test_spending_limit_stops_ai_but_generation_completes(settings, mock, project):
    settings.ai.run_limit_usd = 0.02  # about one request at list price
    result = generate(project, GenerationRequest(seed=9, render_previews=False), ai_service=service_for_project(project, settings))
    assert len(result.versions) == 5
    assert any("limit" in n for n in result.notes)
    assert len(mock.requests) <= 4  # stopped early; parallel recognition may have one or two in flight
    vm = VersionManager(project)
    assert {vm.load(r.id).sources["director"] for r in result.versions} == {"local"}


def test_unknown_price_with_limit_is_disclosed_and_blocked(mock, project, monkeypatch):
    monkeypatch.setenv("BEHANCE_STUDIO_OPENAI_API_KEY", "sk-x")
    s = AppSettings()
    s.ai.provider, s.ai.base_url, s.ai.model = "openai", "https://api.example.invalid/v1", "some-model"
    service = service_for_project(project, s)
    est = service.estimate_generation(project, s.families)
    assert est.expected_cost is None and "unknown" in est.blocked_reason.lower()


# --------------------------------------------------------------- critique
def test_ai_critique_recomposes_flagged_sections(settings, mock, project):
    from behance_studio.render.browser import browser_available

    if not browser_available(""):
        pytest.skip("headless browser not available")
    settings.ai.use_for_evaluation = True
    settings.ai.use_for_direction = False
    result = generate(project, GenerationRequest(families=["minimal", "bold"], seed=4), ai_service=service_for_project(project, settings))
    critiques = mock.requests_for("Rubric for each section score")
    assert len(critiques) == 2
    body = critiques[0]["body"]
    images = [c for c in body["messages"][0]["content"] if c["type"] == "image"]
    assert 3 <= len(images) <= 16
    vm = VersionManager(project)
    for record in result.versions:
        data = vm.load(record.id)
        assert data.quality.metrics.get("ai_critique") == 4.0
        assert data.sources["ai_critique"]["sections"]
        assert any(n.startswith("AI critique") for n in data.notes)


def test_critique_needs_preview_permission(settings, mock, project):
    settings.ai.use_for_evaluation = True
    settings.ai.allow_image_upload = False
    service = service_for_project(project, settings)
    assert service.critique(None, None) is None
    assert mock.requests_for("Rubric") == []


# ------------------------------------------------------------- references
def test_reference_folder_is_never_shown_but_offered_to_the_director(settings, mock, projects_dir, demo_assets_dir, tmp_path):
    refs = tmp_path / "References"
    refs.mkdir()
    from PIL import Image, ImageDraw

    shot = Image.new("RGB", (1280, 800), (236, 226, 210))  # a stand-in screenshot (synthetic, clearly a fixture)
    ImageDraw.Draw(shot).rectangle((80, 120, 700, 680), fill=(120, 72, 40))
    shot.save(refs / "kanoffe-cafe-screenshot.jpg", quality=88)
    p = Project.create(projects_dir, "Refs")
    import_paths(p, [demo_assets_dir / "01 Logo", demo_assets_dir / "04 Packaging", refs])
    p.write_text("brief", BRIEF)
    p.config.ai_consent = True
    p.save_config()
    ref = next(a for a in p.list_assets() if a.filename.startswith("kanoffe"))
    assert ref.kind == "reference"
    result = generate(p, GenerationRequest(families=["layered"], seed=1, render_previews=False), ai_service=service_for_project(p, settings))
    data = VersionManager(p).load(result.versions[0].id)
    assert all(ref.id not in s.asset_ids for s in data.plan.sections)
    directed = mock.requests_for("CONCEPT TO DEVELOP")[0]["body"]
    content = directed["messages"][0]["content"]
    assert [c["type"] for c in content].count("image") == 2  # contact sheet + reference sheet
    assert "reference screenshot" in json.dumps(content)
    # Offline, references are simply left out.
    offline = generate(p, GenerationRequest(families=["minimal"], seed=1, render_previews=False))
    plan = VersionManager(p).load(offline.versions[0].id).plan
    assert all(ref.id not in s.asset_ids for s in plan.sections)


def test_estimate_respects_consent(settings, mock, project):
    project.config.ai_consent = False
    project.save_config()
    service = service_for_project(project, settings)
    est = service.estimate_generation(project, settings.families)
    assert est.requests == 0 and "not allowed" in est.summary()
    with pytest.raises(ProviderError):
        raise BudgetExceeded("x")
