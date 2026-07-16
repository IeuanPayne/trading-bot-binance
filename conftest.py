from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repository root is importable during pytest collection
# (e.g. for `from trading_bot import ...`) in CI and local runs.
ROOT = Path(__file__).resolve().parent
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)
