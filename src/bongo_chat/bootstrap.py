"""Small frozen launcher: switch verified version slots between app sessions."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

import psutil

from .exit_codes import PROFILE_IN_USE, RESTART_FOR_UPDATE, RESTART_CAPABILITY, UPDATE_DIAGNOSTIC_FAILED
from .updates import (ARCHIVE, MARKER, UpdateError, atomic_bytes, atomic_json, child,
                      config, extract_archive, installation, load_json, no_links,
                      remove_owned, staged_manifest, version)

APP = 'BongoCatChatApp/BongoCatChatApp.exe'
VERSION_MARKER = '.bongo-version.json'


@contextmanager
def install_lock(root):
    import msvcrt
    path = child(root, '.bongo-cat-chat-run.lock')
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise UpdateError('already_running') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def probe_slot(slot, cache, expected_version):
    """Probe a separate empty database; never migrate or open the user's history."""
    report = child(cache, 'probe-' + uuid4().hex + '.json')
    data = child(cache, 'probe-data-' + uuid4().hex)
    command = [str(child(slot, APP)), '--offline', '--data-dir', str(data), '--smoke-report', str(report)]
    process = subprocess.Popen(command, cwd=slot, **process_options())
    try:
        try:
            code = process.wait(timeout=45)
        except subprocess.TimeoutExpired as exc:
            # Only descendants of this updater-owned offline probe are stopped.
            children = psutil.Process(process.pid).children(recursive=True)
            for descendant in reversed(children):
                try:
                    descendant.kill()
                except psutil.NoSuchProcess:
                    pass
            process.kill()
            process.wait(timeout=10)
            raise UpdateError('probe_timeout') from exc
        if code != 0 or not report.exists():
            raise UpdateError('probe_failed')
        result = load_json(report.read_bytes())
        if (result.get('renderer') is not True or result.get('console_errors')
                or result.get('version') != expected_version or result.get('offline') is not True):
            raise UpdateError('probe_failed')
    finally:
        report.unlink(missing_ok=True)
        if data.exists():
            remove_owned(cache, data)


def apply_pending(root, settings, probe=probe_slot):
    """Caller holds the installation lock. The active pointer changes last."""
    root = no_links(root)
    marker = installation(root)
    cache = child(root, '.updates')
    manifest = staged_manifest(root, settings)
    target_version = manifest['version']
    if version(target_version) <= version(marker['active']):
        raise UpdateError('not_newer')
    failed = child(cache, 'attempted.json')
    if failed.exists() and load_json(failed.read_bytes()).get('sha256') == manifest['sha256']:
        raise UpdateError('previous_apply_failed')
    # Write the attempt before any mutation. A power loss or full disk must not
    # cause the same candidate to be installed over and over on every startup.
    atomic_json(failed, {'sha256': manifest['sha256'], 'version': target_version})
    stage = child(cache, 'extract-' + uuid4().hex)
    slot = child(root, 'versions', target_version)
    try:
        if slot.exists():
            # Never overwrite an active/previous/foreign version directory.
            existing = load_json(child(slot, VERSION_MARKER).read_bytes())
            if target_version == marker.get('previous') or existing.get('sha256') != manifest['sha256']:
                raise UpdateError('version_slot_exists')
            remove_owned(child(root, 'versions'), slot)
        extract_archive(child(cache, 'pending', ARCHIVE), stage)
        probe(stage, cache, target_version)
        atomic_json(stage / VERSION_MARKER, {'schema': 1, 'version': target_version, 'sha256': manifest['sha256']})
        slot.parent.mkdir(exist_ok=True)
        os.replace(stage, slot)
        # The helper is a copy outside this path. Replacing the launcher is one
        # atomic file operation; old and new launchers support bootstrap schema 1.
        atomic_bytes(child(root, 'BongoCatChat.exe'), child(slot, 'BongoCatChat.exe').read_bytes())
        atomic_bytes(child(root, 'uninstall.ps1'), child(slot, 'uninstall.ps1').read_bytes())
        atomic_json(child(cache, 'result.json'), {'state': 'applied', 'version': target_version})
        atomic_json(child(root, MARKER), {'schema': 2, 'active': target_version, 'previous': marker['active']})
        return target_version
    finally:
        if stage.exists():
            remove_owned(cache, stage)


def clean_old_slots(root):
    """Keep active + previous; skip unknown files instead of deleting them."""
    marker = installation(root)
    versions = child(root, 'versions')
    for slot in versions.iterdir():
        if slot.name in {marker['active'], marker.get('previous')}:
            continue
        try:
            version(slot.name)
            names = {entry.name for entry in slot.iterdir()}
            allowed = {'BongoCatChat.exe', 'BongoCatChatApp', 'uninstall.ps1', VERSION_MARKER}
            recorded = load_json(child(slot, VERSION_MARKER).read_bytes())
            if names <= allowed and recorded.get('schema') == 1 and recorded.get('version') == slot.name:
                remove_owned(versions, slot)
        except (OSError, ValueError):
            continue


def clean_cache(root):
    cache = child(root, '.updates')
    if not cache.exists():
        return
    for path in cache.iterdir():
        if re.fullmatch(r'(?:download|extract|probe-data)-[a-f0-9]{32}|probe-[a-f0-9]{32}\.json|bootstrap-[a-f0-9]{32}\.exe', path.name):
            if path != no_links(sys.executable):
                try:
                    remove_owned(cache, path)
                except OSError:
                    pass  # A bootloader may still be finishing its own cleanup.


def run_app(root, data, offline=False, read_only=False, smoke_report=None, connection_report=None, update_smoke_dir=None, restart_supported=True):
    marker = installation(root)
    command = [str(child(root, 'versions', marker['active'], APP)), '--install-root', str(root), '--data-dir', str(data)]
    if offline:
        command.append('--offline')
    if read_only:
        command.append('--read-only')
    if smoke_report:
        command.extend(['--smoke-report', str(smoke_report)])
    if connection_report:
        command.extend(['--connection-report', str(connection_report)])
    if update_smoke_dir:
        command.extend(['--update-smoke-dir', str(update_smoke_dir)])
    started = time.monotonic()
    try:
        # An environment capability is ignored by old apps, including rollback
        # slots. A new CLI argument would make their argument parser fail.
        code = subprocess.call(command, cwd=root,
                               env={**os.environ, RESTART_CAPABILITY: '1' if restart_supported else '0'}, **process_options())
    except OSError:
        if not marker.get('previous'):
            raise
        # The candidate may disappear or become inaccessible after its probe,
        # for example when an antivirus quarantines the executable.
        code = 1
    if code not in (0, PROFILE_IN_USE, RESTART_FOR_UPDATE, UPDATE_DIAGNOSTIC_FAILED) and time.monotonic() - started < 45 and marker.get('previous'):
        slot = child(root, 'versions', marker['active'])
        recorded = load_json(child(slot, VERSION_MARKER).read_bytes())
        atomic_json(child(root, '.updates', 'attempted.json'), {'sha256': recorded.get('sha256'), 'version': marker['active']})
        atomic_json(child(root, MARKER), {'schema': 2, 'active': marker['previous'], 'previous': None})
        atomic_json(child(root, '.updates', 'result.json'), {'state': 'rolled_back', 'version': marker['previous']})
    if code == 0:
        try:
            if staged_manifest(root, config())['version'] == installation(root)['active']:
                remove_owned(child(root, '.updates'), child(root, '.updates', 'pending'))
        except (OSError, ValueError):
            pass
    return code


def handoff(root, data, args):
    """Run the already installed launcher copy after this process releases it."""
    helper = child(root, '.updates', 'bootstrap-' + uuid4().hex + '.exe')
    shutil.copyfile(no_links(sys.executable), helper)
    owner = psutil.Process()
    parent = owner.parent()
    # PyInstaller onefile keeps an outer bootloader alive after Python exits.
    # Wait for that process too before atomically replacing its executable.
    if parent and no_links(parent.exe()) == no_links(sys.executable):
        owner = parent
    command = [str(helper), '--apply-root', str(root), '--parent', str(owner.pid),
               '--parent-created', str(owner.create_time()), '--data-dir', str(data)]
    if args.offline:
        command.append('--offline')
    if args.read_only:
        command.append('--read-only')
    if args.smoke_report:
        command.extend(['--smoke-report', str(args.smoke_report)])
    if args.connection_report:
        command.extend(['--connection-report', str(args.connection_report)])
    if args.update_smoke_dir:
        command.extend(['--update-smoke-dir', str(args.update_smoke_dir)])
    subprocess.Popen(command, cwd=helper.parent, **process_options())


def main():
    parser = argparse.ArgumentParser(description='Bongo Cat Chat launcher')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '.')) / 'BongoCatChat')
    parser.add_argument('--smoke-report', type=Path)
    parser.add_argument('--connection-report', type=Path)
    parser.add_argument('--update-smoke-dir', type=Path)
    parser.add_argument('--apply-root', type=Path)
    parser.add_argument('--parent', type=int)
    parser.add_argument('--parent-created', type=float)
    args = parser.parse_args()
    if args.smoke_report and not args.offline:
        parser.error('--smoke-report requires --offline')
    if args.connection_report and (not args.read_only or args.offline or args.smoke_report):
        parser.error('--connection-report requires --read-only')
    if args.update_smoke_dir and (not args.offline or args.smoke_report or args.connection_report
            or not any(value == '--data-dir' or value.startswith('--data-dir=') for value in sys.argv[1:])):
        parser.error('--update-smoke-dir requires --offline and explicit --data-dir')
    root = no_links(args.apply_root or Path(sys.executable).parent)
    data = no_links(args.data_dir)
    try:
        if data.is_relative_to(root):
            raise UpdateError('data_inside_installation')
        installation(root)
        if args.apply_root:
            if not Path(sys.executable).resolve().is_relative_to(child(root, '.updates')) or not args.parent or not args.parent_created:
                raise UpdateError('invalid_handoff')
            try:
                parent = psutil.Process(args.parent)
                if parent.create_time() == args.parent_created:
                    parent.wait(timeout=30)
            except psutil.NoSuchProcess:
                pass
        with install_lock(root):
            clean_cache(root)
            settings = config()
            pending = child(root, '.updates', 'pending')
            if pending.exists():
                try:
                    manifest = staged_manifest(root, settings)
                    failed = child(root, '.updates', 'attempted.json')
                    blocked = failed.exists() and load_json(failed.read_bytes()).get('sha256') == manifest['sha256']
                    if version(manifest['version']) > version(installation(root)['active']) and not blocked:
                        if not args.apply_root:
                            handoff(root, data, args)
                            return 0
                        apply_pending(root, settings)
                except (OSError, ValueError, zipfile.BadZipFile):
                    try:
                        atomic_json(child(root, '.updates', 'result.json'), {'state': 'apply_failed'})
                    except OSError:
                        pass  # A full update disk must not prevent the old app starting.
            clean_old_slots(root)
            code = run_app(root, data, args.offline, args.read_only, args.smoke_report, args.connection_report, args.update_smoke_dir)
            if code == RESTART_FOR_UPDATE:
                # The app has closed its worker, database and profile lock.
                # Reuse the existing handoff so even a running onefile helper
                # releases its executable and install lock before replacement.
                try:
                    handoff(root, data, args)
                except (OSError, ValueError, psutil.Error):
                    # The current app has already closed. Restore its window
                    # without another automatic attempt in this session if a
                    # full disk or antivirus prevented the helper starting.
                    return run_app(root, data, args.offline, args.read_only, args.smoke_report,
                                   args.connection_report, args.update_smoke_dir, restart_supported=False)
                return 0
            return code
    except (OSError, ValueError, psutil.Error) as exc:
        if args.smoke_report:
            atomic_json(args.smoke_report, {'bootstrap_error': type(exc).__name__})
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, '앱이 이미 실행 중이거나 설치를 확인할 수 없습니다. 기존 대화 기록은 보존됩니다.', 'Bongo Cat Chat', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
