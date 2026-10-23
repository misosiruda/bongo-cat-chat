"""Collect package, native and corresponding-source notices for this build."""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import sys

from audit_distribution import ROOT, dependencies

# Explicitly excluded by the audio runtime hook and PyInstaller arguments.
# Keep all other locked package notices: optional imports can cause PyInstaller
# to include helpers from packages that are otherwise used only for development.
EXCLUDED_AUDIO = {"fmod-toolkit", "pyfmodex"}


def collect(output):
    manifest = json.loads((ROOT / 'packaging/licenses/sources.lock.json').read_text())
    from PySide6.QtCore import qVersion
    from PySide6.QtWebEngineCore import qWebEngineVersion, qWebEngineChromiumVersion
    if (qVersion(), qWebEngineVersion(), qWebEngineChromiumVersion()) != (manifest['qt'], manifest['webengine'], manifest['chromium']):
        raise ValueError('Qt/Chromium changed: update corresponding sources and notices')
    for name, expected in manifest['notices'].items():
        if hashlib.sha256((ROOT / 'packaging/licenses' / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Native notice checksum mismatch: ' + name)
    output.mkdir(parents=True, exist_ok=True)
    sections = [
        "Bongo Cat Chat - third-party licence texts\n",
        "Project-owned source is MIT licensed; see LICENSE.txt.\n",
        "This collection includes Python package notices, Qt/PySide upstream source notices, "
        "and the standard GNU licence texts. Chromium notices are in CHROMIUM-LICENSES.html. "
        "SOURCES.md and sources.lock.json identify corresponding archives and replacement instructions. "
        "Package and upstream source notices include a superset of build/test/platform components, not a runtime SBOM.\n",
        "Qt/PySide6 are used through their open-source licensing options, not under a "
        "purchased commercial licence. A packaged commercial-licence reference is not evidence "
        "that this project has purchased one.\n",
    ]
    seen = set()
    for row in dependencies():
        if not row.get("version_matches"):
            raise ValueError(f"Missing or mismatched dependency: {row['name']}")
        if row["name"].lower().replace("_", "-") in EXCLUDED_AUDIO:
            continue
        dist = metadata.distribution(row["name"])
        sections.append(f"\n{'=' * 70}\n{row['name']} {row['installed_version']}\n")
        sections.append(str(row["license_expression"] or row["license_label"] or row["license_classifiers"]))
        sections.extend(row["project_urls"])
        for relative in row["license_files"]:
            path = Path(dist.locate_file(relative))
            if not path.is_file():
                raise ValueError(f"Missing advertised licence file: {relative}")
            content = path.read_text(encoding="utf-8", errors="replace")
            if content not in seen:
                sections.extend([relative, content])
                seen.add(content)
    sections.extend(["\nMono.Cecil 0.11.6", (ROOT / "tools/compatibility/Mono.Cecil.LICENSE.txt").read_text()])
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("CPython licence text missing from the Windows build environment")
    sections.extend([f"\nCPython {sys.version.split()[0]}", python_license.read_text(encoding="utf-8")])
    extra = json.loads((ROOT / 'packaging/licenses/additional-notices.json').read_text())
    for name, source in extra.items():
        if hashlib.sha256((ROOT / 'packaging/licenses' / name).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Additional notice checksum mismatch: ' + name)
    for name in ("GPL-3.0.txt", "LGPL-3.0.txt", "LGPL-2.1.txt", "QT-NOTICES.txt", *extra):
        path = ROOT / "packaging/licenses" / name
        sections.extend([path.name, path.read_text(encoding="utf-8")])
    shutil.copyfile(ROOT / "LICENSE", output / "LICENSE.txt")
    shutil.copyfile(ROOT / "docs/privacy-policy.md", output / "PRIVACY.md")
    shutil.copyfile(ROOT / "docs/privacy-policy.en.md", output / "PRIVACY.en.md")
    shutil.copyfile(ROOT / "docs/licensing/SOURCES.md", output / "SOURCES.md")
    for name in ('sources.lock.json', 'CHROMIUM-LICENSES.html'):
        shutil.copyfile(ROOT / 'packaging/licenses' / name, output / name)
    (output / "THIRD-PARTY-NOTICES.txt").write_text("\n\n".join(sections) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    collect(args.output)
    print(f"Collected package/native notices and corresponding-source information in {args.output}.")
