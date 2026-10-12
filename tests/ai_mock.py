"""A local mock of the Anthropic Messages API and OpenAI-compatible APIs.

Used by the AI tests: it records every request, answers asset recognition,
brief, copy, creative-direction and critique prompts with fixed structured
JSON, and reports token usage like the real APIs. No network, no cost.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _texts(body: dict) -> str:
    parts = []
    for message in body.get("messages", []):
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts += [c.get("text", "") for c in content if isinstance(c, dict)]
    return "\n".join(parts)


def storyboard_from_prompt(text: str, tamper: bool = True) -> dict:
    """Echo the baseline storyboard back, reversed in the middle, plus some
    invalid items the validator must reject."""
    lines = re.findall(r"^(\d+)\. (\w+) \[([A-Z0-9 ?]*)\]$", text, flags=re.M)
    cover = {"module": "cover_logo", "assets": [], "message": 0}
    sections = []
    for _, module, handles in lines:
        ids = [h for h in handles.split() if h != "?"]
        if module in ("cover_logo", "cover_hero", "cover_split", "collage"):
            cover = {"module": module, "assets": ids, "message": 0}
            continue
        if module == "closing":
            continue
        chapter = "identity" if module in ("chapter", "chapter_spread") else "none"
        sections.append({"module": module, "assets": ids, "chapter": chapter, "message": -1, "why": f"{module} keeps the rhythm"})
    if len(sections) > 3:
        sections[1:-1] = list(reversed(sections[1:-1]))
    if tamper:
        sections.append({"module": "hologram", "assets": ["A1"], "chapter": "none", "message": -1, "why": "invented"})
        sections.append({"module": "duo", "assets": ["A999", "A998"], "chapter": "none", "message": -1, "why": "unknown handles"})
        sections.append({"module": "quote_band", "assets": [], "chapter": "none", "message": 42, "why": "missing message"})
    handles = re.findall(r"^(A\d+) · ", text, flags=re.M)
    return {
        "idea": "Lead with the warmest photographs and let the identity breathe.",
        "cover": cover,
        "sections": sections,
        "closing_message": -1,
        "left_out": [{"asset": handles[-1], "reason": "a weaker repeat of the hero image"}] if handles else [],
    }


class MockAI:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.fail_next = 0
        self.copy_text = "Packaging for Butter & Bean, shown across the product range."
        self.kind = "packaging"
        self.critique_action = "recompose"
        self.usage = (1200, 300)
        self.reject_output_config = False
        self.storyboard = None  # fixed storyboard to answer with (default: echo the baseline)
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

    def requests_for(self, marker: str) -> list[dict]:
        return [r for r in self.requests if r["body"] and marker in json.dumps(r["body"], ensure_ascii=False)]

    def answer(self, body: dict) -> str:
        text = _texts(body)
        if "CONCEPT TO DEVELOP" in text:
            return json.dumps(self.storyboard if self.storyboard is not None else storyboard_from_prompt(text))
        if "Rubric for each section score" in text:
            n = len(re.findall(r"^\d+: \w+$", text, flags=re.M))
            sections = [{"section": k, "score": 4, "problems": [], "action": "keep", "note": "fine"} for k in range(n)]
            if n > 2:
                sections[2] = {"section": 2, "score": 2, "problems": ["too_empty"], "action": self.critique_action, "note": "feels empty"}
            return json.dumps({"overall": 4, "summary": "Strong opening; one section feels empty.", "sections": sections})
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
                self._send(200, {"data": [{"id": "vision-model"}, {"id": "other-model"}, {"id": "claude-opus-5-5"}]})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                mock.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if mock.fail_next:
                    mock.fail_next -= 1
                    self._send(503, {"error": {"message": "overloaded"}})
                    return
                if mock.reject_output_config and "output_config" in body:
                    self._send(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "output_config: unsupported"}})
                    return
                answer = mock.answer(body)
                tin, tout = mock.usage
                if self.path.endswith("/messages"):
                    self._send(200, {"content": [{"type": "thinking", "thinking": "", "signature": "x"}, {"type": "text", "text": answer}],
                                     "stop_reason": "end_turn", "usage": {"input_tokens": tin, "output_tokens": tout}})
                else:
                    self._send(200, {"choices": [{"message": {"role": "assistant", "content": answer}}],
                                     "usage": {"prompt_tokens": tin, "completion_tokens": tout}})

        return Handler
