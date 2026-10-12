# Development status

_Last updated: 2026-10-12 · version 2.0.0-dev · branch `claude/behance-studio-windows-app-o0z32d`_

This file is the persistent record of what exists, what was verified and what
is still open. Update it at every milestone.

## Behance Studio 2.0 — current state

The architecture decision is in [docs/ARCHITECTURE_2.0.md](docs/ARCHITECTURE_2.0.md):
incremental evolution (Python core + PySide6 + one HTML/CSS design runtime),
no destructive migration. Before/after renders: `docs/samples/v1/` (version 1)
and `docs/samples/v2/` (the five 2.0 concepts, same synthetic fixture).

| Area | Status | Verified by |
| --- | --- | --- |
| Design Spec v2 (layers: rotation, perspective, clip masks, fades, shadows, blend, filters, tint, devices, pattern fills, zoom) + JSON schema (`docs/design-spec.schema.json`) + validator for AI output | **Done** | `tests/test_v2_engine.py` (round trip, rejection of bad specs, renderer output) |
| One renderer for preview, export and QA | **Done** (unchanged principle, extended) | rendered samples, export tests |
| Asset nature (photo / artwork / element / document / screen / motion), text-line detection (classical OpenCV, labelled heuristic), crop never cuts detected typography, strongest-asset selection, weak-image hold-back, near-duplicate collapse | **Done (heuristic)** | unit tests on synthetic images and fixture |
| Creative Director (local, rules-based) planning complete case studies: asset selection, cover, narrative order, module per section, pacing, chapters, brand-message use | **Done** | plans printed by `tools/render_concepts.py`, tests |
| Module composition engine (≈30 modules: covers, statement, logo hero/pair/tiles/cards, symbol feature, palette columns/circles, live type specimen, pattern field, full-bleed, duo, trio, filmstrip, letterbox, stage, stage pair, framed poster wall, phones, feed, browser, collage, floating stack, masked trio, chapter cards/spreads, quote band, closing) | **Done** | renders reviewed visually; zero validator errors for all concepts |
| Five concepts by default (Minimal Editorial, Bold Graphic, Premium Photographic, Layered Experimental, Immersive Story) | **Done** | structural distance between every pair > 0.25 (test); classic v1 layouts still available |
| Rendered visual QA (empty surface, blank media, measured overlay contrast, off-balance) + bounded targeted re-composition | **Done (technical checks)** | unit tests; observed fixing a real 2.4:1 contrast cover in an end-to-end run |
| ZIP import (safe extraction) | **Done** | `tests/test_zip_import.py` |
| AI Creative Director via providers: storyboard per concept (structured JSON schema, Anthropic structured outputs), one labelled contact sheet instead of per-asset images, validation and repair (unknown handles/modules/messages dropped, artwork re-staged instead of cropped, counts clamped, cover first / closing last), no AI-written presentation text, offline director fallback, cache | **Done — tested against a local mock server only** | `tests/test_ai_director.py` (validation, fallback, five AI-directed concepts, cache, consent, no images without permission) |
| AI visual critique of rendered sections (rubric 1–5, closed problem list), one bounded round: weakest flagged sections recomposed, kept only if technical rendered checks do not get worse | **Done — mock-tested; off by default** | `tests/test_ai_director.py::test_ai_critique_recomposes_flagged_sections` (real Chromium render) |
| Cost disclosure and limits: per-step estimate before paid runs (UI dialog: Use AI / Generate offline / Cancel; CLI `--allow-paid-ai`), built-in prices only for documented Anthropic models, user-entered prices otherwise, per-generation and monthly limits enforced before each request, real usage from responses, month ledger (counts only) | **Done** | `tests/test_ai_director.py` (meter, ledger, limits, unknown-price blocking), `tests/test_ai.py` |
| Reference screenshots (folder `References`/`Inspiration`/`Moodboard`): never placed in presentations; shown to the AI director as one sheet | **Done** | `tests/test_ai_director.py::test_reference_folder_is_never_shown_but_offered_to_the_director` |
| Local vision model (CLIP via ONNX Runtime, GPU) | **Blocked here** — model host (huggingface.co) is not reachable from this environment | — |
| Generative mockups | **Planned (M4)** — CSS device/frame mockups are done | — |
| Visual editor overlay on the spec | **Planned (M3)** — inspector editing works on 2.0 proposals | — |
| Windows installer | **Planned (M5)** | — |

**Not available for testing:** the Kanoffe reference page (www.behance.net is
blocked by this environment's network policy) and the real Butter & Bean
project files. All 2.0 results use the clearly identified synthetic
fixture from `tools/make_demo_assets.py`; the real 28-asset project is still
needed for the acceptance test.

**Honesty notes:** the local Creative Director and all QA checks are
deterministic rules and measurements, not AI. Passing them does not make a
layout artistically excellent; the renders in `docs/samples/v2/` are the
evidence to judge. The AI director and critique have only been exercised
against `tests/ai_mock.py` (no API key was available and no real provider
was called), so their output quality with a real model is unverified; the
provider code follows the documented Anthropic Messages API request shape.

## Version 1 record

### How to run

| Platform | Command |
| --- | --- |
| Windows 10/11 — first time | `setup_windows.bat` (creates `.venv`, installs pinned deps + Chromium) |
| Windows — start the app | `BehanceStudio.bat` → `.venv\Scripts\pythonw.exe -m behance_studio` with `PYTHONPATH=src` |
| Windows — with a log console | `BehanceStudio_debug.bat` |
| Windows — tests | `run_tests.bat` |
| Linux/macOS (development) | `./run.sh setup`, `./run.sh`, `./run.sh test` |
| CLI | `.venv\Scripts\python -m behance_studio <create|import|generate|list|export|trash|restore|purge|demo|doctor>` |

### Status by priority

### P1 — Working desktop application — **done, verified on Linux (offscreen)**
* PySide6 app: Home, Project (assets, brief, script, generation options),
  Proposals, Viewer/editor, Compare, Export Center, Trash, Settings; sidebar
  navigation, shortcuts, background tasks with progress + cancel, toasts,
  friendly error dialogs, window-state persistence, logging, crash hook.
* Verified by an offscreen GUI test driving the real main window through
  import → generate → view → edit → undo → compare → export → trash → restore,
  plus manual screenshot review of every page.
* **Not yet verified on a real Windows machine** (see Limitations).

### P2 — Automatic generation — **done, tested**
* Import of JPG/PNG/WebP/TIFF/BMP/GIF/SVG/MP4/MOV/WebM/TXT/MD/JSON, folder
  recursion, validation, exact + near-duplicate detection, metadata,
  thumbnails, Unicode names, originals never modified, relink of missing files.
* Measured image analysis and heuristic classification (26 asset kinds,
  EN/PT keywords), roles, before/after pairing.
* Brief parser and `GUIAO_PROJETO.txt` parser (text + JSON) with precedence
  script › brief › inferred › defaults, exact text, order, exclusions,
  missing/ambiguous reference reports with suggestions (never silent
  substitution), strict / auto-sections modes.
* Category inference (20 categories), palette, personality, typography
  pairing from 28 bundled open-licence font files.
* Narrative planning sized to the collection; EN default, PT-PT supported;
  honest generated copy (no invented facts).
* 10-stage pipeline with cancel/progress; per-family failure isolation;
  automatic revision of layouts with validation errors.

### P3 — Six layout families — **done, tested**
Editorial Classic, Cinematic Story, Split Narrative, Graphic Posters, Curated
Gallery, Modular Identity. Tests assert for every family × several seeds:
zero validator errors on the demo project, determinism (same seed → same
layout), structural distance > 0.25 between families (recolouring alone
scores ≤ 0.2), small and large collections, script compliance.

### P4 — PDF export — **done, tested**
Continuous PDF (named page sizes per section group, vector text, embedded
fonts) and A4 PDF (section-boundary pagination, optional margins). Page
counts and sizes are validated after writing.

### P5 — Preview and proposal management — **done, tested**
Gallery with hover-scroll strips, filters, favourites, preferred version,
rename, duplicate, regenerate, apply family; Viewer with zoom/fit/full
screen; Compare (2–3 columns, synchronised scroll); versions never
overwritten; history states; Trash with restore, permanent delete and empty
(all confirmed).

### P6 — Other exports — **done, tested**
JPG, PNG, WebP (segmented ≤ 16,383 px), TIFF (sRGB ICC), HTML package
(offline, link-checked, videos/GIFs play), ZIP (tested), Markdown text;
section subsets, width/quality options, filename patterns, no overwrite,
export history.

### P7 — AI — **done (optional), tested against a mock server only**
OpenAI-compatible, Anthropic and local (Ollama/LM Studio) providers;
per-project consent, separate image consent, small re-encoded previews,
content-hash cache, fact guard for drafted copy, HTTPS-only keys, keyring
storage, free connection test, timeouts/retries, graceful fallback.
**Not exercised against real OpenAI/Anthropic/Ollama endpoints** (no keys or
model servers in the development environment).

### P8 — Advanced editing — **partial**
Done: inspector editing of title/subtitle/text, replace/remove images, focal
point, background colour, spacing, hide section, regenerate one section,
duplicate, move up/down, script-lock confirmation, undo/redo, history restore.
Pending: direct manipulation on the canvas (drag to reorder/resize, crop
handles), per-block typography controls, adding brand-new sections from the
UI, reordering images within a section.

### Test suite

`pytest` — 102 tests (parsers, planning, layout families, generation,
versions/Trash, editing, every export format, AI with a mock server, GUI
smoke). All synthetic fixtures are generated by `tools/make_demo_assets.py`.
Latest results: see "Last test runs" at the end of this file.

### Known limitations

* **Windows not yet run end-to-end.** Development and tests ran on Linux
  (Python 3.14.6). Windows-specific paths (Documents folder via
  `SHGetFolderPathW`, `%APPDATA%`, Edge discovery, `os.startfile`, Credential
  Manager, taskbar app id) are implemented but untested on Windows. Binary
  wheels for every pinned dependency were confirmed for Windows x64 on Python
  3.12, 3.13 and 3.14 (3.11 is not supported: no NumPy 2.5 wheel).
  The batch scripts were reviewed but not executed on Windows.
* **No installer.** Distribution is the folder + `setup_windows.bat`
  (needs Python and internet once). A PyInstaller/MSIX package is pending.
* **Rendering needs Chromium or Edge.** Exports and proposal previews use a
  headless Chromium-family browser; without one, generation still works but
  thumbnails and exports do not.
* **Video in the in-app preview** uses VP9 WebM proxies because the PySide6
  WebEngine build has no H.264; exports keep the original files.
* **Heuristics are approximations.** Asset classification, category and
  personality inference, quality scores and validator scores are estimates
  (the UI labels them as such); users can correct asset types.
* **Brand fonts** that are not among the bundled families are substituted by
  the closest bundled match (noted in the proposal), not installed.
* **UI language** is English; presentations are generated in English or
  Portuguese.
* Very large collections (thousands of assets) are not yet benchmarked;
  the planner's curation path is tested with synthetic sets of ~200.

### Next priorities

1. Run `setup_windows.bat`, the launcher and `run_tests.bat` on clean
   Windows 10 and 11 machines (with and without Chromium download; Edge
   fallback; high-DPI 150 %/200 %; paths with accents and OneDrive
   Documents) and fix anything found.
2. Package a Windows installer (PyInstaller one-folder build + Inno Setup or
   MSIX) with a bundled Python, so no separate Python install is needed.
3. Validate the AI providers against real OpenAI, Anthropic and Ollama
   endpoints; tune prompts; record costs per generation.
4. Canvas-level editing (P8 items above).
5. Performance pass for 500+ asset projects (parallel analysis tuning,
   incremental previews).

### Milestone log

| Commit | Milestone |
| --- | --- |
| `5538732` | Foundation: structure, core infrastructure, project store and library |
| `9100e13` | Asset system: import, validation, metadata, analysis, classification |
| `feb4e7a` | Understanding and planning: script/brief parsers, precedence, direction, narrative |
| `cbd4c40` | Layout engine: six families, composition toolkit, validation, HTML renderer |
| `7ad850f` | Layout tests, deterministic section ids, structural distance metric |
| `8a56eb4` | Generation pipeline, versions, Trash, editing, exports and CLI |
| `3dd36aa` | Desktop UI (all pages) + GUI smoke test |
| `ab2e868` | Optional AI providers + mock-server tests |
| _this commit_ | Windows setup/launcher/test scripts, documentation, status file |

### Last test runs (2026-10-12, Linux, Python 3.14.6)

* Full suite: **102 passed** in 2 min 16 s.
* Later full runs: 101 passed, 1 failed — `test_ui.py::test_full_workflow`,
  where the export step could not start Chromium (`spawn … ENOENT`). Cause:
  a command run during development (`uv pip compile … -o /dev/null`)
  replaced the container's `/dev/null` device with a regular file, so
  processes that open `/dev/null` (Chromium, ffmpeg) fail intermittently.
  This affects only that development container, not the application. The
  same test passes when run on its own (2 passed, 44 s), and the full suite
  should be re-run in a fresh environment to confirm.
* The GUI test now closes any unexpected dialog and fails with its text, and
  waits for background work with a time limit, so this kind of problem shows
  up as a clear failure rather than a hang.
