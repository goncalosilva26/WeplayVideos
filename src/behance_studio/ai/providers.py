"""AI provider clients (standard library HTTP only).

Supported:

* ``openai``    – any OpenAI-compatible Chat Completions API (OpenAI,
                  OpenRouter, Azure-compatible gateways, …). Cloud: may be billed.
* ``anthropic`` – the Anthropic Messages API. Cloud: may be billed.
* ``local``     – a local OpenAI-compatible server (Ollama, LM Studio,
                  llama.cpp). Nothing leaves the machine when it runs locally.

Rules enforced here:

* API keys come from :mod:`behance_studio.ai.credentials` and are only ever
  placed in request headers. They are never logged or written to disk.
* Keys are never sent over plain HTTP, except to the local machine.
* Every request has a timeout and a bounded number of retries with backoff.
* Nothing is sent unless the caller (see :mod:`ai.orchestrator`) decided the
  user has configured and authorised it. :meth:`test_connection` only lists
  the available models, which providers do not bill.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from behance_studio import __version__
from behance_studio.ai.credentials import get_api_key
from behance_studio.core.errors import ProviderError
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "local": "http://localhost:11434/v1",
}
DEFAULT_MODELS = {"openai": "gpt-4.1-mini", "anthropic": "claude-sonnet-5-5", "local": "llava"}
CLOUD_PROVIDERS = ("openai", "anthropic")
ANTHROPIC_VERSION = "2023-06-01"
USER_AGENT = f"BehanceStudio/{__version__}"


@dataclass
class ImagePart:
    data: bytes
    mime: str = "image/jpeg"

    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_private_url(url: str) -> bool:
    """Loopback or LAN address (a local model server on this network)."""
    if is_loopback_url(url):
        return True
    host = (urlparse(url).hostname or "").strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(".local") or host.endswith(".lan")
    return ip.is_private or ip.is_link_local


class Provider:
    kind = "base"

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout: float = 60.0, max_retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = max(5.0, float(timeout))
        self.max_retries = max(0, min(5, int(max_retries)))
        self.requests_made = 0
        scheme = urlparse(self.base_url).scheme
        if scheme not in ("http", "https"):
            raise ProviderError(f"The API address must start with https:// (got “{base_url}”).")
        if scheme == "http" and api_key and not is_private_url(self.base_url):
            raise ProviderError("For your security, API keys are only sent over https:// (plain http is allowed for local servers only).")

    def __repr__(self) -> str:  # never include the key
        return f"<{type(self).__name__} {self.base_url} model={self.model}>"

    # ------------------------------------------------------------- facts
    @property
    def is_local(self) -> bool:
        """True when requests stay on this machine or local network."""
        return self.kind == "local" and is_private_url(self.base_url)

    @property
    def may_bill(self) -> bool:
        return self.kind in CLOUD_PROVIDERS

    # ------------------------------------------------------------- http
    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "User-Agent": USER_AGENT}

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(url, data=body, method=method, headers=self._headers())
            try:
                self.requests_made += 1
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProviderError("The AI provider returned an unreadable response.", str(exc)) from exc
            except urllib.error.HTTPError as exc:
                detail = _error_detail(exc)
                if exc.code in (408, 409, 429, 500, 502, 503, 504, 529) and attempt < self.max_retries:
                    wait = _retry_after(exc, attempt)
                    log.info("Provider returned %s; retrying in %.1fs", exc.code, wait)
                    time.sleep(wait)
                    last = exc
                    continue
                raise _http_error(exc.code, detail, self) from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                last = exc
                if attempt < self.max_retries:
                    time.sleep(min(8.0, 0.6 * 2**attempt))
                    continue
                reason = getattr(exc, "reason", exc)
                if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
                    raise ProviderError(f"The AI provider did not answer within {self.timeout:.0f} seconds.") from None
                raise ProviderError(f"Could not reach the AI provider at {self.base_url}.", str(reason)) from None
        raise ProviderError("The AI provider is not responding.", str(last))

    # -------------------------------------------------------------- api
    def list_models(self) -> list[str]:
        raise NotImplementedError

    def complete(self, system: str, prompt: str, images: list[ImagePart] | None = None, max_tokens: int = 600, temperature: float = 0.2) -> str:
        raise NotImplementedError

    def complete_json(self, system: str, prompt: str, images: list[ImagePart] | None = None, max_tokens: int = 600) -> dict[str, Any]:
        text = self.complete(system, prompt, images, max_tokens=max_tokens, temperature=0.1)
        data = extract_json(text)
        if not isinstance(data, dict):
            raise ProviderError("The AI provider did not return the expected structured answer.", text[:400])
        return data

    def test_connection(self) -> str:
        """Check the address, key and model without a billable request."""
        models = self.list_models()
        where = "on this computer" if self.is_local else self.base_url
        if not models:
            return f"Connected to {where}. The provider did not list its models; “{self.model}” will be used."
        if self.model and not any(self.model == m or m.startswith(self.model + ":") for m in models):
            sample = ", ".join(models[:8])
            raise ProviderError(f"Connected to {where}, but the model “{self.model}” is not available.", f"Available models include: {sample}")
        billing = " Requests to this provider may be billed to your account." if self.may_bill else ""
        return f"Connected to {where}. Model “{self.model}” is available.{billing}"


class OpenAICompatibleProvider(Provider):
    kind = "openai"

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def list_models(self) -> list[str]:
        data = self._request("GET", "/models")
        return sorted(str(m.get("id", "")) for m in data.get("data", []) if isinstance(m, dict))

    def complete(self, system: str, prompt: str, images: list[ImagePart] | None = None, max_tokens: int = 600, temperature: float = 0.2) -> str:
        content: list[dict[str, Any]] | str
        if images:
            content = [{"type": "text", "text": prompt}]
            for image in images:
                content.append({"type": "image_url", "image_url": {"url": f"data:{image.mime};base64,{image.b64()}", "detail": "low"}})
        else:
            content = prompt
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = self._request("POST", "/chat/completions", payload)
        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The AI provider returned an unexpected response.", json.dumps(data)[:400]) from exc
        if isinstance(message, list):  # some gateways return content parts
            message = "".join(part.get("text", "") for part in message if isinstance(part, dict))
        return str(message or "")


class LocalProvider(OpenAICompatibleProvider):
    kind = "local"


class AnthropicProvider(Provider):
    kind = "anthropic"

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _path(self, path: str) -> str:
        return path if self.base_url.endswith("/v1") else f"/v1{path}"

    def list_models(self) -> list[str]:
        data = self._request("GET", self._path("/models"))
        return sorted(str(m.get("id", "")) for m in data.get("data", []) if isinstance(m, dict))

    def complete(self, system: str, prompt: str, images: list[ImagePart] | None = None, max_tokens: int = 600, temperature: float = 0.2) -> str:
        content: list[dict[str, Any]] = []
        for image in images or []:
            content.append({"type": "image", "source": {"type": "base64", "media_type": image.mime, "data": image.b64()}})
        content.append({"type": "text", "text": prompt})
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        data = self._request("POST", self._path("/messages"), payload)
        parts = data.get("content") if isinstance(data, dict) else None
        if not isinstance(parts, list):
            raise ProviderError("The AI provider returned an unexpected response.", json.dumps(data)[:400])
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")


PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "openai": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
    "local": LocalProvider,
}


def create_provider(settings) -> Provider | None:
    """Build the configured provider, or None when AI is switched off.

    Raises :class:`ProviderError` when the configuration is incomplete.
    """
    ai = settings.ai
    kind = (ai.provider or "none").lower()
    if kind == "none":
        return None
    cls = PROVIDER_CLASSES.get(kind)
    if cls is None:
        raise ProviderError(f"Unknown AI provider “{ai.provider}”.")
    key = get_api_key(kind)
    if kind in CLOUD_PROVIDERS and not key:
        raise ProviderError("Add an API key in Settings → AI assistance to use this provider.")
    return cls(ai.base_url or DEFAULT_URLS[kind], ai.model or DEFAULT_MODELS[kind], key, ai.timeout_s, ai.max_retries)


# --------------------------------------------------------------- helpers
def extract_json(text: str) -> Any:
    """Parse the first JSON object in a model answer (tolerates code fences)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    try:
        data = json.loads(raw)
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message") or err.get("type") or raw)[:400]
        return str(err)[:400]
    except (json.JSONDecodeError, AttributeError):
        return raw[:400]


def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
    value = exc.headers.get("retry-after") if exc.headers else None
    try:
        if value is not None:
            return max(0.2, min(10.0, float(value)))
    except ValueError:
        pass
    return min(8.0, 0.8 * 2**attempt)


def _http_error(code: int, detail: str, provider: Provider) -> ProviderError:
    if code in (401, 403):
        return ProviderError("The AI provider rejected the API key (or the key lacks permission).", detail)
    if code == 404:
        return ProviderError(f"Not found at {provider.base_url}: check the API address and the model name “{provider.model}”.", detail)
    if code == 429:
        return ProviderError("The AI provider is rate-limiting requests or the account has no remaining credit.", detail)
    if code == 400:
        return ProviderError("The AI provider refused the request (the model may not accept images).", detail)
    return ProviderError(f"The AI provider returned an error ({code}).", detail)
