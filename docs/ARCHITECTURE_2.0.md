# Behance Studio 2.0 — audit and architecture decision

_Date: 2026-10-12. Status: **decided — incremental evolution, no destructive
migration.**_

## 1. Audit of version 1

### What exists and works (verified by 102 automated tests)

| Area | State | Keep? |
| --- | --- | --- |
| Project storage (folders, SQLite, atomic JSON, versions, history, Trash) | Solid, tested | **Keep** |
| Import (14 formats, validation, duplicates, pHash, metadata, thumbnails, video proxies) | Solid | **Keep**, add ZIP |
| Measured image analysis (saliency, focal point, content box, flatness, colours, faces) | Good signals, no semantics | **Keep**, extend |
| Classification (file names + visual features → 26 kinds) | Heuristic only | Keep as offline fallback; add genuine vision |
| Brief / script parsers, precedence, missing-reference reports | Solid | **Keep** |
| Text measurement (FreeType, variable fonts, exact line breaks) | Solid | **Keep** |
| Single HTML/CSS renderer for preview (Qt WebEngine), HTML, PDF and images (headless Chromium/Edge) | Solid — preview and export already share one representation | **Keep and extend** |
| Exporters (continuous/A4 PDF, PNG/JPG/WebP/TIFF, HTML, ZIP) with post-write validation | Solid | **Keep** |
| PySide6 desktop UI (8 pages, background tasks, compare, export) | Works | **Keep**, restyle the workflow |
| AI providers (OpenAI-compatible, Anthropic, local) with consent, cache, fact guard | Works (mock-tested) | **Keep**, extend to structured design output |

### What limits the product

1. **Composition reads like a document.** Planning is section-type centric
   (logo → palette → typography → packaging …), and the six families render
   each section as heading + image arrangement. The output looks like a
   well-typeset catalogue, not an art-directed case study (see the baseline
   renders in `docs/samples/v1/`).
2. **The design model is too thin for editorial work.** `Block` supports
   rect geometry, cover/contain, radius and a few shadows. There is no
   rotation, masking, device framing, logo tinting, perspective, controlled
   overlaps or per-layer effects, so layered and mockup compositions cannot
   even be expressed.
3. **Compositions are hand-coded per family** (~2,800 lines). Adding
   variety means adding procedural templates — the opposite of what 2.0
   needs.
4. **AI does not direct anything.** It refines classification and copy only;
   no structured design is produced or validated; quality checks are purely
   geometric and run before rendering.
5. **Asset understanding** has no notion of *finished artwork vs raw
   photograph vs reusable brand element*, which is what decides cropping,
   staging and reuse.

None of these limitations comes from Python, PySide6 or the HTML renderer.
They come from the planning model, the layer vocabulary and the composition
strategy.

## 2. Options evaluated

Criteria weighted for this product: visual-composition capability, export
fidelity, editor feasibility, image analysis/AI, Windows packaging, and
migration risk.

| Criterion | A. Python + PySide6 + HTML/CSS engine (current, extended) | B. React/TS UI + Python service | C. Tauri + React/TS + Python sidecar | D. Electron + React/TS (+ Python) | E. Native canvas engine (Skia/Cairo) |
| --- | --- | --- | --- | --- | --- |
| Composition power (masks, blend, transforms, filters, gradients, SVG, variable fonts) | Full CSS/SVG via Chromium | Same (browser) | Same (WebView2 = Chromium) | Same | Strong graphics, weak typography (own text layout) |
| One representation for preview, editor, export | **Already true** (same HTML in Qt WebEngine and headless Chromium) | Possible, needs re-plumbing | Possible; export still needs headless Chromium or Python | Possible | Possible, but loses HTML text layout |
| WYSIWYG editor | Build as JS overlay inside the web view (same DOM as export) | Native strength | Native strength | Native strength | Must build everything |
| Image analysis / AI | Native (NumPy, OpenCV, ONNX Runtime with CUDA/DirectML) | Python service | Python sidecar + IPC | Python sidecar + IPC | Python |
| GPU | Chromium GPU compositing; ONNX GPU for vision | Same | Same | Same | Skia GPU |
| Windows packaging | PyInstaller one-folder + Inno Setup (~450 MB with Qt WebEngine) | Two runtimes | Rust + Python sidecar, smallest shell (WebView2) | Large (~250 MB + Python) | PyInstaller |
| Memory | Moderate (one Chromium) | Higher (browser + service) | Lowest shell, plus Python | Highest | Low |
| Migration cost | **Low** — extend existing code | Rewrite ~4,300 lines of UI + IPC | Rewrite UI + Rust shell + IPC + sidecar packaging | Rewrite UI | Rewrite renderer and text engine |
| Risk to working features | Low | Medium | High | Medium | High |

## 3. Decision

**Option A, evolved as a hybrid where it pays off:** keep the Python core and
the PySide6 shell, and make the HTML/CSS layer the single design runtime:

* **Design Spec v2** — a formal, versioned, layer-based JSON representation
  (sections → layers with geometry, z-order, masks, transforms, effects,
  device frames, asset fitting and text) with a JSON-schema validator. It is
  rendered by one renderer: Qt WebEngine shows it, headless Chromium/Edge
  prints and captures it, and the QA loop screenshots it. What you see is
  what you export.
* **Creative Director → module engine** replaces "section type → template".
  A director (local rules or an AI provider) outputs a structured
  *concept plan*: art direction, asset selection, a sequence of art-directed
  modules with parameters. The composition engine turns modules into
  validated Design Spec layers. AI output is validated against the schema
  before rendering; the local director produces the same structure, so the
  product works offline.
* **Rendered QA loop** — render every section, measure the pixels, fix
  weak sections by changing module parameters, re-render (bounded rounds).
* **The visual editor** will be an HTML/JS overlay inside the existing web
  view, editing the same spec. If its complexity grows, a small TypeScript
  bundle can be added and shipped as static files — no Node.js at runtime.
* **Windows distribution** — PyInstaller one-folder build + Inno Setup
  installer, using Microsoft Edge (always present on Windows 10/11) for
  headless rendering so Chromium need not be bundled.

**Why not a rewrite (B/C/D):** they mostly improve UI development comfort.
They do not improve the thing that matters most — composition quality —
which lives in the planner, layer model and composition engine. They would
cost the working storage, import, export and UI layers, and add a second
runtime plus IPC. Tauri's small shell is attractive, but the app would still
ship Python for analysis and a Chromium for faithful PDF export. If a future
editor needs a web framework, it can live inside the web view, so this
decision does not close that door.

**No destructive migration is required, so implementation proceeds.**

## 4. Migration plan (milestones)

| # | Milestone | Status |
| --- | --- | --- |
| M1 | Design Spec v2 (layers, masks, devices, tint, effects) + schema validator + renderer | **done** |
| M1 | Asset *nature* (photograph / finished artwork / brand element / document) + strongest-asset selection | **done** (heuristic) |
| M1 | Creative Director (local) + module engine + five concepts as the new default | **done** |
| M1 | Rendered QA loop (render → measure → fix → re-render) | **done** (technical checks) |
| M2 | AI Creative Director and AI visual critique via providers (structured output, budgets, cost estimates) | **done** (mock-tested; see `docs/AI_PROVIDERS.md`) |
| M2 | Local vision model (CLIP via ONNX Runtime, GPU) for genuine offline asset understanding | planned — model download needs network access to the model host |
| M3 | Visual editor overlay on the spec; workflow UI (Import → Analyse → Generate → Compare → Export) | planned (ZIP import done) |
| M4 | Optional mockup compositing and image-generation providers | planned |
| M5 | PyInstaller + Inno Setup installer, update flow | planned |

The six v1 layout families remain available as "Classic layouts"; nothing
that works today is removed.
