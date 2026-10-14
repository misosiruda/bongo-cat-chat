"""Collect available licence texts without claiming a complete native SBOM."""
import argparse
from importlib import metadata
from pathlib import Path
import shutil
import sys

from audit_distribution import ROOT, dependencies

# These are not shipped by the application; PyInstaller's bootloader is shipped.
BUILD_ONLY = {"fmod-toolkit", "pyfmodex", "pytest", "playwright", "greenlet",
              "pyee", "pluggy", "iniconfig", "pygments", "colorama", "altgraph",
              "pefile", "pyinstaller-hooks-contrib", "setuptools", "pywin32-ctypes"}


def collect(output):
    output.mkdir(parents=True, exist_ok=True)
    sections = [
        "Bongo Cat Chat - third-party licence texts\n",
        "Project-owned source is MIT licensed; see LICENSE.txt.\n",
        "This collection preserves available package notices and standard GNU licence texts. "
        "It is not a complete native-component SBOM or a legal clearance. "
        "Qt/Chromium corresponding-source and native attribution review remains required.\n",
        "Qt/PySide6 are used through their open-source licensing options, not under a "
        "purchased commercial licence. A packaged commercial-licence reference is not evidence "
        "that this project has purchased one.\n",
    ]
    seen = set()
    for row in dependencies():
        if not row.get("version_matches"):
            raise ValueError(f"Missing or mismatched dependency: {row['name']}")
        if row["name"].lower().replace("_", "-") in BUILD_ONLY:
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
    for name in ("GPL-3.0.txt", "LGPL-3.0.txt", "LGPL-2.1.txt"):
        path = ROOT / "packaging/licenses" / name
        sections.extend([path.name, path.read_text(encoding="utf-8")])
    shutil.copyfile(ROOT / "LICENSE", output / "LICENSE.txt")
    shutil.copyfile(ROOT / "docs/privacy-policy.md", output / "PRIVACY.md")
    (output / "THIRD-PARTY-NOTICES.txt").write_text("\n\n".join(sections) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    collect(args.output)
    print(f"Collected available licence texts in {args.output}; native review is still required.")
