"""AI subsystem tests against a local mock server (no network, no cost)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from behance_studio.ai import credentials
from behance_studio.ai.orchestrator import AIService, fact_guard
from behance_studio.ai.providers import AnthropicProvider, OpenAICompatibleProvider, create_provider, extract_json
from behance_studio.ai.service import service_for_project
from behance_studio.assets.importer import import_paths
from behance_studio.core.errors import ProviderError
from behance_studio.core.settings import AppSettings
from behance_studio.generation.pipeline import GenerationRequest, generate
from behance_studio.projects.store import Project

SECRET = "sk-test-SECRET-never-on-disk-12345"


class MockAI:
    """Records requests and answers like an OpenAI/Anthropic-compatible API."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.fail_next = 0
        self.copy_text = "Packaging for Butter & Bean, shown across the product range."
        self.kind = "packaging"
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _answer(self, body: dict) -> str:
        text = json.dumps(body, ensure_ascii=False)
        if "Allowed kinds" in text:
            return json.dumps({"kind": self.kind, "confidence": 0.93, "description": "A coffee bag on a table", "tags": ["coffee", "bag"]})
        if "Rate the intended brand personality" in text:
            return "```json\n" + json.dumps({"personality": {"warmth": 0.9, "energy": None, "modernity": 0.4}, "mood_words": ["inviting", "crafted"], "tone": None}) + "\n```"
        return json.dumps({"text": self.copy_text})

    def _handler(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def _send(self, code: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                mock.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": None})
                self._send(200, {"data": [{"id": "vision-model"}, {"id": "other-model"}]})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                mock.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if mock.fail_next:
                    mock.fail_next -= 1
                    self._send(503, {"error": {"message": "overloaded"}})
                    return
                answer = mock._answer(body)
                if self.path.endswith("/messages"):
                    self._send(200, {"content": [{"type": "text", "text": answer}]})
                else:
                    self._send(200, {"choices": [{"message": {"role": "assistant", "content": answer}}]})

        return Handler


@pytest.fixture
def mock_ai():
    server = MockAI()
    yield server
    server.close()


@pytest.fixture
def ai_settings(mock_ai, monkeypatch):
    monkeypatch.setenv("BEHANCE_STUDIO_OPENAI_API_KEY", SECRET)
    s = AppSettings()
    s.ai.provider = "openai"
    s.ai.base_url = mock_ai.url + "/v1"
    s.ai.model = "vision-model"
    s.ai.timeout_s = 10
    s.ai.max_retries = 2
    s.ai.allow_image_upload = True
    return s


def images_sent(mock: MockAI) -> int:
    return sum(json.dumps(r["body"]).count("data:image/") for r in mock.requests if r["body"])


def test_no_provider_means_no_service(projects_dir):
    project = Project.create(projects_dir, "Offline")
    assert service_for_project(project, AppSettings()) is None


def test_cloud_provider_requires_key(monkeypatch):
    for var in ("BEHANCE_STUDIO_OPENAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    credentials._session.clear()
    s = AppSettings()
    s.ai.provider = "openai"
    with pytest.raises(ProviderError):
        create_provider(s)


def test_key_never_sent_over_plain_http_to_remote_hosts():
    with pytest.raises(ProviderError):
        OpenAICompatibleProvider("http://api.example.com/v1", "m", "secret")
    OpenAICompatibleProvider("http://127.0.0.1:9/v1", "m", "secret")  # local: allowed
    assert "secret" not in repr(OpenAICompatibleProvider("https://api.example.com/v1", "m", "secret"))


def test_connection_test_lists_models_without_billing(ai_settings, mock_ai):
    provider = create_provider(ai_settings)
    message = provider.test_connection()
    assert "vision-model" in message and "billed" in message
    assert all(r["body"] is None for r in mock_ai.requests)  # only GET /models
    assert mock_ai.requests[0]["headers"]["authorization"] == f"Bearer {SECRET}"
    ai_settings.ai.model = "missing-model"
    with pytest.raises(ProviderError):
        create_provider(ai_settings).test_connection()


def test_retries_then_succeeds(ai_settings, mock_ai):
    mock_ai.fail_next = 2
    provider = create_provider(ai_settings)
    assert provider.complete("system", "hello") .startswith("{")
    assert len(mock_ai.requests) == 3
    mock_ai.fail_next = 5
    with pytest.raises(ProviderError):
        provider.complete("system", "hello")


def test_anthropic_request_format(mock_ai):
    provider = AnthropicProvider(mock_ai.url, "claude-model", "anthropic-key", timeout=10, max_retries=0)
    from behance_studio.ai.providers import ImagePart

    text = provider.complete("sys", "Allowed kinds: logo", [ImagePart(b"\xff\xd8fake", "image/jpeg")])
    assert json.loads(text)["kind"] == "packaging"
    req = mock_ai.requests[-1]
    assert req["path"] == "/v1/messages"
    assert req["headers"]["x-api-key"] == "anthropic-key"
    assert req["headers"]["anthropic-version"]
    assert req["body"]["system"] == "sys"
    assert req["body"]["messages"][0]["content"][0]["type"] == "image"


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    assert extract_json("no json") is None


def test_fact_guard():
    source = "Butter & Bean is a neighbourhood coffee shop. Packaging and posters."
    assert fact_guard("Packaging for Butter & Bean.", source)[0]
    assert not fact_guard("Award-winning packaging for Butter & Bean.", source)[0]
    assert not fact_guard("Packaging that increased sales by 40%.", source)[0]
    assert not fact_guard("Packaging designed for Starbucks in Lisbon.", source)[0]
    assert not fact_guard("The best coffee packaging.", source)[0]
    assert not fact_guard("", source)[0]


def test_consent_gates_all_project_content(ai_settings, mock_ai, projects_dir, demo_assets_dir):
    project = Project.create(projects_dir, "Consent")
    import_paths(project, [demo_assets_dir / "04 Packaging"])
    assert not project.config.ai_consent
    service = service_for_project(project, ai_settings)
    assert service is not None and not service.content_allowed
    generate(project, GenerationRequest(families=["editorial"], count=1), ai_service=service)
    assert mock_ai.requests == []  # nothing was sent without project consent

    # Consent but previews not allowed: text only, no images.
    project.config.ai_consent = True
    project.save_config()
    ai_settings.ai.allow_image_upload = False
    service = service_for_project(project, ai_settings)
    generate(project, GenerationRequest(families=["editorial"], count=1), ai_service=service)
    assert mock_ai.requests and images_sent(mock_ai) == 0


def test_ai_classification_copy_and_cache(ai_settings, mock_ai, projects_dir, demo_assets_dir):
    project = Project.create(projects_dir, "Butter & Bean")
    import_paths(project, [demo_assets_dir])
    project.write_text("brief", "Project: Butter & Bean\nType: brand identity for a coffee shop\nMood: warm and friendly")
    project.config.ai_consent = True
    project.save_config()
    # The user's manual correction must survive AI classification.
    target = next(a for a in project.list_assets(visual_only=True) if a.kind == "logo")
    target.user_kind = "logo"
    project.save_asset(target)

    service = service_for_project(project, ai_settings)
    result = generate(project, GenerationRequest(families=["editorial", "posters"], count=2, seed=7), ai_service=service)
    assert result.ai_used and len(result.versions) == 2
    sent = images_sent(mock_ai)
    assert 0 < sent <= len(project.list_assets(visual_only=True))
    # Previews are small re-encoded JPEGs, never original files.
    for r in mock_ai.requests:
        for part in (r["body"] or {}).get("messages", [{}])[-1].get("content", []) if r["body"] else []:
            if isinstance(part, dict) and part.get("type") == "image_url":
                assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
                assert len(part["image_url"]["url"]) < 200_000

    assets = project.list_assets(visual_only=True)
    assert any(a.kind_source == "ai" for a in assets)
    kept = project.get_asset(target.id)
    assert kept.effective_kind == "logo"

    proposal = next(iter(result.proposals)) if hasattr(result, "proposals") else None
    from behance_studio.projects.versions import VersionManager

    manager = VersionManager(project)
    data = manager.load(result.versions[0].id)
    ai_sections = [s for s in data.plan.sections if s.meta.get("copy_source") == "ai"]
    assert ai_sections and all(s.body == mock_ai.copy_text for s in ai_sections)
    assert all(not s.locked for s in ai_sections)
    del proposal

    # Regenerating identical content reuses the cache: no new requests at all.
    before = len(mock_ai.requests)
    generate(project, GenerationRequest(families=["editorial", "posters"], count=2, seed=7), ai_service=service_for_project(project, ai_settings))
    assert mock_ai.requests[before:] == []
    # A new variation may regroup sections (new copy drafts), but never re-sends previews or the brief.
    before = len(mock_ai.requests)
    generate(project, GenerationRequest(families=["editorial", "posters"], count=2, seed=8), ai_service=service_for_project(project, ai_settings))
    repeated = [r for r in mock_ai.requests[before:] if "data:image/" in json.dumps(r["body"]) or "Rate the intended" in json.dumps(r["body"])]
    assert repeated == []

    # The key never ends up in project files or exports.
    for path in project.root.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes(), path


def test_rejected_copy_keeps_offline_text(ai_settings, mock_ai, projects_dir, demo_assets_dir):
    mock_ai.copy_text = "Award-winning work that boosted sales by 300%."
    project = Project.create(projects_dir, "Guarded")
    import_paths(project, [demo_assets_dir / "04 Packaging", demo_assets_dir / "01 Logo"])
    project.config.ai_consent = True
    project.save_config()
    service = service_for_project(project, ai_settings)
    result = generate(project, GenerationRequest(families=["editorial"], count=1), ai_service=service)
    from behance_studio.projects.versions import VersionManager

    data = VersionManager(project).load(result.versions[0].id)
    assert not any("Award" in (s.body or "") for s in data.plan.sections)
    assert any(s.meta.get("ai_copy_rejected") for s in data.plan.sections)


def test_unreachable_provider_falls_back(projects_dir, demo_assets_dir, monkeypatch):
    monkeypatch.setenv("BEHANCE_STUDIO_OPENAI_API_KEY", SECRET)
    s = AppSettings()
    s.ai.provider = "openai"
    s.ai.base_url = "http://127.0.0.1:9/v1"  # nothing listens here
    s.ai.timeout_s = 5
    s.ai.max_retries = 0
    s.ai.allow_image_upload = True
    project = Project.create(projects_dir, "Fallback")
    import_paths(project, [demo_assets_dir / "01 Logo", demo_assets_dir / "04 Packaging"])
    project.config.ai_consent = True
    project.save_config()
    service = AIService.create(project, s)
    result = generate(project, GenerationRequest(families=["editorial"], count=1), ai_service=service)
    assert len(result.versions) == 1 and not result.ai_used
    assert any("AI" in n for n in result.notes)
