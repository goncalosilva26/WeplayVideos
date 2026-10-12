"""A local stand-in for the Canva Connect API (OAuth + design imports).

Implements the documented request/response shapes the app relies on and
*verifies* what the client sends: PKCE S256 (the code verifier must hash to
the challenge given at authorisation), HTTP Basic client authentication,
single-use rotating refresh tokens, bearer tokens, the ``Import-Metadata``
header (Base64 title, MIME type) and a PowerPoint file as the raw body.
It is not Canva: it cannot tell whether Canva's converter would accept or
render a file, only that the protocol is followed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import threading
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class MockCanva:
    def __init__(self, client_id: str = "OC-test-client", client_secret: str = "cnvca-secret") -> None:
        self.client_id, self.client_secret = client_id, client_secret
        self.codes: dict[str, dict] = {}
        self.access: dict[str, bool] = {}  # token -> valid
        self.refresh: dict[str, bool] = {}  # token -> unused
        self.jobs: dict[str, dict] = {}
        self.uploads: list[dict] = []
        self.revoked: list[str] = []
        self.log: list[tuple[str, str]] = []
        self.throttle_imports = 0  # answer the next N imports with HTTP 429
        self.fail_imports = False
        self.polls_before_success = 2
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    @property
    def api_base(self) -> str:
        return f"{self.url}/rest"

    @property
    def auth_url(self) -> str:
        return f"{self.url}/api/oauth/authorize"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def expire_access_tokens(self) -> None:
        with self.lock:
            for k in self.access:
                self.access[k] = False

    # ------------------------------------------------- the user's browser
    def browser(self, url: str, approve: bool = True) -> None:
        """What the browser does: Canva's consent page, then the redirect."""
        parsed = urllib.parse.urlparse(url)
        assert parsed.path == "/api/oauth/authorize", parsed.path
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        assert q["response_type"] == "code" and q["code_challenge_method"].lower() == "s256"
        assert q["client_id"] == self.client_id
        assert q["redirect_uri"].startswith("http://127.0.0.1:"), "Canva accepts 127.0.0.1 redirects for local apps"
        assert set(q["scope"].split(" ")) >= {"design:content:write"}
        if approve:
            code = secrets.token_urlsafe(16)
            with self.lock:
                self.codes[code] = {"challenge": q["code_challenge"], "redirect_uri": q["redirect_uri"]}
            target = f"{q['redirect_uri']}?{urllib.parse.urlencode({'code': code, 'state': q['state']})}"
        else:
            target = f"{q['redirect_uri']}?{urllib.parse.urlencode({'error': 'access_denied', 'error_description': 'The user declined', 'state': q['state']})}"
        threading.Thread(target=lambda: urllib.request.urlopen(target, timeout=10).read(), daemon=True).start()

    # ------------------------------------------------------------- server
    def _issue(self) -> dict:
        at, rt = "at-" + secrets.token_hex(8), "rt-" + secrets.token_hex(8)
        self.access[at] = True
        self.refresh[rt] = True
        return {"access_token": at, "refresh_token": rt, "token_type": "Bearer", "expires_in": 14400, "scope": "design:content:write"}

    def _handler(self):
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def _json(self, code: int, payload: dict, headers: dict | None = None) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _bearer_ok(self) -> bool:
                auth = self.headers.get("Authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else ""
                with mock.lock:
                    ok = mock.access.get(token, False)
                if not ok:
                    self._json(401, {"code": "invalid_access_token", "message": "Access token is invalid or expired"})
                return ok

            def _basic_ok(self) -> bool:
                expected = base64.b64encode(f"{mock.client_id}:{mock.client_secret}".encode()).decode()
                if self.headers.get("Authorization") != f"Basic {expected}":
                    self._json(401, {"error": "invalid_client", "error_description": "Client authentication failed"})
                    return False
                return True

            def do_POST(self) -> None:  # noqa: N802
                path = urllib.parse.urlparse(self.path).path
                mock.log.append(("POST", path))
                if path == "/rest/v1/oauth/token":
                    body = self._body()
                    if not self._basic_ok():
                        return
                    form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode()).items()}
                    with mock.lock:
                        if form.get("grant_type") == "authorization_code":
                            info = mock.codes.pop(form.get("code", ""), None)
                            if info is None:
                                return self._json(400, {"error": "invalid_grant", "error_description": "Unknown code"})
                            challenge = _b64url(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
                            if challenge != info["challenge"] or form.get("redirect_uri") != info["redirect_uri"]:
                                return self._json(400, {"error": "invalid_grant", "error_description": "PKCE verification failed"})
                            return self._json(200, mock._issue())
                        if form.get("grant_type") == "refresh_token":
                            rt = form.get("refresh_token", "")
                            if not mock.refresh.get(rt):
                                return self._json(400, {"error": "invalid_grant", "error_description": "Refresh token used or unknown"})
                            mock.refresh[rt] = False  # single use
                            return self._json(200, mock._issue())
                    return self._json(400, {"error": "unsupported_grant_type"})
                if path == "/rest/v1/oauth/revoke":
                    body = self._body()
                    if self._basic_ok():
                        mock.revoked.append(urllib.parse.parse_qs(body.decode()).get("token", [""])[0])
                        self._json(200, {})
                    return
                if path == "/rest/v1/imports":
                    body = self._body()
                    if not self._bearer_ok():
                        return
                    if mock.throttle_imports > 0:
                        mock.throttle_imports -= 1
                        return self._json(429, {"code": "too_many_requests", "message": "Slow down"}, {"Retry-After": "1"})
                    try:
                        meta = json.loads(self.headers.get("Import-Metadata", ""))
                        title = base64.b64decode(meta["title_base64"]).decode("utf-8")
                    except Exception:  # noqa: BLE001
                        return self._json(400, {"code": "invalid_header", "message": "Import-Metadata is invalid"})
                    if self.headers.get("Content-Type") != "application/octet-stream":
                        return self._json(400, {"code": "invalid_content_type", "message": "Expected application/octet-stream"})
                    try:
                        with zipfile.ZipFile(io.BytesIO(body)) as z:
                            pptx = "ppt/presentation.xml" in z.namelist()
                    except zipfile.BadZipFile:
                        pptx = False
                    job = "job-" + secrets.token_hex(4)
                    with mock.lock:
                        mock.uploads.append({"title": title, "mime_type": meta.get("mime_type"), "size": len(body), "pptx": pptx})
                        mock.jobs[job] = {"polls": mock.polls_before_success, "title": title, "valid": pptx}
                    return self._json(200, {"job": {"id": job, "status": "in_progress"}})
                self._json(404, {"code": "not_found", "message": path})

            def do_GET(self) -> None:  # noqa: N802
                path = urllib.parse.urlparse(self.path).path
                mock.log.append(("GET", path))
                if path == "/rest/v1/users/me/profile":
                    if self._bearer_ok():
                        self._json(200, {"profile": {"display_name": "Ada Designer"}})
                    return
                if path.startswith("/rest/v1/imports/"):
                    if not self._bearer_ok():
                        return
                    jid = path.rsplit("/", 1)[-1]
                    with mock.lock:
                        job = mock.jobs.get(jid)
                        if job is None:
                            return self._json(404, {"code": "not_found", "message": "No such job"})
                        if job["polls"] > 0:
                            job["polls"] -= 1
                            return self._json(200, {"job": {"id": jid, "status": "in_progress"}})
                    if mock.fail_imports or not job["valid"]:
                        return self._json(200, {"job": {"id": jid, "status": "failed",
                                                        "error": {"code": "invalid_file", "message": "The file could not be read"}}})
                    did = "DAF" + secrets.token_hex(5).upper()
                    return self._json(200, {"job": {"id": jid, "status": "success", "result": {"designs": [{
                        "id": did, "title": job["title"],
                        "urls": {"edit_url": f"https://www.canva.com/design/{did}/edit", "view_url": f"https://www.canva.com/design/{did}/view"},
                        "thumbnail": {"width": 376, "height": 452, "url": "https://example.invalid/thumb.png"},
                        "created_at": 1700000000, "updated_at": 1700000000}]}}})
                self._json(404, {"code": "not_found", "message": path})

        return H
