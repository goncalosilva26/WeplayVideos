"""Headless Chromium rendering service (Playwright).

Used for PDF/image exports, proposal thumbnails and the browser-side layout
check. Executable discovery order:

1. Settings → Rendering → browser path, or ``BEHANCE_STUDIO_CHROMIUM``
2. Playwright's own Chromium (installed by the setup script)
3. Any Playwright Chromium found in the usual cache folders
4. Microsoft Edge or Google Chrome installed on the system (Windows always
   ships Edge, so exports keep working even if the download failed)
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from PIL import Image

from behance_studio.core.errors import RenderError
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

_browser_cache: dict[str, str | None] = {}
_cache_lock = threading.Lock()

READY_JS = """
async () => {
  await document.fonts.ready;
  const imgs = Array.from(document.images);
  await Promise.all(imgs.map(img => {
    if (img.complete) { return img.decode ? img.decode().catch(() => null) : null; }
    return new Promise(res => { img.onload = img.onerror = () => res(null); });
  }));
  const vids = Array.from(document.querySelectorAll('video'));
  await Promise.all(vids.map(v => v.readyState >= 2 ? null : new Promise(res => {
    v.addEventListener('loadeddata', () => res(null), {once: true});
    v.addEventListener('error', () => res(null), {once: true});
    setTimeout(() => res(null), 4000);
  })));
  return true;
}
"""

SECTIONS_JS = """
() => Array.from(document.querySelectorAll('.bs-sec')).map(s => {
  const r = s.getBoundingClientRect();
  return {id: s.dataset.sec, type: s.dataset.type, top: r.top + window.scrollY, height: r.height};
})
"""

LAYOUT_CHECK_JS = """
() => {
  const issues = [];
  document.querySelectorAll('.bs-txt').forEach(el => {
    const sec = el.closest('.bs-sec');
    const lines = el.querySelectorAll('.ln');
    let widest = 0;
    lines.forEach(l => { const r = l.getBoundingClientRect(); widest = Math.max(widest, r.width); });
    const box = el.getBoundingClientRect();
    if (el.dataset.role !== 'marquee' && widest > box.width + 1.5) {
      issues.push({kind: 'text_overflow', section: sec ? sec.dataset.sec : '', block: el.dataset.b, overflow: widest - box.width, width: box.width});
    }
  });
  document.querySelectorAll('.bs-img img').forEach(img => {
    if (!img.complete || img.naturalWidth === 0) {
      const blk = img.closest('.bs-b'); const sec = img.closest('.bs-sec');
      issues.push({kind: 'broken_image', section: sec ? sec.dataset.sec : '', block: blk ? blk.dataset.b : '', src: img.getAttribute('src')});
    }
  });
  return issues;
}
"""


def _candidates_from_cache_dirs() -> list[str]:
    roots = []
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        roots.append(env)
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(os.path.join(local, "ms-playwright"))
    else:
        roots += [os.path.expanduser("~/.cache/ms-playwright"), "/opt/pw-browsers"]
    found = []
    for root in roots:
        patterns = [
            os.path.join(root, "chromium-*", "chrome-win*", "chrome.exe"),
            os.path.join(root, "chromium-*", "chrome-linux*", "chrome"),
            os.path.join(root, "chromium-*", "chrome-mac*", "Chromium.app", "Contents", "MacOS", "Chromium"),
        ]
        for pattern in patterns:
            found.extend(sorted(glob.glob(pattern), reverse=True))
    return found


def _system_browsers() -> list[str]:
    if sys.platform.startswith("win"):
        bases = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        out = []
        for base in filter(None, bases):
            out.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
            out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        return out
    if sys.platform == "darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    return [p for p in (shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome", "microsoft-edge")) if p]


def find_browser(preferred: str = "") -> str | None:
    """Return an executable path, or None to let Playwright use its default."""
    key = preferred or "auto"
    with _cache_lock:
        if key in _browser_cache:
            return _browser_cache[key]
    result: str | None = None
    for candidate in (preferred, os.environ.get("BEHANCE_STUDIO_CHROMIUM", "")):
        if candidate and Path(candidate).exists():
            result = candidate
            break
    if result is None:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                default = p.chromium.executable_path
            if default and Path(default).exists():
                result = default
        except Exception as exc:  # noqa: BLE001
            log.debug("Playwright default browser unavailable: %s", exc)
    if result is None:
        for candidate in _candidates_from_cache_dirs() + _system_browsers():
            if candidate and Path(candidate).exists():
                result = candidate
                break
    with _cache_lock:
        _browser_cache[key] = result
    log.info("Rendering browser: %s", result or "not found")
    return result


def browser_available(preferred: str = "") -> bool:
    return find_browser(preferred) is not None


class BrowserSession:
    """A headless Chromium instance bound to the current thread."""

    def __init__(self, preferred_path: str = "") -> None:
        self.preferred_path = preferred_path
        self._pw = None
        self._browser = None

    def __enter__(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RenderError("The rendering engine (Playwright) is not installed.", str(exc)) from exc
        executable = find_browser(self.preferred_path)
        if executable is None:
            raise RenderError(
                "No Chromium-based browser was found for rendering.\n"
                "Run the setup script again, or install Microsoft Edge or Google Chrome, "
                "or choose a browser in Settings → Rendering."
            )
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                executable_path=executable,
                headless=True,
                args=["--font-render-hinting=none", "--disable-lcd-text", "--hide-scrollbars", "--allow-file-access-from-files"],
            )
        except Exception as exc:
            self._pw.stop()
            raise RenderError("The rendering browser could not be started.", str(exc)) from exc
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._pw is not None:
                self._pw.stop()

    def open(self, html_path: Path, width: int, scale: float = 1.0, height: int = 1200, media: str = "screen"):
        assert self._browser is not None
        context = self._browser.new_context(viewport={"width": int(width), "height": int(height)}, device_scale_factor=scale)
        page = context.new_page()
        page.emulate_media(media=media)
        page.goto(Path(html_path).resolve().as_uri(), wait_until="load", timeout=180_000)
        page.evaluate(READY_JS)
        return page

    @staticmethod
    def close_page(page) -> None:
        try:
            context = page.context
            page.close()
            context.close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def sections(page) -> list[dict[str, Any]]:
        return page.evaluate(SECTIONS_JS)

    @staticmethod
    def layout_issues(page) -> list[dict[str, Any]]:
        return page.evaluate(LAYOUT_CHECK_JS)

    @staticmethod
    def _fix_height(path: Path, expected: int) -> Path:
        """Chromium may return ±1px for fractional clips; normalise exactly."""
        with Image.open(path) as img:
            if img.height == expected:
                return path
            fixed = Image.new("RGB", (img.width, expected), img.getpixel((0, img.height - 1))[:3] if img.height else (255, 255, 255))
            fixed.paste(img.convert("RGB").crop((0, 0, img.width, min(img.height, expected))), (0, 0))
        fixed.save(path, "PNG")
        return path

    @staticmethod
    def capture(page, y: float, height: float, width: float, scale: float, out_path: Path, tile_px: int = 4000) -> Path:
        """Capture a vertical region (CSS px) to PNG, tiling tall regions."""
        total_px = int(round(height * scale))
        y_px = int(round(y * scale))
        if total_px <= tile_px:
            page.screenshot(path=str(out_path), clip={"x": 0, "y": y_px / scale, "width": width, "height": total_px / scale}, full_page=True, type="png", animations="disabled")
            return BrowserSession._fix_height(out_path, total_px)
        tiles = []
        done = 0
        index = 0
        while done < total_px:
            h = min(tile_px, total_px - done)
            tile_path = out_path.with_name(f"{out_path.stem}.tile{index}.png")
            page.screenshot(path=str(tile_path), clip={"x": 0, "y": (y_px + done) / scale, "width": width, "height": h / scale}, full_page=True, type="png", animations="disabled")
            BrowserSession._fix_height(tile_path, h)
            tiles.append(tile_path)
            done += h
            index += 1
        images = [Image.open(t) for t in tiles]
        total_h = sum(i.height for i in images)
        out = Image.new("RGB", (images[0].width, total_h))
        cy = 0
        for img in images:
            out.paste(img.convert("RGB"), (0, cy))
            cy += img.height
            img.close()
        out.save(out_path, "PNG")
        for t in tiles:
            t.unlink(missing_ok=True)
        return out_path
