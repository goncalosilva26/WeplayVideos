"""Ollama: free, local AI on this computer.

This module answers "can local AI run right now, and if not, what exactly
should the user do?" and talks to Ollama's own HTTP API for the parts the
generic provider layer does not cover:

* :func:`detect` – is Ollama installed, running, which models are present,
  does the configured model see images (``vision`` capability)?
* :func:`setup_steps` – step-by-step instructions for the current state.
* :func:`pull_model` – download a model through Ollama, with progress.
* :func:`start_server` – start an installed Ollama that is not running.
* :data:`RECOMMENDED` – vision models evaluated for this app.

Everything here only contacts the Ollama server (``localhost`` by default).
Nothing is sent anywhere else, and nothing costs money.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3-vl:8b"
DOWNLOAD_URL = "https://ollama.com/download/windows"
MIN_VERSION_NOTE = "Qwen3-VL needs a recent Ollama (0.12.7 or newer); update Ollama if the download fails."


@dataclass(frozen=True)
class ModelOption:
    name: str  # Ollama tag
    label: str
    download_gb: float  # approximate download size of the default (4-bit) build
    vram_gb: float  # approximate GPU memory with the app's context size
    note: str


# Evaluated for an NVIDIA RTX 3060 12 GB + 32 GB RAM. Sizes are approximate
# figures for the default 4-bit builds; Ollama shows the exact size on download.
RECOMMENDED: list[ModelOption] = [
    ModelOption("qwen3-vl:8b", "Qwen3-VL 8B", 6.1, 9.0,
                "Recommended. Best at reading text in designs (logos, packaging, posters) and at following the "
                "app's structured answers. Fits entirely in 12 GB of GPU memory with the context this app uses."),
    ModelOption("qwen3-vl:4b", "Qwen3-VL 4B", 3.3, 5.5,
                "Lighter and faster, slightly less accurate. Choose it if other programs need the GPU at the same time."),
    ModelOption("qwen2.5vl:7b", "Qwen2.5-VL 7B", 6.0, 9.0,
                "Previous generation; a solid fallback for Ollama versions without Qwen3-VL."),
    ModelOption("gemma3:12b", "Gemma 3 12B", 8.1, 11.0,
                "Good general vision, but leaves little GPU memory free on a 12 GB card; slower."),
    ModelOption("gemma3:4b", "Gemma 3 4B", 3.3, 5.0,
                "Small and fast; weaker at reading text and at long planning answers."),
]
NOT_RECOMMENDED = {
    "llava": "older model; often misreads text in designs",
    "moondream": "very small; too weak for planning",
}


@dataclass
class OllamaStatus:
    url: str
    model: str
    installed: bool | None = None  # None = unknown (a remote/LAN server)
    binary: str = ""
    running: bool = False
    version: str = ""
    models: list[str] = field(default_factory=list)
    model_installed: bool = False
    vision: bool | None = None
    thinking: bool = False
    error: str = ""

    @property
    def state(self) -> str:
        if not self.running:
            return "not_installed" if self.installed is False else "not_running"
        if not self.model_installed:
            return "model_missing"
        if self.vision is False:
            return "no_vision"
        return "ready"

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def summary(self) -> str:
        return {
            "not_installed": "Ollama is not installed.",
            "not_running": "Ollama is installed but not running." if self.installed else f"No Ollama server answers at {self.url}.",
            "model_missing": f"Ollama {self.version} is running, but the model “{self.model}” is not downloaded yet.",
            "no_vision": f"“{self.model}” cannot see images. Choose a vision model (e.g. {DEFAULT_MODEL}).",
            "ready": f"Local AI ready: Ollama {self.version}, model “{self.model}”.",
        }[self.state]


# ----------------------------------------------------------------- http
def _opener():
    # Ollama runs on this computer: never route it through a proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url: str, timeout: float) -> dict:
    with _opener().open(urllib.request.Request(url, headers={"User-Agent": "BehanceStudio"}), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _post(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", "User-Agent": "BehanceStudio"})
    with _opener().open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def same_model(installed: str, wanted: str) -> bool:
    """``qwen3-vl`` matches ``qwen3-vl:latest``; tags must otherwise match."""
    a, b = installed.strip().lower(), wanted.strip().lower()
    if ":" not in b:
        b += ":latest"
    if ":" not in a:
        a += ":latest"
    return a == b


# ------------------------------------------------------------ detection
def find_binary() -> str:
    found = shutil.which("ollama")
    if found:
        return found
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        candidates += [Path(local) / "Programs" / "Ollama" / "ollama.exe"]
        for base in filter(None, (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"))):
            candidates.append(Path(base) / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/usr/local/bin/ollama")]
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    return next((str(p) for p in candidates if p.exists()), "")


def _is_this_computer(url: str) -> bool:
    from behance_studio.ai.providers import is_loopback_url

    return is_loopback_url(url)


def detect(url: str = DEFAULT_URL, model: str = DEFAULT_MODEL, timeout: float = 2.0) -> OllamaStatus:
    """Check Ollama without downloading or generating anything."""
    url = (url or DEFAULT_URL).rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    status = OllamaStatus(url=url, model=model or DEFAULT_MODEL)
    if _is_this_computer(url):
        status.binary = find_binary()
        status.installed = bool(status.binary)
    try:
        status.version = str(_get(f"{url}/api/version", timeout).get("version", ""))
        status.running = True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        status.error = str(getattr(exc, "reason", exc))
        return status
    if status.installed is False:
        status.installed = True  # it answers, so it is installed (e.g. a custom location)
    try:
        tags = _get(f"{url}/api/tags", timeout).get("models", [])
        status.models = sorted(str(m.get("name") or m.get("model") or "") for m in tags if isinstance(m, dict))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        status.error = str(exc)
        return status
    match = next((m for m in status.models if same_model(m, status.model)), None)
    status.model_installed = match is not None
    if match:
        try:
            info = _post(f"{url}/api/show", {"model": match}, max(timeout, 5.0))
            caps = [str(c).lower() for c in info.get("capabilities") or []]
            if caps:
                status.vision = "vision" in caps
                status.thinking = "thinking" in caps
            else:  # older Ollama without capabilities: look at the model's projector
                status.vision = bool(info.get("projector_info")) or None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.debug("Ollama /api/show failed: %s", exc)
    return status


def gpu_usage(url: str = DEFAULT_URL, timeout: float = 2.0) -> list[dict]:
    """Loaded models and how much of each sits in GPU memory (``/api/ps``)."""
    try:
        models = _get(f"{url.rstrip('/')}/api/ps", timeout).get("models", [])
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for m in models:
        size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
        out.append({"name": m.get("name", ""), "size_gb": round(size / 1e9, 2), "vram_gb": round(vram / 1e9, 2),
                    "gpu_share": round(vram / size, 2) if size else 0.0})
    return out


# -------------------------------------------------------------- actions
def pull_model(url: str, model: str, progress: Callable[[float, str], None] = lambda f, m: None,
               cancelled: Callable[[], bool] = lambda: False, timeout: float = 30.0) -> None:
    """Download ``model`` through Ollama (``/api/pull``), reporting progress.

    Raises ``RuntimeError`` with Ollama's message when the download fails.
    """
    url = url.rstrip("/")
    req = urllib.request.Request(f"{url}/api/pull", data=json.dumps({"model": model, "stream": True}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with _opener().open(req, timeout=timeout) as response:
        for raw in response:
            if cancelled():
                raise InterruptedError("Download cancelled")
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("error"):
                raise RuntimeError(str(event["error"]))
            total, done = event.get("total") or 0, event.get("completed") or 0
            text = str(event.get("status", ""))
            if total:
                progress(min(1.0, done / total), f"{text} — {done / 1e9:.2f} of {total / 1e9:.2f} GB")
            else:
                progress(0.0 if text != "success" else 1.0, text)
            if text == "success":
                return


def start_server(binary: str = "", wait_s: float = 15.0, url: str = DEFAULT_URL) -> bool:
    """Start an installed Ollama in the background; True when it answers."""
    binary = binary or find_binary()
    if not binary:
        return False
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([binary, "serve"], **kwargs)  # noqa: S603 - the user's own Ollama executable
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            _get(f"{url.rstrip('/')}/api/version", 1.0)
            return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.5)
    return False


# --------------------------------------------------------- instructions
def setup_steps(status: OllamaStatus, cli: bool = False) -> list[str]:
    """What to do next, for the current state (Windows wording)."""
    steps = _steps(status)
    if cli:
        steps = [s.replace("press “Download model” here, or in a terminal run:", "run:")
                  .replace("Press “Check again”", "Run: behance-studio ai-check")
                  .replace(" (or press “Start Ollama” here)", "") for s in steps]
    return steps


def _steps(status: OllamaStatus) -> list[str]:
    pull = f"ollama pull {status.model}"
    state = status.state
    if state == "not_installed":
        return [
            f"Download Ollama for Windows from {DOWNLOAD_URL} and run OllamaSetup.exe (no administrator rights needed), "
            "or in a terminal: winget install Ollama.Ollama",
            "Ollama starts automatically after installing (llama icon in the taskbar notification area).",
            f"Download the vision model: press “Download model” here, or in a terminal run:  {pull}",
            "Press “Check again”. Make sure your NVIDIA driver is up to date so Ollama uses the GPU.",
        ]
    if state == "not_running":
        if status.installed:
            return ["Start Ollama from the Start menu (or press “Start Ollama” here).", "Press “Check again”."]
        return [f"Start the Ollama server at {status.url}, or change the address.", "Press “Check again”."]
    if state == "model_missing":
        other = [m for m in status.models if any(same_model(m, r.name) for r in RECOMMENDED)]
        steps = [f"Download the model: press “Download model” here, or in a terminal run:  {pull}",
                 f"About {next((r.download_gb for r in RECOMMENDED if same_model(r.name, status.model)), 6):g} GB; "
                 "the download happens once.", MIN_VERSION_NOTE]
        if other:
            steps.append(f"Or use a model you already have: {', '.join(other)}.")
        return steps
    if state == "no_vision":
        return [f"Choose a vision model in Settings (recommended: {DEFAULT_MODEL}), then:  ollama pull {DEFAULT_MODEL}"]
    return []
