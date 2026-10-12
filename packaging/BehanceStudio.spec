# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build: one folder with two executables.

* ``BehanceStudio.exe``      – the desktop app (no console window)
* ``BehanceStudio-cli.exe``  – the command line (doctor, generate, export…)

Build with ``build_windows.bat`` (Windows) or ``./run.sh build`` (Linux,
development check). Rendering uses Microsoft Edge (present on every
Windows 10/11 machine) through the bundled Playwright driver, so no
Chromium is shipped.
"""

import os
import re
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH is defined by PyInstaller
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

datas = [
    (os.path.join(SRC, "behance_studio", "resources"), os.path.join("behance_studio", "resources")),
    (os.path.join(ROOT, "tools", "make_demo_assets.py"), "tools"),
    (os.path.join(ROOT, "docs", "USER_GUIDE.md"), "docs"),
    (os.path.join(ROOT, "docs", "AI_PROVIDERS.md"), "docs"),
]
binaries = []
hiddenimports = collect_submodules("behance_studio") + [
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.macOS",
    "send2trash",
]
for package in ("playwright", "imageio_ffmpeg"):  # the Playwright driver and the FFmpeg binary are data files
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# Qt modules the app never uses (keeps the folder smaller).
EXCLUDES = [
    "tkinter", "matplotlib", "IPython", "pytest",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtGraphs", "PySide6.QtHelp", "PySide6.QtHttpServer", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
]

ICON = os.path.join(SRC, "behance_studio", "resources", "icons", "app.ico")

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=EXCLUDES,
    noarchive=False,
)
# Qt's hooks collect every QML module because Qt WebEngine imports QtQuick.
# The app uses Qt Widgets + Qt WebEngine Widgets only: drop QML modules,
# unused Qt libraries/plugins and translations other than English/Portuguese.
UNUSED_QT = re.compile(
    r"Qt6(3D|Charts|DataVisualization|Graphs|Labs|Location|Multimedia|Quick3D|QuickControls2|QuickDialogs2|"
    r"QuickEffects|QuickLayouts|QuickParticles|QuickShapes|QuickTest|QuickTimeline|QuickVectorImage|RemoteObjects|"
    r"Scxml|Sensors|SerialPort|ShaderTools|SpatialAudio|Sql|StateMachine|Test|TextToSpeech|VirtualKeyboard|"
    r"WaylandCompositor|WebEngineQuick|WebView|PdfQuick|PositioningQuick|WebChannelQuick|QmlDesignSupport|"
    r"QmlLocalStorage|QmlXmlListModel|MultimediaQuick|SensorsQuick)",
    re.IGNORECASE,
)
UNUSED_PLUGINS = re.compile(
    r"/plugins/(sceneparsers|geometryloaders|renderers|renderplugins|sensors|sqldrivers|texttospeech|virtualkeyboard|"
    r"multimedia|qmltooling|assetimporters|canbus|designer|webview|qmllint|qmlls)/"
)
KEEP_LOCALES = re.compile(r"(^|[/_-])(en|en-us|en-gb|pt|pt-pt|pt-br|pt_pt|pt_br)\.(qm|pak)$", re.IGNORECASE)


def _wanted(entry) -> bool:
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    if "/qml/" in f"/{dest}" or UNUSED_PLUGINS.search(f"/{dest}") or UNUSED_QT.search(name):
        return False
    if "/translations/" in f"/{dest}" or "/qtwebengine_locales/" in f"/{dest}":
        return bool(KEEP_LOCALES.search(name))
    return True


a.binaries = [e for e in a.binaries if _wanted(e)]
a.datas = [e for e in a.datas if _wanted(e)]

pyz = PYZ(a.pure)  # noqa: F821

gui = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BehanceStudio",
    console=False,
    icon=ICON,
    upx=False,
)
cli = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BehanceStudio-cli",
    console=True,
    icon=ICON,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    gui,
    cli,
    a.binaries,
    a.datas,
    upx=False,
    name="BehanceStudio",
)
