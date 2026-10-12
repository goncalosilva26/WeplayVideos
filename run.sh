#!/usr/bin/env bash
# Development launcher for Linux/macOS (Behance Studio targets Windows 10/11).
#   ./run.sh setup      create .venv and install dependencies
#   ./run.sh test       run the test suite
#   ./run.sh build      PyInstaller one-folder build into dist/ (development check of the packaging)
#   ./run.sh [args]     start the app (or a CLI command, e.g. ./run.sh doctor)
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"

if [[ "${1:-}" == "setup" ]]; then
    python3 -m venv .venv
    "$PY" -m pip install --upgrade pip -q
    "$PY" -m pip install -r requirements-dev.txt
    "$PY" -m pip install -e . --no-deps -q || true
    "$PY" -m playwright install chromium || echo "Chromium download failed; a system Chrome/Edge will be used."
    exit 0
fi
[[ -x "$PY" ]] || { echo "Run ./run.sh setup first."; exit 1; }
export PYTHONPATH="$PWD/src"
if [[ "${1:-}" == "build" ]]; then
    "$PY" -m pip install -q -r requirements-build.txt 2>/dev/null || uv pip install --python "$PY" -q -r requirements-build.txt
    "$PY" -m PyInstaller packaging/BehanceStudio.spec --noconfirm --clean --distpath dist --workpath build/pyinstaller
    exec dist/BehanceStudio/BehanceStudio-cli doctor
fi
if [[ "${1:-}" == "test" ]]; then
    shift
    exec "$PY" -m pytest "$@"
fi
exec "$PY" -m behance_studio "$@"
