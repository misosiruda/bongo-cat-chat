"""Discover the running installation, never launch or change the game."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import psutil

SUPPORT_PATH = Path(__file__).with_name("supported-build.json")
BUILD_FILES = (
    "BongoCat_Data/Managed/Assembly-CSharp.dll",
    "BongoCat_Data/Plugins/x86_64/steam_api64.dll",
    "MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll",
    "BongoCat_Data/Managed/Heathen.Steamworks.dll",
)


class UnsupportedGameBuild(RuntimeError):
    def __init__(self, build, fingerprint):
        super().__init__("unsupported_game_build")
        self.build, self.fingerprint = build, fingerprint


def installed_build(root):
    """Public build number for diagnostics only; never an authorization source."""
    try:
        with (root.parent.parent / "appmanifest_3419430.acf").open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            return ""
        text = raw.decode("utf-8-sig")
        app = re.findall(r'"appid"\s+"([0-9]+)"', text)
        build = re.findall(r'"buildid"\s+"([0-9]{1,12})"', text)
        return build[0] if app == ["3419430"] and len(build) == 1 else ""
    except (OSError, UnicodeError):
        return ""


def supported_builds():
    try:
        catalog = json.loads(SUPPORT_PATH.read_text(encoding="utf-8"))
        builds = catalog["builds"]
        valid = catalog["schema"] == 1 and isinstance(builds, list) and 0 < len(builds) <= 64
        valid = valid and all(
            isinstance(row, dict) and re.fullmatch(r"[0-9]{1,12}", row["build"])
            and set(row["sha256"]) == set(BUILD_FILES)
            and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in row["sha256"].values())
            for row in builds)
        if not valid:
            raise ValueError
        return builds
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError("unsupported_build_catalog") from exc


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
    builds = supported_builds()
    observed = {}
    for relative in BUILD_FILES:
        try:
            with (root / relative).open("rb") as stream:
                observed[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError:
            observed[relative] = "unavailable"
    # A complete tuple must match one validated environment. Never mix hashes
    # from different builds, or trust the editable Steam build number alone.
    matches = [row for row in builds if row["sha256"] == observed]
    if len(matches) != 1:
        fingerprint = hashlib.sha256(json.dumps(observed, sort_keys=True).encode("ascii")).hexdigest()
        raise UnsupportedGameBuild(installed_build(root), fingerprint)
    return matches[0]["build"]
