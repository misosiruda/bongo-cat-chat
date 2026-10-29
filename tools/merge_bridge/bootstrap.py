"""Developer entry point for the app bootstrap."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from bongo_chat.merge_bootstrap import *  # noqa: F403
