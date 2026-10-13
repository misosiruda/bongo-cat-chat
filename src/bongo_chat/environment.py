"""Discover the running installation, never launch or change the game."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import psutil


@dataclass(frozen=True)
class GameProcess:
    pid: int
    created: float
    root: Path

    def alive(self):
        try:
            process = psutil.Process(self.pid)
            return process.create_time() == self.created and Path(process.exe()).resolve() == self.root / "BongoCat.exe"
        except (psutil.Error, OSError):
            return False


def running_game():
    games = []
    for process in psutil.process_iter(["name", "exe", "create_time"]):
        if (process.info["name"] or "").lower() == "bongocat.exe" and process.info["exe"]:
            path = Path(process.info["exe"]).resolve()
            games.append(GameProcess(process.pid, process.info["create_time"], path.parent))
    if len(games) != 1:
        raise RuntimeError("game_missing_or_ambiguous")
    return games[0]


def verify_build(root):
    support = json.loads(Path(__file__).with_name("supported-build.json").read_text(encoding="utf-8"))
    for relative, expected in support["sha256"].items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError("unsupported_game_build")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise RuntimeError("unsupported_game_build")
    return support["build"]
