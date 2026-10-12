# Windows distribution

Behance Studio ships as a **portable folder** (`dist\BehanceStudio`) and an
**installer** (`dist\installer\BehanceStudio-Setup-<version>.exe`), built
with PyInstaller (one-folder mode) and Inno Setup 6.

## Build (on Windows 10/11, 64-bit)

1. Install Python 3.12–3.14 (64-bit) and run `setup_windows.bat` once.
2. Optional, for the installer: install [Inno Setup 6](https://jrsoftware.org/isinfo.php).
3. Run `build_windows.bat`. It
   1. installs the pinned packaging tools (`requirements-build.txt`),
   2. builds `dist\BehanceStudio` from `packaging\BehanceStudio.spec`,
   3. runs `BehanceStudio-cli.exe doctor` on the result,
   4. compiles `packaging\BehanceStudio.iss` into the installer if Inno
      Setup is found (otherwise the portable folder is the result).

## What is inside

| File | Purpose |
| --- | --- |
| `BehanceStudio.exe` | the desktop app (no console window) |
| `BehanceStudio-cli.exe` | the command line: `doctor`, `demo`, `create`, `import`, `generate`, `export`, … |
| `_internal\` | Python, Qt (Widgets + WebEngine only — QML, 3D, charts, multimedia and other unused Qt parts are filtered out), fonts, the Playwright driver, FFmpeg, OpenCV |

Rendering of previews, PDFs and images uses **Microsoft Edge** (present on
every Windows 10/11 machine) or Google Chrome, driven headlessly; no
Chromium is bundled. The installer warns if Edge cannot be found.

## Installer behaviour

* Per-user install by default (`%LOCALAPPDATA%\Programs\Behance Studio`), no
  administrator rights; "install for all users" can be chosen in the first
  page. English and Portuguese setup languages.
* Start-menu shortcut, optional desktop shortcut, "launch now" at the end.
* **Uninstalling removes the program folder only.** Projects
  (`Documents\Behance Studio Projects` by default), settings, the AI usage
  record (`%APPDATA%\BehanceStudio`) and API keys (Windows Credential
  Manager) are kept.
* Upgrades install over the previous version (same AppId).

## Size

The Linux development build of the same spec is about 0.9 GB unpacked; the
largest parts are Qt WebEngine (~200 MB), the Playwright driver (~140 MB),
OpenCV (~150 MB) and FFmpeg (~80 MB). The Windows build has not been
measured yet; the installer compresses with LZMA2.

## Verification status

* **Verified (Linux, this repository's CI-like environment):** the spec
  builds; the frozen `BehanceStudio-cli` runs `doctor`, creates the demo
  project, generates the five concepts with rendered previews and exports
  PDF, PNG and HTML; the frozen GUI starts without errors; the Qt WebEngine
  helper process is bundled. `tests/test_packaging.py` checks the packaging
  files.
* **Not verified:** building and running on Windows, the Inno Setup
  compilation, Edge-based rendering from the packaged app, and SmartScreen
  behaviour. The executables are not code-signed, so Windows SmartScreen
  will warn on first run until a signing certificate is used.
