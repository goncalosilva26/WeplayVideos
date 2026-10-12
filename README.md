# Behance Studio

A Windows 10/11 desktop application that turns a folder of raw design material
into complete, portfolio-ready presentations for Behance.

Create a project, drop in your logos, mockups, photographs, posters, social
media pieces and videos, optionally add a creative brief (`brief.txt`) or a
detailed script (`GUIAO_PROJETO.txt`), and press **Generate Projects**. Behance
Studio analyses the material, plans a narrative, and designs one complete
proposal in each of six distinct layout families. Compare them side by side,
choose the one you prefer, refine it if needed, and export to PDF, images, an
HTML package or a ZIP.

Everything works offline. AI providers are optional and only refine results.

| Layout family | Character |
| --- | --- |
| **Editorial Classic** | 12-column editorial grid, hanging headers, serif titles, hairline rules, calm rhythm |
| **Cinematic Story** | Dark, immersive, full-bleed widescreen imagery, title cards, strong pacing |
| **Split Narrative** | Asymmetric split screens, coloured text panels beside full-height images |
| **Graphic Posters** | Every section a poster: brand-colour fields, huge fitted type, stickers, marquees |
| **Curated Gallery** | Museum-like walls, uncropped images at their own proportions, asymmetric hangs |
| **Modular Identity** | Bento grid of modules, brand colours as tiles, monospaced labels |

## Install and run (Windows 10/11)

1. Install **Python 3.13** (64-bit) from <https://www.python.org/downloads/windows/>
   (3.12 and 3.14 also work).
2. Double-click **`setup_windows.bat`**. It creates a private environment in
   `.venv` inside this folder, installs the pinned dependencies and the
   Chromium rendering engine (about 150 MB), runs a self-check and offers a
   desktop shortcut. Nothing is installed system-wide.
3. Start the app with **`BehanceStudio.bat`** (or the desktop shortcut).

The launcher always runs this folder's own interpreter
(`.venv\Scripts\pythonw.exe -m behance_studio`), never a global Python.
`BehanceStudio_debug.bat` starts it with a console that shows log messages.

If Chromium cannot be downloaded, Microsoft Edge (part of Windows 10/11) is
used for rendering instead.

### Command line

The same interpreter offers a command-line interface (useful for batch work):

```bat
set PYTHONPATH=%CD%\src
.venv\Scripts\python -m behance_studio doctor
.venv\Scripts\python -m behance_studio demo "%USERPROFILE%\Documents\Behance Studio Projects"
.venv\Scripts\python -m behance_studio create "My Project" --assets "D:\Delivery\My Project"
.venv\Scripts\python -m behance_studio generate "D:\...\My Project"
.venv\Scripts\python -m behance_studio export "D:\...\My Project" --formats pdf,png,zip
```

Run `python -m behance_studio --help` for every command and option.

### Tests

```bat
run_tests.bat
```

On Linux/macOS (development only): `./run.sh setup`, `./run.sh test`, `./run.sh`.

## Documentation

* [User guide](docs/USER_GUIDE.md) — workflow, brief and script formats, editing, exporting
* [AI providers](docs/AI_PROVIDERS.md) — optional OpenAI-compatible, Anthropic and local models; privacy and cost
* [Architecture](docs/ARCHITECTURE.md) — how the pipeline, layout engine and renderer work
* [Development status](DEVELOPMENT_STATUS.md) — what is complete, partial and pending

## Where things are stored

* Projects: `Documents\Behance Studio Projects\<Project>` by default (configurable).
  Each project folder is self-contained: `Assets`, `Versions`, `Exports`,
  `Trash`, `Cache`, `project.json` and `project.db`. Original files are never
  modified; by default they are copied into `Assets`.
* Settings, the recent-projects library and logs: `%APPDATA%\BehanceStudio`.
* API keys (only if you configure AI): Windows Credential Manager. Never in
  settings files, projects or exports.
