"""A local stand-in for Ollama's native HTTP API (``/api/*``).

It tests the app's side of the integration — request shapes, detection,
downloads, fallbacks, validation — without a GPU or model. It does not judge
images: design purposes are answered from the file name in the prompt.
Real-model behaviour is covered by ``tests/test_ollama_live.py``, which runs
only when a real Ollama with a vision model is available.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ai_mock import _texts, storyboard_from_prompt

PURPOSES = [
    ("monogram", "monogram", "brand_element"),
    ("logo", "logo", "brand_element"),
    ("palette", "palette", "document_sheet"),
    ("typography", "typography", "document_sheet"),
    ("pattern", "pattern", "brand_element"),
    ("instagram", "social", "flat_artwork"),
    ("poster", "poster", "flat_artwork"),
    ("billboard", "outdoor", "photographed_scene"),
    ("bag", "packaging", "photographed_scene"),
    ("box", "packaging", "photographed_scene"),
    ("cups", "packaging", "photographed_scene"),
    ("dsc", "photo", "photograph"),
]


class MockOllama:
    def __init__(self, models: list[str] | None = None, capabilities: list[str] | None = None) -> None:
        self.models = list(models if models is not None else ["qwen3-vl:8b"])
        self.capabilities = list(capabilities if capabilities is not None else ["completion", "vision"])
        self.version = "0.12.9"
        self.requests: list[dict] = []
        self.overrides: dict[str, tuple[str, str]] = {}  # file name -> (kind, presentation)
        self.boxes: dict[str, list[float]] = {}  # file name -> subject box (0-1000)
        self.cover_scores: dict[str, float] = {}  # file name -> cover score
        self.pull_error = ""
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def chats(self, marker: str = "") -> list[dict]:
        return [r["body"] for r in self.requests if r["path"] == "/api/chat" and marker in json.dumps(r["body"], ensure_ascii=False)]

    def purpose(self, text: str) -> dict:
        m = re.search(r"File name: (.+)", text)
        name = (m.group(1).strip() if m else "").lower()
        kind, presentation = self.overrides.get(name, (None, None)) if name else (None, None)
        if kind is None:
            kind, presentation = next(((k, p) for word, k, p in PURPOSES if word in name), ("photo", "photograph"))
        return {"kind": kind, "presentation": presentation, "shows_logo": kind in ("logo", "packaging"), "text_visible": kind in ("poster", "social"),
                "confidence": 0.9, "description": f"a {kind.replace('_', ' ')}", "tags": [kind],
                "subject_box": self.boxes.get(name, [150, 150, 850, 850]), "cover_score": self.cover_scores.get(name, 0.5)}

    def answer(self, body: dict) -> str:
        text = _texts(body)
        if "CONCEPT TO DEVELOP" in text:
            return json.dumps(storyboard_from_prompt(text))
        if "Allowed kinds" in text:
            return json.dumps(self.purpose(text))
        if "Rate the intended brand personality" in text:
            return json.dumps({"personality": {"warmth": 0.8}, "mood_words": ["warm"], "tone": None})
        if "Rubric for each section score" in text:
            n = len(re.findall(r"^\d+: \w+$", text, flags=re.M))
            return json.dumps({"overall": 4, "summary": "Clear and calm.", "sections": [
                {"section": k, "score": 4, "problems": [], "action": "keep", "note": "fine"} for k in range(n)]})
        return json.dumps({"text": "Packaging for Butter & Bean."})

    def _handler(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                mock.requests.append({"path": self.path, "body": None})
                if self.path == "/api/version":
                    self._send(200, {"version": mock.version})
                elif self.path == "/api/tags":
                    self._send(200, {"models": [{"name": m, "model": m, "size": 6_100_000_000} for m in mock.models]})
                elif self.path == "/api/ps":
                    self._send(200, {"models": [{"name": m, "size": 7_000_000_000, "size_vram": 7_000_000_000} for m in mock.models[:1]]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                mock.requests.append({"path": self.path, "body": body})
                model = body.get("model", "")
                known = any(m == model or m == f"{model}:latest" for m in mock.models)
                if self.path == "/api/show":
                    if not known:
                        self._send(404, {"error": f"model '{model}' not found"})
                    else:
                        self._send(200, {"capabilities": mock.capabilities, "details": {"family": "qwen3vl"}})
                elif self.path == "/api/pull":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    if mock.pull_error:
                        self.wfile.write((json.dumps({"error": mock.pull_error}) + "\n").encode())
                        return
                    events = [{"status": "pulling manifest"}] + [
                        {"status": "pulling 1a2b", "total": 1000, "completed": c} for c in (0, 250, 600, 1000)
                    ] + [{"status": "verifying sha256 digest"}, {"status": "success"}]
                    for event in events:
                        self.wfile.write((json.dumps(event) + "\n").encode())
                    mock.models.append(model)
                elif self.path == "/api/chat":
                    if not known:
                        self._send(404, {"error": f"model '{model}' not found, try pulling it first"})
                    elif "think" in body and "thinking" not in mock.capabilities:
                        self._send(400, {"error": f"\"{model}\" does not support thinking"})
                    else:
                        self._send(200, {"model": model, "message": {"role": "assistant", "content": mock.answer(body)},
                                         "done": True, "done_reason": "stop", "prompt_eval_count": 900, "eval_count": 120})
                else:
                    self._send(404, {"error": "not found"})

        return Handler
