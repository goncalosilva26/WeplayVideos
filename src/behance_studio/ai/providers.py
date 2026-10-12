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
* With a :class:`~behance_studio.ai.costs.SpendMeter` attached, every
  request is authorised against the spending limits *before* it is sent and
  the usage the provider reports is recorded afterwards.

The clients deliberately use the standard library only: one small HTTP
layer serves three provider families (and keeps the Windows build free of
extra SDK dependencies). Anthropic requests follow the current Messages API
shape: structured outputs (``output_config.format``) for JSON answers,
``output_config.effort`` to bound reasoning on models that always think, and
no sampling parameters on models that reject them.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from behance_studio import __version__
from behance_studio.ai.costs import THINKING_EXPECTED, THINKING_HEADROOM, RequestEstimate, SpendMeter, Usage, image_tokens, text_tokens
from behance_studio.ai.credentials import get_api_key
from behance_studio.core.errors import ProviderError
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "local": "http://localhost:11434/v1",
}
DEFAULT_MODELS = {"ollama": "qwen3-vl:8b", "openai": "gpt-4.1-mini", "anthropic": "claude-opus-5-5", "local": "qwen3-vl-8b"}
# Suggested Anthropic models (shown in Settings with their list prices).
ANTHROPIC_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
CLOUD_PROVIDERS = ("openai", "anthropic")
LOCAL_PROVIDERS = ("local", "ollama")
ANTHROPIC_VERSION = "2023-06-01"
USER_AGENT = f"BehanceStudio/{__version__}"


@dataclass
class ImagePart:
    data: bytes
    mime: str = "image/jpeg"
    width: int = 0
    height: int = 0

    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def size(self) -> tuple[int, int]:
        if self.width and self.height:
            return self.width, self.height
        try:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(self.data)) as im:
                self.width, self.height = im.size
        except Exception:  # noqa: BLE001 - unknown size: assume a preview
            self.width, self.height = 640, 640
        return self.width, self.height


def anthropic_model_traits(model: str) -> dict[str, bool]:
    """Request features by Anthropic model generation.

    * ``modern`` – Claude 5 family and Opus 4.6+/Sonnet 4.6: structured
      outputs and ``effort`` are available; reasoning (thinking) may be on
      by default, so ``max_tokens`` needs headroom.
    * ``no_sampling`` – the model rejects ``temperature``/``top_p``.
    """
    m = (model or "").lower()
    five = bool(re.match(r"claude-(opus|sonnet|haiku|fable|mythos)-5", m))
    newer4 = bool(re.match(r"claude-(opus-4-[6-9]|sonnet-4-6)", m))
    return {"modern": five or newer4, "no_sampling": five or bool(re.match(r"claude-opus-4-[7-9]", m))}


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
    parallel = 3  # concurrent requests that make sense for this provider

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout: float = 60.0, max_retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = max(5.0, float(timeout))
        self.max_retries = max(0, min(5, int(max_retries)))
        self.requests_made = 0
        self.meter: SpendMeter | None = None
        self.last_usage = Usage()
        # A server on this machine is contacted directly, never through a proxy.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if is_loopback_url(self.base_url) else urllib.request.build_opener()
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
        return self.kind in LOCAL_PROVIDERS and is_private_url(self.base_url)

    @property
    def may_bill(self) -> bool:
        """Cloud APIs, and any server that is not on this computer/network."""
        return self.kind in CLOUD_PROVIDERS or not is_private_url(self.base_url)

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
                with self._opener.open(request, timeout=self.timeout) as response:
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
                error = _http_error(exc.code, detail, self)
                error.status = exc.code  # type: ignore[attr-defined]
                raise error from None
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

    def complete(self, system: str, prompt: str, images: list[ImagePart] | None = None, max_tokens: int = 600, temperature: float = 0.2,
                 *, schema: dict[str, Any] | None = None, effort: str = "low", purpose: str = "request", shared: str = "",
                 json_mode: bool = False) -> str:
        """Send one request and return the answer text.

        ``shared`` is context that repeats across several requests of a run
        (placed before ``prompt``; Anthropic caches it). ``schema`` asks for
        JSON that matches it where the provider supports structured outputs.
        """
        est = self.estimate(system, shared + prompt, images, max_tokens, effort=effort, purpose=purpose)
        if self.meter is not None:
            self.meter.authorize(est)
        data = self._send(system, prompt, images or [], max_tokens, temperature, schema, effort, shared, json_mode=json_mode or schema is not None)
        self.last_usage = Usage.from_response(data)
        if self.meter is not None:
            self.meter.record(self.last_usage, est)
        return self._text(data)

    def complete_json(self, system: str, prompt: str, images: list[ImagePart] | None = None, max_tokens: int = 600,
                      *, schema: dict[str, Any] | None = None, effort: str = "low", purpose: str = "request", shared: str = "") -> dict[str, Any]:
        text = self.complete(system, prompt, images, max_tokens=max_tokens, temperature=0.1, schema=schema, effort=effort, purpose=purpose,
                             shared=shared, json_mode=True)
        data = extract_json(text)
        if not isinstance(data, dict):
            raise ProviderError("The AI provider did not return the expected structured answer.", text[:400])
        return data

    def thinks(self) -> bool:
        """Does this model spend reasoning tokens on every answer?"""
        return False

    def estimate(self, system: str, prompt: str, images: list[ImagePart] | None, max_tokens: int, effort: str = "low", purpose: str = "request") -> RequestEstimate:
        img = sum(image_tokens(*im.size(), kind=self.kind) for im in images or [])
        think = THINKING_EXPECTED.get(effort, 1600) if self.thinks() else 0
        headroom = THINKING_HEADROOM.get(effort, 6000) if self.thinks() else 0
        answer = max(16, int(max_tokens * 0.6))
        return RequestEstimate(purpose, text_tokens(system, prompt) + img + 12, answer + think, max_tokens + headroom, len(images or []))

    def _send(self, system: str, prompt: str, images: list[ImagePart], max_tokens: int, temperature: float,
              schema: dict[str, Any] | None, effort: str, shared: str, json_mode: bool = False) -> dict[str, Any]:
        raise NotImplementedError

    def _text(self, data: dict[str, Any]) -> str:
        raise NotImplementedError

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

    def _send(self, system: str, prompt: str, images: list[ImagePart], max_tokens: int, temperature: float,
              schema: dict[str, Any] | None, effort: str, shared: str, json_mode: bool = False) -> dict[str, Any]:
        text = f"{shared}\n\n{prompt}" if shared else prompt
        content: list[dict[str, Any]] | str
        if images:
            content = [{"type": "text", "text": text}]
            for image in images:
                content.append({"type": "image_url", "image_url": {"url": f"data:{image.mime};base64,{image.b64()}", "detail": "low"}})
        else:
            content = text
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        return self._request("POST", "/chat/completions", payload)

    def _text(self, data: dict[str, Any]) -> str:
        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The AI provider returned an unexpected response.", json.dumps(data)[:400]) from exc
        if isinstance(message, list):  # some gateways return content parts
            message = "".join(part.get("text", "") for part in message if isinstance(part, dict))
        return str(message or "")


class LocalProvider(OpenAICompatibleProvider):
    kind = "local"
    parallel = 1  # local servers answer one request at a time


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

    def thinks(self) -> bool:
        return anthropic_model_traits(self.model)["modern"]

    def _payload(self, system: str, prompt: str, images: list[ImagePart], max_tokens: int, temperature: float,
                 schema: dict[str, Any] | None, effort: str, shared: str, plain: bool = False) -> dict[str, Any]:
        traits = anthropic_model_traits(self.model)
        content: list[dict[str, Any]] = []
        for image in images:
            content.append({"type": "image", "source": {"type": "base64", "media_type": image.mime, "data": image.b64()}})
        if shared:
            # Repeated context of this run: cached so later requests re-read it cheaply.
            content.append({"type": "text", "text": shared, "cache_control": {"type": "ephemeral"}})
        content.append({"type": "text", "text": prompt})
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        if traits["modern"] and not plain:
            # Reasoning counts towards max_tokens: leave room so the answer is not cut off.
            payload["max_tokens"] = max_tokens + THINKING_HEADROOM.get(effort, 6000)
            config: dict[str, Any] = {"effort": effort}
            if schema is not None:
                config["format"] = {"type": "json_schema", "schema": schema}
            payload["output_config"] = config
        elif traits["modern"]:
            payload["max_tokens"] = max_tokens + THINKING_HEADROOM.get(effort, 6000)
        if not traits["no_sampling"]:
            payload["temperature"] = temperature
        return payload

    def _send(self, system: str, prompt: str, images: list[ImagePart], max_tokens: int, temperature: float,
              schema: dict[str, Any] | None, effort: str, shared: str, json_mode: bool = False) -> dict[str, Any]:
        payload = self._payload(system, prompt, images, max_tokens, temperature, schema, effort, shared)
        try:
            return self._request("POST", self._path("/messages"), payload)
        except ProviderError as exc:
            if getattr(exc, "status", None) == 400 and "output_config" in payload:
                # A gateway or snapshot without structured outputs/effort: ask plainly once.
                log.info("Provider refused output_config (%s); retrying without it", exc.detail)
                plain = self._payload(system, prompt, images, max_tokens, temperature, None, effort, shared, plain=True)
                return self._request("POST", self._path("/messages"), plain)
            raise

    def _text(self, data: dict[str, Any]) -> str:
        parts = data.get("content") if isinstance(data, dict) else None
        if not isinstance(parts, list):
            raise ProviderError("The AI provider returned an unexpected response.", json.dumps(data)[:400])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
        stop = data.get("stop_reason")
        if stop == "refusal":
            raise ProviderError("The AI model declined this request.", str(data.get("stop_details") or "")[:400])
        if stop == "max_tokens" and not text.strip():
            raise ProviderError("The AI answer was cut off before it was complete.", "stop_reason=max_tokens")
        return text


class OllamaProvider(Provider):
    """Ollama's native API (``/api/chat``): free and local.

    * JSON answers use Ollama's structured outputs (``format`` = the JSON
      schema), so small local models return parseable, schema-shaped JSON.
    * The context window (``num_ctx``) is sized per request: Ollama's
      default is too small for the creative-direction prompt.
    * Models that can "think" (e.g. some Qwen3-VL builds) are asked not to,
      which keeps answers fast and within the token budget.
    * The model stays loaded for 15 minutes between requests (``keep_alive``).
    """

    kind = "ollama"
    parallel = 1  # Ollama answers one request at a time on a single GPU

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self._caps: list[str] | None = None

    def capabilities(self) -> list[str]:
        if self._caps is None:
            try:
                info = self._request("POST", "/api/show", {"model": self.model})
                self._caps = [str(c).lower() for c in info.get("capabilities") or []]
            except ProviderError:
                self._caps = []
        return self._caps

    def list_models(self) -> list[str]:
        data = self._request("GET", "/api/tags")
        return sorted(str(m.get("name") or m.get("model") or "") for m in data.get("models", []) if isinstance(m, dict))

    def test_connection(self) -> str:
        from behance_studio.ai.ollama import detect

        status = detect(self.base_url, self.model, timeout=5.0)
        if not status.ready:
            from behance_studio.ai.ollama import setup_steps

            raise ProviderError(status.summary(), "\n".join(setup_steps(status)))
        return f"{status.summary()} Runs on this computer: free, nothing leaves your PC."

    @staticmethod
    def context_for(prompt_chars: int, images: list[ImagePart], answer_tokens: int) -> int:
        image_tokens = 0
        for im in images:
            w, h = im.size()
            image_tokens += int((w / 28) * (h / 28)) + 16  # vision patches (generous)
        need = int(prompt_chars / 3.2) + image_tokens + answer_tokens + 512
        size = 8192
        while size < need and size < 32768:
            size *= 2
        return size

    def _send(self, system: str, prompt: str, images: list[ImagePart], max_tokens: int, temperature: float,
              schema: dict[str, Any] | None, effort: str, shared: str, json_mode: bool = False) -> dict[str, Any]:
        text = f"{shared}\n\n{prompt}" if shared else prompt
        user: dict[str, Any] = {"role": "user", "content": text}
        if images:
            user["images"] = [im.b64() for im in images]
        answer = max(64, int(max_tokens * 1.5))
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, user],
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": temperature, "num_predict": answer,
                        "num_ctx": self.context_for(len(system) + len(text), images, answer)},
        }
        if schema is not None:
            payload["format"] = schema
        elif json_mode:
            payload["format"] = "json"
        if "thinking" in self.capabilities():
            payload["think"] = False
        try:
            return self._request("POST", "/api/chat", payload)
        except ProviderError as exc:
            status = getattr(exc, "status", None)
            detail = (exc.detail or "").lower()
            if status == 404 or "not found" in detail:
                raise ProviderError(f"The model “{self.model}” is not downloaded in Ollama. Run:  ollama pull {self.model}", exc.detail) from None
            if status == 400 and "think" in payload and "think" in detail:
                payload.pop("think")
                return self._request("POST", "/api/chat", payload)
            if "memory" in detail:
                raise ProviderError(f"Not enough memory to run “{self.model}”. Close other GPU programs or choose a smaller model "
                                    "(e.g. qwen3-vl:4b).", exc.detail) from None
            if exc.message.startswith("Could not reach"):
                raise ProviderError(f"Ollama is not running at {self.base_url}. Start Ollama and try again.", exc.detail) from None
            raise

    def _text(self, data: dict[str, Any]) -> str:
        message = data.get("message") if isinstance(data, dict) else None
        if not isinstance(message, dict):
            raise ProviderError("Ollama returned an unexpected response.", json.dumps(data)[:400])
        text = str(message.get("content") or "")
        if data.get("done_reason") == "length" and extract_json(text) is None:
            raise ProviderError("The local model's answer was cut off before it was complete.", "done_reason=length")
        return text


PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
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
    timeout = ai.timeout_s
    if kind in LOCAL_PROVIDERS:
        timeout = max(timeout, 300.0)  # loading a model and answering on a local GPU/CPU takes longer
    return cls(ai.base_url or DEFAULT_URLS[kind], ai.model or DEFAULT_MODELS[kind], key, timeout, ai.max_retries)


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
