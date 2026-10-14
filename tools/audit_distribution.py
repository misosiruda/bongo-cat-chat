"""Reproducible dependency inventory and known distribution-blocker checks.

Metadata is evidence, not a legal conclusion. In particular, native libraries
inside a Python wheel can have a different licence from their Python wrapper.
No network, game access, package installation or private user data is needed.
"""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
# This project uses the LGPL route for Qt. These optional modules are unused.
GPL_QT = re.compile(
    r"qt6(?:graphs|charts|datavisualization|quick3d|quicktimeline|quick3dphysics|"
    r"coap|grpc|httpserver|lottie|mqtt|networkauth|qmlcompiler|virtualkeyboard|"
    r"waylandcompositor|canvaspainter).*\.dll$", re.I)
GAME_FILES = {"steam_api64.dll", "assembly-csharp.dll", "mono-2.0-bdwgc.dll",
              "sharedassets0.assets", "resources.assets", "heathen.steamworks.dll"}


def dependencies(lock=ROOT / "requirements-lock.txt"):
    rows = []
    for line in lock.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, version = line.strip().split("==", 1)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            rows.append({"name": name, "locked_version": version, "installed": False})
            continue
        meta = dist.metadata
        classifiers = [c for c in meta.get_all("Classifier", []) if c.startswith("License ::")]
        rows.append({
            "name": name, "locked_version": version, "installed_version": dist.version,
            "version_matches": version == dist.version,
            "license_expression": meta.get("License-Expression"),
            "license_label": (meta.get("License") or "").splitlines()[0:1],
            "license_classifiers": classifiers,
            "license_files": [str(p).replace("\\", "/") for p in dist.files or []
                              if re.search(r"(?:^|/)(?:licenses?/|[^/]*(?:license|copying|notice)[^/]*$)",
                                           str(p).replace("\\", "/"), re.I)],
            "project_urls": meta.get_all("Project-URL", []),
        })
    return rows


def inspect_bundle(bundle):
    root = Path(bundle).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Bundle must be a directory")
    findings, binaries = [], []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Linked bundle paths are not supported")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        name = path.name.lower()
        if name in GAME_FILES:
            findings.append({"path": relative, "reason": "game_file"})
        if name.startswith(("fmod", "libfmod")) and path.suffix.lower() in {".dll", ".so", ".dylib"}:
            findings.append({"path": relative, "reason": "proprietary_fmod"})
        if GPL_QT.fullmatch(name):
            findings.append({"path": relative, "reason": "unused_qt_gpl_module"})
        if path.suffix.lower() in {".exe", ".dll", ".pyd"}:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            binaries.append({"path": relative, "sha256": digest, "bytes": path.stat().st_size})
    return {"known_blockers": findings, "native_files": binaries,
            "scope": "Known file checks only; not a complete licence compliance verdict"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": 1, "dependencies": dependencies(),
              "manual_review_required": ["project_licence", "native_licences_and_notices",
                                         "corresponding_sources", "game_integration_terms"]}
    if args.bundle:
        report["bundle"] = inspect_bundle(args.bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    blockers = report.get("bundle", {}).get("known_blockers", [])
    mismatches = [row["name"] for row in report["dependencies"] if not row.get("version_matches")]
    print(json.dumps({"report": str(args.output), "known_blockers": len(blockers),
                      "missing_or_mismatched_packages": mismatches}))
    return int(bool(blockers or mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
