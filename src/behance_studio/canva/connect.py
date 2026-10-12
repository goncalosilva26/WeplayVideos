"""Canva Connect API: put an exported file straight into the user's Canva.

Official flow (Canva Connect REST API, https://www.canva.dev/docs/connect/):

1. **Authorisation** — OAuth 2.0 Authorization Code with PKCE (SHA-256). The
   browser opens ``https://www.canva.com/api/oauth/authorize``; Canva sends
   the user back to ``http://127.0.0.1:<port>/oauth/redirect`` (Canva accepts
   127.0.0.1, not "localhost", for local apps), where this app receives the
   code. Tokens come from ``POST /v1/oauth/token`` (HTTP Basic auth with the
   integration's client ID and secret). Access tokens expire; refresh tokens
   are single-use and replaced on every refresh.
2. **Design import** — ``POST /v1/imports`` with the file as the raw request
   body and an ``Import-Metadata`` header (Base64 title, MIME type), scope
   ``design:content:write``. Canva converts the PowerPoint file into a native
   Canva design. The job is polled with ``GET /v1/imports/{jobId}`` until it
   succeeds (the result holds the design's ``edit_url``) or fails.

The integration (client ID and secret) is created by the user in Canva's
Developer Portal; nothing is hard-coded. The client secret and the refresh
token are kept in the operating system's credential vault (Windows
Credential Manager), never in settings, projects or exports. Requests only
go to Canva, only when the user asks for an upload, and Canva's API is free
to use (no paid request is ever made).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

from behance_studio.ai import credentials
from behance_studio.core.errors import OperationCancelled, UserFacingError
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

API_BASE = "https://api.canva.com/rest"
AUTH_URL = "https://www.canva.com/api/oauth/authorize"
DEVELOPER_PORTAL = "https://www.canva.com/developers/integrations/connect-api"
SCOPES = ["design:content:write", "design:meta:read", "profile:read"]
DEFAULT_PORT = 51723
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MAX_TITLE = 50  # Canva's design title limit (characters)
SECRET_KEY = "canva_client_secret"
REFRESH_KEY = "canva_refresh_token"


class CanvaError(UserFacingError):
    """A Canva request failed (message safe to show)."""


@dataclass
class ImportedDesign:
    id: str
    title: str
    edit_url: str
    view_url: str = ""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge): 64-character verifier, S256 challenge."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ------------------------------------------------------- redirect receiver
_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Behance Studio</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;background:#f6f5f2;color:#222;display:flex;align-items:center;justify-content:center;height:90vh">
<div style="text-align:center;max-width:460px"><h2>{title}</h2><p>{text}</p></div></body></html>"""


class _Receiver:
    """One-shot HTTP listener on 127.0.0.1 for the OAuth redirect."""

    def __init__(self, port: int) -> None:
        self.result: dict[str, str] | None = None
        self.done = threading.Event()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # keep codes out of the logs
                pass

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path.rstrip("/") != "/oauth/redirect":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                ok = "code" in query and "error" not in query
                body = _PAGE.format(
                    title="Connected to Canva" if ok else "Canva did not connect",
                    text="You can close this tab and return to Behance Studio." if ok else
                    "Return to Behance Studio for details. " + (query.get("error_description") or query.get("error") or ""),
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                receiver.result = query
                receiver.done.set()

        try:
            self.server = HTTPServer(("127.0.0.1", port), Handler)
        except OSError as exc:
            raise CanvaError(f"Port {port} on this computer is busy, so Canva cannot send the sign-in back.\n"
                             "Close the program using it, or change the port in Settings → Canva (and in your Canva integration's "
                             "redirect URL).", str(exc)) from exc
        self.server.timeout = 0.5
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.done.is_set():
            self.server.handle_request()

    def close(self) -> None:
        self.done.set()
        try:
            self.server.server_close()
        except OSError:
            pass


# ------------------------------------------------------------------ client
class CanvaConnect:
    """Canva Connect API client (one per integration / user)."""

    _access: dict[str, tuple[str, float]] = {}  # client id -> (access token, expiry) — memory only
    _lock = threading.Lock()

    def __init__(self, client_id: str, client_secret: str | None = None, port: int = DEFAULT_PORT,
                 api_base: str | None = None, auth_url: str | None = None, timeout: float = 60.0) -> None:
        self.client_id = (client_id or "").strip()
        self._secret = client_secret
        self.port = int(port or DEFAULT_PORT)
        self.api_base = (api_base or os.environ.get("BEHANCE_STUDIO_CANVA_API") or API_BASE).rstrip("/")
        self.auth_url = auth_url or os.environ.get("BEHANCE_STUDIO_CANVA_AUTH") or AUTH_URL
        self.timeout = timeout

    @classmethod
    def from_settings(cls, settings) -> "CanvaConnect":
        c = settings.canva
        return cls(c.client_id, port=c.redirect_port)

    # ------------------------------------------------------- credentials
    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/oauth/redirect"

    @property
    def client_secret(self) -> str | None:
        return self._secret or credentials.get_api_key(SECRET_KEY)

    @staticmethod
    def store_client_secret(secret: str) -> str:
        return credentials.set_api_key(SECRET_KEY, secret)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def connected(self) -> bool:
        return self.configured and bool(credentials.get_api_key(REFRESH_KEY))

    def _require_config(self) -> None:
        if not self.client_id or not self.client_secret:
            raise CanvaError("Canva is not set up yet: enter your integration's Client ID and Client secret in Settings → Canva.")

    # ------------------------------------------------------------- OAuth
    def authorization_url(self, challenge: str, state: str) -> str:
        query = {
            "code_challenge": challenge,
            "code_challenge_method": "s256",
            "scope": " ".join(SCOPES),
            "response_type": "code",
            "client_id": self.client_id,
            "state": state,
            "redirect_uri": self.redirect_uri,
        }
        return f"{self.auth_url}?{urllib.parse.urlencode(query, quote_via=urllib.parse.quote)}"

    def authorize(self, open_url: Callable[[str], object] = webbrowser.open, timeout: float = 300.0,
                  cancelled: Callable[[], bool] = lambda: False) -> str:
        """Sign in to Canva in the browser; returns the Canva display name."""
        self._require_config()
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(24)
        receiver = _Receiver(self.port)
        try:
            open_url(self.authorization_url(challenge, state))
            deadline = time.monotonic() + timeout
            while not receiver.done.wait(0.25):
                if cancelled():
                    raise OperationCancelled("Canva sign-in cancelled")
                if time.monotonic() > deadline:
                    raise CanvaError("Canva sign-in timed out. Try again and approve the request in the browser.")
            result = receiver.result or {}
        finally:
            receiver.close()
        if result.get("error"):
            raise CanvaError(f"Canva did not allow the connection: {result.get('error_description') or result['error']}.")
        if not secrets.compare_digest(result.get("state", ""), state):
            raise CanvaError("The answer from Canva could not be verified (state mismatch). Try again.")
        code = result.get("code", "")
        if not code:
            raise CanvaError("Canva did not return an authorisation code. Try again.")
        self._store(self._token({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                 "redirect_uri": self.redirect_uri}))
        try:
            return self.profile_name()
        except CanvaError:
            return ""

    def _token(self, data: dict[str, str]) -> dict:
        self._require_config()
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(f"{self.api_base}/v1/oauth/token", data=body, method="POST", headers={
            "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - fixed https endpoint
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _error_text(exc)
            if exc.code in (400, 401):
                if data.get("grant_type") == "refresh_token":
                    credentials.delete_api_key(REFRESH_KEY)
                    raise CanvaError("The Canva connection has expired. Connect again in Settings → Canva.", detail) from exc
                raise CanvaError("Canva rejected the sign-in. Check the Client ID, the Client secret and that the redirect URL "
                                 f"{self.redirect_uri} is added to your integration.", detail) from exc
            raise CanvaError(f"Canva could not be reached (HTTP {exc.code}).", detail) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise CanvaError("Canva could not be reached. Check the internet connection.", str(exc)) from exc

    def _store(self, tokens: dict) -> None:
        access = tokens.get("access_token")
        if not access:
            raise CanvaError("Canva did not return an access token.")
        expires = time.time() + max(60, int(tokens.get("expires_in", 3600))) - 60
        with self._lock:
            self._access[self.client_id] = (access, expires)
        if tokens.get("refresh_token"):
            credentials.set_api_key(REFRESH_KEY, tokens["refresh_token"])

    def access_token(self) -> str:
        with self._lock:
            cached = self._access.get(self.client_id)
        if cached and cached[1] > time.time():
            return cached[0]
        refresh = credentials.get_api_key(REFRESH_KEY)
        if not refresh:
            raise CanvaError("Behance Studio is not connected to Canva. Connect in Settings → Canva.")
        self._store(self._token({"grant_type": "refresh_token", "refresh_token": refresh}))
        return self._access[self.client_id][0]

    def disconnect(self) -> None:
        """Revoke the refresh token (best effort) and forget it."""
        refresh = credentials.get_api_key(REFRESH_KEY)
        with self._lock:
            self._access.pop(self.client_id, None)
        credentials.delete_api_key(REFRESH_KEY)
        if refresh and self.configured:
            try:
                basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
                req = urllib.request.Request(f"{self.api_base}/v1/oauth/revoke", data=urllib.parse.urlencode({"token": refresh}).encode(),
                                             method="POST", headers={"Authorization": f"Basic {basic}",
                                                                     "Content-Type": "application/x-www-form-urlencoded"})
                urllib.request.urlopen(req, timeout=15).close()  # noqa: S310
            except Exception as exc:  # noqa: BLE001 - forgetting locally is what matters
                log.info("Canva token revocation failed: %s", exc)

    # ------------------------------------------------------------ requests
    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None,
                retries: int = 3) -> dict:
        refreshed = False
        attempt = 0
        while True:
            req = urllib.request.Request(f"{self.api_base}{path}", data=body, method=method,
                                         headers={"Authorization": f"Bearer {self.access_token()}", "Accept": "application/json", **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                    raw = resp.read()
                    return json.loads(raw.decode("utf-8")) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = _error_text(exc)
                if exc.code == 401 and not refreshed:
                    with self._lock:
                        self._access.pop(self.client_id, None)
                    refreshed = True
                    continue
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                    wait = _retry_after(exc, 2.0 * (2 ** attempt))
                    attempt += 1
                    log.info("Canva %s %s: HTTP %s, retrying in %.0fs", method, path, exc.code, wait)
                    time.sleep(wait)
                    continue
                raise _http_error(exc.code, detail) from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt < retries:
                    attempt += 1
                    time.sleep(2.0 * attempt)
                    continue
                raise CanvaError("Canva could not be reached. Check the internet connection.", str(exc)) from exc

    def profile_name(self) -> str:
        data = self.request("GET", "/v1/users/me/profile")
        return str((data.get("profile") or {}).get("display_name") or "")

    # -------------------------------------------------------------- import
    def import_design(self, path: Path, title: str, cancelled: Callable[[], bool] = lambda: False,
                      progress: Callable[[str], None] = lambda m: None, poll_timeout: float = 900.0) -> ImportedDesign:
        """Upload a .pptx and wait until Canva has made it a design."""
        path = Path(path)
        title = (title or path.stem).strip()[:MAX_TITLE] or "Behance Studio"
        meta = json.dumps({"title_base64": base64.b64encode(title.encode("utf-8")).decode("ascii"), "mime_type": PPTX_MIME})
        progress("Uploading to Canva…")
        data = self.request("POST", "/v1/imports", body=path.read_bytes(),
                            headers={"Content-Type": "application/octet-stream", "Import-Metadata": meta})
        job = data.get("job") or {}
        job_id = job.get("id")
        if not job_id:
            raise CanvaError("Canva did not start the import.", json.dumps(data)[:300])
        progress("Canva is converting the design…")
        delay, deadline = 1.5, time.monotonic() + poll_timeout
        while job.get("status") in (None, "in_progress"):
            if cancelled():
                raise OperationCancelled("Canva upload cancelled")
            if time.monotonic() > deadline:
                raise CanvaError("Canva is taking unusually long to convert the file. Check your Canva home page in a few minutes.")
            time.sleep(delay)
            delay = min(delay * 1.5, 6.0)
            job = self.request("GET", f"/v1/imports/{urllib.parse.quote(job_id)}").get("job") or {}
        if job.get("status") != "success":
            err = job.get("error") or {}
            raise CanvaError(_import_failure(err.get("code", ""), err.get("message", "")), json.dumps(err)[:300])
        designs = (job.get("result") or {}).get("designs") or []
        if not designs:
            raise CanvaError("Canva finished the import but returned no design.")
        d = designs[0]
        urls = d.get("urls") or {}
        return ImportedDesign(str(d.get("id", "")), str(d.get("title") or title), str(urls.get("edit_url", "")), str(urls.get("view_url", "")))


def _error_text(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return f"HTTP {exc.code}"
    return raw[:500]


def _retry_after(exc: urllib.error.HTTPError, default: float) -> float:
    try:
        return max(1.0, min(60.0, float(exc.headers.get("Retry-After", default))))
    except (TypeError, ValueError):
        return default


def _http_error(code: int, detail: str) -> CanvaError:
    try:
        payload = json.loads(detail)
        api_code, message = payload.get("code", ""), payload.get("message", "")
    except ValueError:
        api_code, message = "", ""
    if code == 403:
        return CanvaError("Canva refused the request. In the Canva Developer Portal, enable the scopes "
                          f"{', '.join(SCOPES)} for your integration, then connect again.", detail)
    if code == 413 or api_code in ("file_too_big", "payload_too_large"):
        return CanvaError("The file is too large for Canva. Export with 'Standard' image quality and try again.", detail)
    if code == 429:
        return CanvaError("Canva is limiting requests right now (too many imports in a short time). Wait a minute and try again.", detail)
    return CanvaError(f"Canva returned an error (HTTP {code}){': ' + message if message else ''}.", detail)


def _import_failure(code: str, message: str) -> str:
    known = {
        "invalid_file": "Canva could not read the file.",
        "fetch_failed": "Canva could not fetch the file.",
        "duplicate_import": "Canva is already importing this file.",
        "design_import_throttled": "Canva is limiting imports right now. Try again in a minute.",
        "design_creation_throttled": "Canva is limiting new designs right now. Try again in a minute.",
        "internal_error": "Canva had an internal problem converting the file. Try again.",
    }
    text = known.get(code, "Canva could not convert the file.")
    return f"{text}{' (' + message + ')' if message else ''} The file is saved on this computer: you can also import it in Canva by hand."
