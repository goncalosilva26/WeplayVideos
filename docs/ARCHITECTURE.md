# Architecture

Behance Studio is a Python 3.12–3.14 application (PySide6 / Qt 6 desktop UI,
Pillow + NumPy + OpenCV image analysis, a headless Chromium for rendering).
About 20,000 lines in `src/behance_studio`, organised as a pipeline of plain
Python modules with no UI dependencies; the UI and the CLI are thin layers on
top.

```
assets/ ──► brief/ ──► design/ ──► planning/ ──► layout/ ──► render/ ──► export/
 import      brief &     category,    narrative     six families,  HTML +      PDF, A4, images,
 analysis    script      palette,     plan          composer,      Chromium    HTML package, ZIP
 classify    precedence  typography,  (sections)    validation     (Playwright)
                         personality
                    └──────── generation/pipeline.py (10 stages, cancel, progress) ───────┘
projects/  storage (project folder, SQLite, versions, history, Trash, library)
ai/        optional providers + orchestrator (refines classification, direction, copy)
ui/        PySide6 desktop app        cli.py   command line
```

## Storage

A project is a self-contained folder:

```
<Project>/
  project.json     portable configuration (atomic writes, schema-migrated)
  project.db       SQLite: assets, versions, exports, key/value (PRAGMA user_version migrations)
  brief.txt / GUIAO_PROJETO.txt
  Assets/          copies of imported originals (originals are never modified)
  Versions/NNN/    proposal.json (spec, plan, direction, geometry, quality report),
                   history/ (every edited state), thumb.jpg, strip.jpg
  Exports/         default export destination
  Trash/           trashed versions and removed asset copies (recoverable)
  Cache/           thumbnails, analysis, render sources, previews, AI answers (disposable)
```

`Project.repair()` rebuilds the database from `Versions/*/proposal.json` if
needed. All JSON writes are atomic (temp file + `os.replace`). App settings and
the recent-projects library live in `%APPDATA%\BehanceStudio`.

## Assets (`assets/`)

* `importer.py` — walks files/folders, validates every file (decoding, not
  just extensions), hashes (SHA-256) for exact duplicates, pHash for
  near-duplicates, reads metadata (size, EXIF orientation, DPI, alpha,
  animation, video duration/fps/codec via ffmpeg), adopts `brief.txt` /
  `GUIAO_PROJETO.txt`.
* `analysis.py` — measured features on a 768 px proxy: luminance grid,
  colourfulness, edge density, background uniformity, content bounding box,
  spectral-residual saliency and focal point, face detection, palette-likeness.
* `classify.py` — weighted evidence from file name/folder keywords (EN/PT)
  and visual features → 26 asset kinds with confidence and reasons.
* `roles.py` — hero/cover/closing suitability, quality, before/after pairs,
  near-duplicate clusters.
* `derivatives.py` — thumbnails, size-bucketed render sources, video poster
  frames and VP9 preview proxies (Qt WebEngine's pip build has no H.264).

## Understanding (`brief/`, `design/`)

* `script.py` parses `GUIAO_PROJETO.txt` (text or JSON) and resolves every
  image reference against the project (exact → stem → path → glob → fuzzy
  *suggestion only*), reporting missing, ambiguous and excluded references.
* `brief.py` extracts fields, brand messages, HEX colours, font roles, a
  six-axis personality (with negation/intensity handling), mood, family
  preferences and tone.
* `directives.py` applies the precedence script › brief › inference ›
  defaults and records the provenance of every decision.
* `design/` infers the category (20 categories), builds the palette
  (brief colours exact; otherwise weighted image colours by asset kind) and
  ranks bundled font pairings against the personality.

## Planning (`planning/`)

`planner.py` turns assets + directives into a `PresentationPlan` — an ordered
list of `SectionPlan`s (cover, intro, logo, palette, typography, packaging,
campaign, … closing). Category templates and affinity groups decide the
order; the plan is sized to the collection (compact for a few assets,
curated with hero selection and duplicate suppression for hundreds). With a
script, the script's sections are used verbatim. Section IDs are derived from
content, so plans are reproducible.

## Layout (`layout/`)

* `engine.py` — `ProposalSpec(family, seed, creativity, width, overrides)` →
  plan adaptations → family composition.
* `families/*.py` — six complete design systems (grid, spacing scale, type
  hierarchy, colour strategy, composition patterns). Each section is composed
  with its own RNG seeded from `(family, seed, section id, variant)`, so a
  proposal can be regenerated exactly and one section can be re-rolled alone.
* `composer.py` — the shared toolkit: justified rows, columns, masonry,
  bento packing, candidate arrangements scored for scale balance and
  whitespace, overlay contrast checks, quiet-corner detection.
* `fitting.py` — media integrity: per-kind maximum crop (logos, posters,
  palettes, UI and typography are never cropped; photographs only within
  limits), content-bbox-safe crops, focal points, a native-resolution
  upscale limit.
* `text.py` — real text measurement with the bundled fonts (FreeType, variable
  axes) at layout time; line breaks are computed in Python and rendered as
  explicit lines, so the browser output matches the plan.
* `validate.py` — overlap, overflow, out-of-bounds, contrast (WCAG ratio),
  excessive crop/upscale, tiny images, empty or repetitive sections, script
  compliance; plus a structural signature and `layout_distance` used to prove
  that families and seeds produce structurally different layouts. The
  pipeline revises proposals with errors automatically.

## Rendering and export (`render/`, `export/`)

One HTML renderer (`render/html.py`) produces absolute-positioned sections
from the computed geometry, in three modes: in-app preview (with a
QWebChannel bridge for click-to-select), standalone HTML package, and static
pages for PDF/raster. A headless Chromium (Playwright's, or Edge/Chrome)
prints PDFs (named page sizes per section group; A4 pagination at section
boundaries) and captures rasters in device-pixel-snapped tiles that are
merged and written with an sRGB profile. Every export is validated after
writing (page count/size, image dimensions, HTML link check, ZIP test);
invalid files are removed and reported. Pillow is a fallback preview
renderer.

## Generation (`generation/`)

`pipeline.generate()` runs ten weighted stages with a `CancelToken` and
progress events; failures of one family do not stop the others.
`editing.py` implements inspector edits as overrides on the proposal spec
(content edits respect script locks), section regeneration, moves,
duplication, family switching and new-seed versions; every save adds a
history state.

## AI (`ai/`)

`providers.py` — urllib clients for OpenAI-compatible, Anthropic and local
servers (timeouts, retries, HTTPS-only keys, model listing for free
connection tests). `orchestrator.py` — consent gating, preview preparation,
content-hash caching, the copy fact guard. `credentials.py` — keyring
storage. See [AI_PROVIDERS.md](AI_PROVIDERS.md).

## UI (`ui/`)

`AppState` (Qt signals for project/assets/versions changes) and `Actions`
(import, generate, demo — each in a background `TaskRunner` thread with a
cancellable progress dialog). Pages: Home, Project (asset grid, brief/script
editors, generation options), Proposals, Viewer (Qt WebEngine preview,
inspector, undo/redo, history), Compare (synchronised scrolling), Export
Center, Trash, Settings. A dark design system lives in `theme.py` with an
SVG icon set rendered at runtime.

## Tests

`tests/` (pytest) runs everything against synthetic fixtures
(`tools/make_demo_assets.py` draws a complete fictional brand identity,
including a video): parsers, planning, all families × seeds (determinism,
structural distance, zero validator errors), generation, versions, Trash,
editing, every export format, AI against a local mock server, and an
offscreen GUI smoke test that drives the real main window.
