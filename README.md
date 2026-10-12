# Behance Studio

A Windows 10/11 desktop application that turns a folder of raw design material
into complete, portfolio-ready presentations for Behance.

Create a project, drop in a folder or a ZIP of your logos, mockups,
photographs, posters, social media pieces and videos, and press **Generate
Projects**. No brief, script, categorising or layout choices are required:
Behance Studio analyses the material, selects the strongest assets, and a
Creative Director plans **five complete, differently art-directed case
studies**. Compare them side by side, choose one, refine it if you like, and
export to PDF, images, an HTML package or a ZIP — or **export to Canva** as an
editable design (every text box, picture and shape separate). A creative brief
(`brief.txt`) and a detailed script (`GUIAO_PROJETO.txt`) remain optional
advanced inputs.

If the material is already organised in section folders (`01 Logo`,
`03 Packaging/Cups`, `04 Campaign/Posters`…), every concept keeps each image
in the section its folder names, in your order; analysis (offline or AI)
only decides how an image is shown. *Section report* explains where every
image went and why.

| Concept | Art direction |
| --- | --- |
| **Minimal Editorial** | Light surfaces, large images framed by negative space, refined serif type, small tracked labels |
| **Bold Graphic** | Full brand-colour fields, poster-scale type, seamless modules, artwork staged with hard shadows |
| **Premium Photographic** | Dark surfaces, edge-to-edge imagery, seamless pairs, framed campaign pieces under soft light |
| **Layered Experimental** | Overlapping cards, arch/circle masks, rotated artwork with depth, pattern grounds |
| **Immersive Story** | Numbered chapter spreads, cinematic frames and filmstrips, brand messages as pauses |

The six layout families of version 1 remain available as *Classic layouts*.
**Free local AI (recommended):** with [Ollama](https://ollama.com) and a vision model such as Qwen3-VL 8B on your own GPU, imported images are recognised by design purpose, kept in the right sections, and the five concepts are planned with AI — no account, no cost, nothing leaves your PC. See [docs/LOCAL_AI.md](docs/LOCAL_AI.md). Everything also works offline (the offline Creative Director is rules-based, not AI). With an optional AI provider, an AI Creative Director plans each concept's storyboard (validated before use) and an optional AI critique reviews the rendered sections; you see the cost estimate before every paid generation and can set spending limits.
See [docs/samples/](docs/samples/) for renders and
[docs/ARCHITECTURE_2.0.md](docs/ARCHITECTURE_2.0.md) for the design of 2.0.

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
* [Windows distribution](docs/WINDOWS_INSTALLER.md) — `build_windows.bat`: portable folder + Inno Setup installer
* [Free local AI with Ollama](docs/LOCAL_AI.md) — model choice for an RTX 3060 12 GB, Windows setup, `LocalAI_Check.bat`
* [Export to Canva](docs/CANVA.md) — how proposals become editable Canva designs, connecting a Canva account, verified fidelity and limitations
* [AI providers](docs/AI_PROVIDERS.md) — optional OpenAI-compatible, Anthropic and local models; AI director and critique; privacy, costs and limits
* [Architecture](docs/ARCHITECTURE.md) — how the pipeline, layout engine and renderer work
* [Development status](DEVELOPMENT_STATUS.md) — what is complete, partial and pending

## Where things are stored

* Projects: `Documents\Behance Studio Projects\<Project>` by default (configurable).
  Each project folder is self-contained: `Assets`, `Versions`, `Exports`,
  `Trash`, `Cache`, `Diagnostics` (section reports), `project.json` and
  `project.db`. Original files are never
  modified; by default they are copied into `Assets`.
* Settings, the recent-projects library and logs: `%APPDATA%\BehanceStudio`.
* API keys (only if you configure AI): Windows Credential Manager. Never in
  settings files, projects or exports.
