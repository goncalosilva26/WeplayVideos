"""Print the app version and its numeric Windows form, e.g. ``2.0.0.dev1 2.0.0.1``."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from behance_studio import __version__  # noqa: E402

numbers = [int(n) for n in re.findall(r"\d+", __version__)][:4]
print(__version__, ".".join(str(n) for n in numbers + [0] * (4 - len(numbers))))
