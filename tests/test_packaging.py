"""Static checks of the Windows packaging files (the build itself runs in
build_windows.bat / ./run.sh build)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_info_numeric_form():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "version_info.py")], capture_output=True, text=True, check=True).stdout.split()
    from behance_studio import __version__

    assert out[0] == __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", out[1])


def test_spec_and_installer_agree():
    spec = (ROOT / "packaging" / "BehanceStudio.spec").read_text()
    iss = (ROOT / "packaging" / "BehanceStudio.iss").read_text()
    assert 'name="BehanceStudio"' in spec and 'name="BehanceStudio-cli"' in spec
    assert r"..\dist\BehanceStudio\*" in iss and '#define AppExe "BehanceStudio.exe"' in iss
    icon = re.search(r"SetupIconFile=\.\.\\(.+)", iss).group(1).strip().replace("\\", "/")
    assert (ROOT / icon).is_file()
    for rel in ("tools/make_demo_assets.py", "docs/USER_GUIDE.md", "docs/AI_PROVIDERS.md", "src/behance_studio/resources/fonts"):
        assert (ROOT / rel).exists(), rel
    # Uninstall must never touch user data: no [UninstallDelete] outside {app}.
    assert "[UninstallDelete]" not in iss or "{userappdata}" not in iss.split("[UninstallDelete]")[1]


def test_build_script_is_windows_batch():
    data = (ROOT / "build_windows.bat").read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert b"packaging\\BehanceStudio.spec" in data and b"BehanceStudio-cli.exe\" doctor" in data


def test_tools_dir_resolves_in_repository():
    from behance_studio.core.paths import is_frozen, tools_dir

    assert not is_frozen()
    assert (tools_dir() / "make_demo_assets.py").is_file()
