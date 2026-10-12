"""Entry script for the packaged build (PyInstaller).

``BehanceStudio.exe`` starts the desktop app; ``BehanceStudio-cli.exe``
(console) runs the command-line interface, e.g. ``BehanceStudio-cli doctor``.
"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from behance_studio.__main__ import main

    sys.exit(main())
