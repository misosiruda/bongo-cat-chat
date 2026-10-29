"""Generate identical product/version metadata for project-owned Windows EXEs."""
import argparse
from pathlib import Path
import re


def numeric_version(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?", version)
    if not match:
        raise ValueError("Unsupported application version")
    numbers = tuple(int(n or 0) for n in match.groups())
    if any(n > 65535 for n in numbers):
        raise ValueError("Windows version components must fit in 16 bits")
    return numbers


def write_resources(output, version):
    numbers = numeric_version(version)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("BongoCatChat", "BongoCatChatApp"):
        text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r},
                   mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('ProductName', 'Bongo Cat Chat'),
    StringStruct('ProductVersion', {version!r}),
    StringStruct('FileVersion', {version!r}),
    StringStruct('FileDescription', 'Bongo Cat Chat'),
    StringStruct('OriginalFilename', '{name}.exe')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""
        (output / f"{name}.txt").write_text(text, encoding="utf-8")
    numeric = ".".join(map(str, numbers))
    for name, title in (("FeatureProbe", "compatibility probe"), ("MemoryScan", "read-only memory scanner"),
                        ("MergePrepare", "item merge module preparation")):
        (output / f"{name}.Version.cs").write_text(
            'using System.Reflection;\n'
            '[assembly: AssemblyProduct("Bongo Cat Chat")]\n'
            f'[assembly: AssemblyTitle("Bongo Cat Chat {title}")]\n'
            f'[assembly: AssemblyVersion("{numeric}")]\n'
            f'[assembly: AssemblyFileVersion("{numeric}")]\n'
            f'[assembly: AssemblyInformationalVersion("{version}")]\n', encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_resources(args.output, args.version)
