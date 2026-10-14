"""Windows installation engine tests using tiny, inert bundles and isolated user folders."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")
REPO = Path(__file__).resolve().parents[1]
POWERSHELL = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@pytest.fixture
def installation(tmp_path):
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path / "local")
    env["APPDATA"] = str(tmp_path / "roaming")
    data = Path(env["LOCALAPPDATA"]) / "BongoCatChat"
    data.mkdir(parents=True)
    (data / "history.sqlite3").write_bytes(b"synthetic history sentinel")
    return tmp_path, env, data


def bundle(root: Path, version="0.1.0.dev4"):
    source = root / ("source-" + version)
    app = source / "versions" / version / "BongoCatChatApp"
    app.mkdir(parents=True, exist_ok=True)
    (app / "BongoCatChatApp.exe").write_bytes(b"inert app " + version.encode())
    (source / "versions" / version / ".bongo-version.json").write_text(
        json.dumps({"schema": 1, "version": version}), encoding="utf8")
    (source / "BongoCatChat.exe").write_bytes(b"inert launcher " + version.encode())
    (source / ".bongo-cat-chat-install").write_text(
        json.dumps({"schema": 2, "active": version, "previous": None}), encoding="utf8")
    for name in ("install.ps1", "uninstall.ps1"):
        shutil.copy2(REPO / "packaging" / name, source / name)
    return source


def run(script: Path, destination: Path, env, *, shortcut=False):
    return subprocess.run(
        [str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Destination", str(destination)] + ([] if shortcut else ["-NoShortcut"]),
        env=env, capture_output=True, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def manifest(destination):
    return json.loads((destination / ".bongo-cat-chat-install").read_text(encoding="utf-8-sig"))


def test_install_repair_and_uninstall_preserve_data_and_unrelated_files(installation):
    root, env, data = installation
    source = bundle(root)
    target = root / "한글 설치 폴더"
    for _ in range(2):
        result = run(source / "install.ps1", target, env)
        assert result.returncode == 0, result.stdout
        assert manifest(target)["active"] == "0.1.0.dev4"
        assert not list(target.glob(".bongo-setup-*"))
    (target / "keep.txt").write_text("unrelated")
    # A later update's version and cache belong to this installation too.
    (target / ".updates").mkdir()
    (target / ".updates" / "pending.zip").write_bytes(b"synthetic cache")
    result = run(REPO / "packaging/uninstall.ps1", target, env)
    assert result.returncode == 0, result.stdout
    assert sorted(p.name for p in target.iterdir()) == ["keep.txt"]
    assert (data / "history.sqlite3").read_bytes() == b"synthetic history sentinel"


def test_upgrade_and_downgrade(installation):
    root, env, _ = installation
    old, new = bundle(root, "0.1.0.dev3"), bundle(root)
    target = root / "installed"
    assert run(old / "install.ps1", target, env).returncode == 0
    assert run(new / "install.ps1", target, env).returncode == 0
    assert manifest(target) == {"schema": 2, "active": "0.1.0.dev4", "previous": "0.1.0.dev3"}
    assert run(old / "install.ps1", target, env).returncode == 30
    assert manifest(target)["active"] == "0.1.0.dev4"


def test_shortcut_registration_collision_and_removal(installation):
    root, env, _ = installation
    source = bundle(root)
    target = root / "installed"
    shortcut = Path(env["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk"
    assert run(source / "install.ps1", target, env, shortcut=True).returncode == 0
    original = shortcut.read_bytes()
    assert original
    assert run(source / "install.ps1", root / "second", env, shortcut=True).returncode == 11
    assert not (root / "second").exists()
    assert shortcut.read_bytes() == original
    assert run(REPO / "packaging/uninstall.ps1", target, env, shortcut=True).returncode == 0
    assert not shortcut.exists()


def test_legacy_install_migrates_without_manual_removal(installation):
    root, env, data = installation
    source = bundle(root)
    target = root / "legacy"
    (target / "_internal").mkdir(parents=True)
    (target / "_internal" / "old.dll").write_bytes(b"inert old dependency")
    (target / "BongoCatChat.exe").write_bytes(b"inert old executable")
    (target / ".bongo-cat-chat-install").write_text("BongoCatChat-0.1.0.dev1")
    assert run(source / "install.ps1", target, env).returncode == 0
    assert not (target / "_internal").exists()
    assert manifest(target)["active"] == "0.1.0.dev4"
    assert (data / "history.sqlite3").exists()


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_launcher_lock_prevents_mutation(installation, operation):
    import msvcrt
    root, env, _ = installation
    source = bundle(root)
    target = root / "installed"
    assert run(source / "install.ps1", target, env).returncode == 0
    with (target / ".bongo-cat-chat-run.lock").open("r+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            script = source / "install.ps1" if operation == "install" else REPO / "packaging/uninstall.ps1"
            assert run(script, target, env).returncode == 20
            assert manifest(target)["active"] == "0.1.0.dev4"
            assert (target / "BongoCatChat.exe").exists()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def exclusive_file(path):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def test_late_file_replacement_failure_restores_previous_installation(installation):
    root, env, _ = installation
    old, new = bundle(root, "0.1.0.dev3"), bundle(root)
    target = root / "installed"
    assert run(old / "install.ps1", target, env).returncode == 0
    with exclusive_file(target / "BongoCatChat.exe"):
        result = run(new / "install.ps1", target, env)
        assert result.returncode == 40, result.stdout
    assert manifest(target)["active"] == "0.1.0.dev3"
    assert (target / "BongoCatChat.exe").read_bytes() == b"inert launcher 0.1.0.dev3"
    assert not (target / "versions/0.1.0.dev4").exists()
    assert not list(target.glob(".bongo-setup-*"))


def test_failed_first_install_can_retry_without_manual_cleanup(installation):
    root, env, data = installation
    source = bundle(root)
    target = root / "new"
    with exclusive_file(source / "BongoCatChat.exe"):
        assert run(source / "install.ps1", target, env).returncode == 40
    assert not target.exists()
    assert run(source / "install.ps1", target, env).returncode == 0
    assert manifest(target)["active"] == "0.1.0.dev4"
    assert (data / "history.sqlite3").read_bytes() == b"synthetic history sentinel"


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_selection_changed_before_lock_is_not_overwritten(installation, operation):
    root, env, _ = installation
    source = bundle(root)
    target = root / "installed"
    assert run(source / "install.ps1", target, env).returncode == 0
    # Model a completed concurrent update between preflight and lock acquisition.
    driver = root / "change-before-lock.ps1"
    script = source / "install.ps1" if operation == "install" else REPO / "packaging/uninstall.ps1"
    driver.write_text(
        "param([string]$Destination, [switch]$NoShortcut)\n"
        "function Get-CimInstance {\n"
        "  @{schema=2;active='0.1.0.dev8';previous='0.1.0.dev4'} | ConvertTo-Json | "
        "Set-Content -LiteralPath (Join-Path $Destination '.bongo-cat-chat-install') -Encoding utf8\n"
        "}\n"
        f"& '{str(script).replace(chr(39), chr(39) * 2)}' -Destination $Destination -NoShortcut\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8-sig",
    )
    result = run(driver, target, env)
    assert result.returncode == 40, result.stdout
    assert manifest(target)["active"] == "0.1.0.dev8"
    assert (target / "BongoCatChat.exe").exists()
    assert not list(target.glob(".bongo-setup-*"))


def test_reject_unrelated_folder_incomplete_bundle_and_data_directory(installation):
    root, env, data = installation
    source = bundle(root)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep")
    assert run(source / "install.ps1", unrelated, env).returncode == 10
    assert run(source / "install.ps1", data, env).returncode == 10
    (source / "versions/0.1.0.dev4/BongoCatChatApp/BongoCatChatApp.exe").unlink()
    assert run(source / "install.ps1", root / "new", env).returncode == 10
    assert not (root / "new").exists()
    assert (unrelated / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_reparse_member_rejected_before_any_mutation(installation, operation):
    root, env, _ = installation
    source = bundle(root)
    target = root / "installed"
    assert run(source / "install.ps1", target, env).returncode == 0
    outside = root / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    link = target / ".updates"
    subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        script = source / "install.ps1" if operation == "install" else REPO / "packaging/uninstall.ps1"
        assert run(script, target, env).returncode == 10
        assert (target / "BongoCatChat.exe").exists()
        assert (outside / "keep.txt").read_text() == "keep"
    finally:
        link.rmdir()  # remove this junction itself, without traversing its target
