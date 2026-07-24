"""Ensure src/ is importable regardless of editable-install .pth quirks."""

import sys
from pathlib import Path

SRC = str(Path(__file__).parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
