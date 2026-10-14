"""Discover the running installation, never launch or change the game."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import os
import subprocess
import sys
import time

import psutil

SUPPORT_PATH = Path(__file__).with_name("feature-contract.json")
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


def compatibility_contract():
    try:
        catalog = json.loads(SUPPORT_PATH.read_text(encoding="utf-8"))
        profiles = catalog["profiles"]
        features = {"privacy", "lobby", "chat", "profiles"}
        valid = (catalog["schema"] == 1 and set(catalog["features"]) == features
                 and catalog["assemblies"] == ["Assembly-CSharp.dll", "Heathen.Steamworks.dll"]
                 and isinstance(profiles, list) and 0 < len(profiles) <= 64
                 and set(catalog["native"]) == {BUILD_FILES[1], BUILD_FILES[2]})
        valid = valid and all(isinstance(row, dict) and set(row) == features
                            and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in row.values()) for row in profiles)
        valid = valid and all(isinstance(values, list) and 0 < len(values) <= 16
                            and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in values)
                            for values in catalog["native"].values())
        if not valid:
            raise ValueError
        return catalog
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError("unsupported_feature_contract") from exc


def file_stamps(root):
    """Detect an update during verification or an active connection; no IDs/logs."""
    result = []
    for name in BUILD_FILES:
        stat = (root / name).stat()
        result.append((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(result)


@dataclass(frozen=True)
class Compatibility:
    root: Path
    stamps: tuple
    build: str

    def check(self):
        try:
            if self.stamps == file_stamps(self.root):
                return
        except OSError:
            pass
        raise RuntimeError("game_files_changed")


def probe_features(root, stop=None):
    helper = (Path(__file__).with_name("compatibility") if getattr(sys, "frozen", False)
              else Path(__file__).resolve().parents[2] / "artifacts/compatibility") / "FeatureProbe.exe"
    if not helper.is_file():
        raise RuntimeError("compatibility_tool_missing")
    # Invoke only the shipped metadata reader, with arguments (never shell text).
    # It does not execute the game, load it through reflection, or write to it.
    process = subprocess.Popen([str(helper), str(root / "BongoCat_Data/Managed"), str(SUPPORT_PATH)],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    started = time.monotonic()
    try:
        while True:
            if stop and stop.is_set():
                raise RuntimeError("compatibility_cancelled")
            if time.monotonic() - started > 20:
                raise RuntimeError("compatibility_timeout")
            try:
                output, _ = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0 or len(output) > 4096:
            raise ValueError("feature_probe_failed")
        features = json.loads(output)
        if (not isinstance(features, dict) or set(features) != {"privacy", "lobby", "chat", "profiles"}
                or not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in features.values())):
            raise ValueError("feature_probe_failed")
        return features
    finally:
        if process.poll() is None:
            process.kill()  # Our helper only, never the game/Steam.
        process.communicate()


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


def verify_compatibility(root, stop=None):
    catalog = compatibility_contract()
    observed = {}
    try:
        before = file_stamps(root)
    except OSError:
        before = None
    for relative in catalog["native"]:
        try:
            with (root / relative).open("rb") as stream:
                observed[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError:
            observed[relative] = "unavailable"
    native_ok = all(observed[name] in hashes for name, hashes in catalog["native"].items())
    if native_ok and before is not None:
        try:
            observed["features"] = probe_features(root, stop)
        except (ValueError, OSError, subprocess.SubprocessError):
            observed["features"] = "unavailable"
    if not native_ok or observed.get("features") not in catalog["profiles"]:
        fingerprint = hashlib.sha256(json.dumps(observed, sort_keys=True).encode("ascii")).hexdigest()
        raise UnsupportedGameBuild(installed_build(root), fingerprint)
    result = Compatibility(root, before, installed_build(root))
    result.check()
    return result


def verify_build(root):
    """Legacy diagnostic entry point; a build number never authorizes support."""
    return verify_compatibility(root).build
