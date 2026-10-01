import sys
from pathlib import Path

# Add project root directory to sys.path so receiving_manager is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from receiving_manager.api import app  # noqa: E402

__all__ = ["app"]
