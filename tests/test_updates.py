import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import threading
import urllib.error
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bongo_chat import bootstrap
from bongo_chat.exit_codes import PROFILE_IN_USE, RESTART_FOR_UPDATE, RESTART_CAPABILITY, UPDATE_DIAGNOSTIC_FAILED
from bongo_chat.updates import (ARCHIVE, MANIFEST, SIGNATURE, MARKER, GitHubRedirect,
    UpdateError, UpdateManager, atomic_json, check_and_stage, extract_archive,
    installation, staged_manifest, trusted_url, verify_manifest, version)


@pytest.fixture
def signing():
    key = Ed25519PrivateKey.generate()
    settings = {'repository': 'fixture-owner/fixture-releases',
                'public_key': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
    return key, settings


def package(signing, release_version='0.2.0', entries=None):
    key, settings = signing
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, body in (entries or {
            'BongoCatChat.exe': b'new launcher',
            'BongoCatChatApp/BongoCatChatApp.exe': b'new app',
            'BongoCatChatApp/_internal/runtime.bin': b'dependency',
            'uninstall.ps1': b'# fixture uninstall',
        }).items():
            archive.writestr(name, body)
    zipped = data.getvalue()
    manifest = {'schema': 1, 'repository': settings['repository'], 'version': release_version,
                'platform': 'windows-x64', 'archive': ARCHIVE, 'size': len(zipped),
                'sha256': hashlib.sha256(zipped).hexdigest(), 'data_schema': 1, 'bootstrap_schema': 1}
    raw = json.dumps(manifest).encode()
    return {ARCHIVE: zipped, MANIFEST: raw, SIGNATURE: key.sign(raw)}


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / '앱 설치'
    root.mkdir()
    atomic_json(root / MARKER, {'schema': 2, 'active': '0.1.0', 'previous': None})
    (root / 'BongoCatChat.exe').write_bytes(b'old launcher')
    slot = root / 'versions' / '0.1.0'
    app = slot / 'BongoCatChatApp'
    app.mkdir(parents=True)
    (app / 'BongoCatChatApp.exe').write_bytes(b'old app')
    atomic_json(slot / bootstrap.VERSION_MARKER, {'schema': 1, 'version': '0.1.0'})
    (root / 'unrelated.txt').write_text('preserve')
    (tmp_path / 'history.sqlite3').write_bytes(b'fixture history never opened')
    return root


def pending(root, assets):
    folder = root / '.updates' / 'pending'
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in assets.items():
        (folder / name).write_bytes(body)


class FixtureTransport:
    def __init__(self, assets, release_version='0.2.0', error=None):
        self.assets, self.error, self.calls = assets, error, []
        self.release = {'tag_name': 'v' + release_version, 'draft': False, 'prerelease': False,
                        'assets': [{'name': n, 'state': 'uploaded', 'browser_download_url': 'https://untrusted.invalid/ignored'} for n in assets]}

    def download(self, url, target, limit):
        self.calls.append(url)
        if self.error:
            raise self.error
        data = json.dumps(self.release).encode() if url.endswith('/latest') else self.assets[url.rsplit('/', 1)[-1]]
        if len(data) > limit:
            raise UpdateError('download_too_large')
        Path(target).write_bytes(data)
        return len(data)


def test_version_order_is_numeric_and_stable_beats_dev():
    assert version('1.0.0.dev2') < version('1.0.0.dev10') < version('1.0.0') < version('1.10.0')
    for invalid in ('', '../1.0.0', 'v1.0.0', '01.0.0', '1.2', '1.0.0+foo'):
        with pytest.raises(ValueError):
            version(invalid)


@pytest.mark.parametrize('change', ['signature', 'bytes', 'repository', 'platform', 'data_schema', 'bootstrap_schema', 'size'])
def test_manifest_rejects_tampering_and_incompatible_payload(signing, change):
    assets = package(signing)
    raw, signature = assets[MANIFEST], assets[SIGNATURE]
    if change == 'signature':
        signature = b'0' * 64
    elif change == 'bytes':
        raw += b' '
    else:
        manifest = json.loads(raw)
        manifest[change] = {'repository':'another/repo', 'platform':'linux-x64', 'data_schema':2, 'bootstrap_schema':2, 'size':True}[change]
        raw = json.dumps(manifest).encode()
        signature = signing[0].sign(raw)
    with pytest.raises(ValueError):
        verify_manifest(raw, signature, signing[1])


def test_signed_duplicate_key_is_rejected(signing):
    raw = package(signing)[MANIFEST][:-1] + b',"schema":1}'
    with pytest.raises(UpdateError, match='duplicate_key'):
        verify_manifest(raw, signing[0].sign(raw), signing[1])


def test_github_check_stages_verified_bytes_without_touching_active_or_history(installed, signing):
    assets = package(signing)
    transport = FixtureTransport(assets)
    states = []
    check_and_stage(installed, '0.1.0', signing[1], transport, lambda *x: states.append(x))
    assert states == [('downloading', '0.2.0'), ('ready', '0.2.0')]
    assert staged_manifest(installed, signing[1])['version'] == '0.2.0'
    assert installation(installed)['active'] == '0.1.0'
    assert (installed.parent / 'history.sqlite3').read_bytes() == b'fixture history never opened'
    assert all(url.startswith(('https://api.github.com/repos/fixture-owner/fixture-releases/',
                              'https://github.com/fixture-owner/fixture-releases/releases/download/v0.2.0/')) for url in transport.calls)
    again = FixtureTransport(assets)
    check_and_stage(installed, '0.1.0', signing[1], again, lambda *x: None)
    assert not any(url.endswith('.zip') for url in again.calls)


@pytest.mark.parametrize('kind', ['checksum', 'size', 'missing_asset', 'prerelease', 'draft', 'tag_mismatch'])
def test_invalid_release_never_publishes_pending(installed, signing, kind):
    assets = package(signing)
    if kind == 'checksum':
        assets[ARCHIVE] = bytes([assets[ARCHIVE][0] ^ 1]) + assets[ARCHIVE][1:]
    if kind == 'size':
        assets[ARCHIVE] += b'bad'
    transport = FixtureTransport(assets)
    if kind == 'missing_asset':
        transport.release['assets'].pop()
    if kind in ('prerelease', 'draft'):
        transport.release[kind] = True
    if kind == 'tag_mismatch':
        transport.release['tag_name'] = 'v0.3.0'
    with pytest.raises(ValueError):
        check_and_stage(installed, '0.1.0', signing[1], transport, lambda *x: None)
    assert not (installed / '.updates' / 'pending').exists()
    assert not list((installed / '.updates').glob('download-*'))


def test_offline_private_and_interrupted_download_keep_installed_app(installed, signing):
    transport = FixtureTransport(package(signing), error=urllib.error.HTTPError('https://api.github.com/', 404, 'private or missing', {}, None))
    manager = UpdateManager(installed, '0.1.0', settings=signing[1], transport=transport)
    manager.request()
    manager.thread.join(5)
    assert manager.snapshot()['state'] == 'unavailable'
    transport.error = OSError('fixture disconnected')
    manager.request()
    manager.thread.join(5)
    assert manager.snapshot()['state'] == 'network_error'
    assert installation(installed)['active'] == '0.1.0'
    assert not (installed / '.updates' / 'pending').exists()
    offline = UpdateManager(installed, '0.1.0', offline=True, settings=signing[1], transport=transport)
    calls = len(transport.calls)
    offline.request()
    assert offline.thread is None and len(transport.calls) == calls


@pytest.mark.parametrize('url', ['http://github.com/x', 'https://github.com.evil.invalid/x',
    'https://user:token@github.com/x', 'https://github.com:444/x', 'file:///C:/x', 'https://github.com/x#fragment'])
def test_untrusted_downloads_and_redirects_are_rejected(url):
    with pytest.raises(ValueError):
        trusted_url(url)
    with pytest.raises(ValueError):
        GitHubRedirect().redirect_request(None, None, 302, '', {}, url)


@pytest.mark.parametrize('name', ['../outside.exe', '/outside.exe', 'C:/outside.exe',
    'BongoCatChatApp/../outside.exe', 'BongoCatChatApp\\escape.exe', 'BongoCatChatApp/file:stream',
    'BongoCatChatApp/CON.txt', 'BongoCatChatApp/trailing.', 'unrelated.txt'])
def test_zip_paths_cannot_escape_or_replace_unowned_files(tmp_path, name):
    path = tmp_path / 'bad.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name, b'bad')
    with pytest.raises(ValueError):
        extract_archive(path, tmp_path / 'stage')
    assert not (tmp_path / 'stage').exists()


def test_zip_symlink_and_case_collisions_rejected(tmp_path):
    path = tmp_path / 'bad.zip'
    info = zipfile.ZipInfo('BongoCatChatApp/link')
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(info, '../../outside')
    with pytest.raises(ValueError):
        extract_archive(path, tmp_path / 'stage')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('BongoCatChatApp/File', b'one')
        archive.writestr('BongoCatChatApp/file', b'two')
    with pytest.raises(ValueError):
        extract_archive(path, tmp_path / 'stage')


def test_apply_switches_only_after_probe_and_keeps_previous(installed, signing):
    pending(installed, package(signing))
    observed = []
    def probe(slot, cache, expected):
        observed.append((installation(installed)['active'], expected))
        assert (slot / bootstrap.APP).read_bytes() == b'new app'
    with bootstrap.install_lock(installed):
        result = bootstrap.apply_pending(installed, signing[1], probe)
    assert observed == [('0.1.0', '0.2.0')] and result == '0.2.0'
    assert installation(installed) == {'schema':2, 'active':'0.2.0', 'previous':'0.1.0'}
    assert (installed / 'versions/0.1.0' / bootstrap.APP).read_bytes() == b'old app'
    assert (installed / 'unrelated.txt').read_text() == 'preserve'
    assert (installed.parent / 'history.sqlite3').read_bytes() == b'fixture history never opened'


def test_failed_probe_keeps_old_app_and_blocks_repeated_install(installed, signing):
    pending(installed, package(signing))
    def fail(*args):
        raise UpdateError('probe_failed')
    with pytest.raises(UpdateError, match='probe_failed'):
        bootstrap.apply_pending(installed, signing[1], fail)
    assert installation(installed)['active'] == '0.1.0'
    assert (installed / 'BongoCatChat.exe').read_bytes() == b'old launcher'
    with pytest.raises(UpdateError, match='previous_apply_failed'):
        bootstrap.apply_pending(installed, signing[1], lambda *x: None)


def test_pointer_write_failure_keeps_old_version_selected(installed, signing, monkeypatch):
    pending(installed, package(signing))
    original = bootstrap.atomic_json
    def fail_pointer(path, value):
        if path.name == MARKER:
            raise OSError('fixture disk full')
        original(path, value)
    monkeypatch.setattr(bootstrap, 'atomic_json', fail_pointer)
    with pytest.raises(OSError):
        bootstrap.apply_pending(installed, signing[1], lambda *x: None)
    assert installation(installed)['active'] == '0.1.0'
    assert (installed / 'versions/0.1.0' / bootstrap.APP).exists()
    manager = UpdateManager(installed, '0.1.0', settings=signing[1])
    assert manager.snapshot()['state'] == 'apply_failed'
    with pytest.raises(UpdateError, match='previous_apply_failed'):
        bootstrap.apply_pending(installed, signing[1], lambda *x: None)


def test_early_new_app_failure_rolls_selection_back(installed, signing, monkeypatch):
    pending(installed, package(signing))
    bootstrap.apply_pending(installed, signing[1], lambda *x: None)
    monkeypatch.setattr(bootstrap.subprocess, 'call', lambda *a, **k: 2)
    assert bootstrap.run_app(installed, installed.parent / 'data', offline=True) == 2
    assert installation(installed)['active'] == '0.1.0'
    assert json.loads((installed / '.updates/result.json').read_text())['state'] == 'rolled_back'


def test_busy_data_profile_keeps_new_version_and_can_launch_again(installed, signing, monkeypatch):
    pending(installed, package(signing))
    bootstrap.apply_pending(installed, signing[1], lambda *x: None)
    paths = [installed / MARKER, installed / '.updates/attempted.json', installed / '.updates/result.json']
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    results = iter([PROFILE_IN_USE, 0])
    launches = []
    def launch(command, **kwargs):
        launches.append(command[0])
        return next(results)
    monkeypatch.setattr(bootstrap.subprocess, 'call', launch)
    assert bootstrap.run_app(installed, installed.parent / 'data', offline=True) == PROFILE_IN_USE
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths] == before
    assert bootstrap.run_app(installed, installed.parent / 'data', offline=True) == 0
    assert launches == [str(installed / 'versions/0.2.0' / bootstrap.APP)] * 2
    assert installation(installed) == {'schema': 2, 'active': '0.2.0', 'previous': '0.1.0'}
    assert (installed.parent / 'history.sqlite3').read_bytes() == b'fixture history never opened'


@pytest.mark.parametrize('error', [FileNotFoundError, PermissionError])
def test_new_app_launch_error_restores_previous_selection(installed, signing, monkeypatch, error):
    assets = package(signing)
    pending(installed, assets)
    bootstrap.apply_pending(installed, signing[1], lambda *x: None)
    def cannot_start(*args, **kwargs):
        raise error('candidate unavailable after probe')
    monkeypatch.setattr(bootstrap.subprocess, 'call', cannot_start)
    assert bootstrap.run_app(installed, installed.parent / 'data', offline=True) == 1
    assert installation(installed)['active'] == '0.1.0'
    assert json.loads((installed / '.updates/result.json').read_bytes())['state'] == 'rolled_back'
    assert (installed.parent / 'history.sqlite3').read_bytes() == b'fixture history never opened'
    with pytest.raises(UpdateError, match='previous_apply_failed'):
        check_and_stage(installed, '0.1.0', signing[1], FixtureTransport(assets), lambda *x: None)


def test_another_launcher_cannot_apply_while_app_session_is_locked(installed):
    with bootstrap.install_lock(installed):
        with pytest.raises(UpdateError, match='already_running'):
            with bootstrap.install_lock(installed):
                pytest.fail('second launcher acquired the running installation')


def test_cleanup_preserves_active_previous_and_unknown_files(installed, signing):
    pending(installed, package(signing))
    bootstrap.apply_pending(installed, signing[1], lambda *x: None)
    unknown = installed / 'versions/0.0.1'
    unknown.mkdir()
    (unknown / 'keep.txt').write_text('unowned')
    atomic_json(unknown / bootstrap.VERSION_MARKER, {'schema':1,'version':'0.0.1'})
    bootstrap.clean_old_slots(installed)
    assert (unknown / 'keep.txt').exists()
    assert (installed / 'versions/0.1.0').exists() and (installed / 'versions/0.2.0').exists()


@pytest.mark.parametrize('exit_code', [RESTART_FOR_UPDATE, UPDATE_DIAGNOSTIC_FAILED])
def test_restart_exit_keeps_current_version_and_staged_package(installed, signing, monkeypatch, exit_code):
    pending(installed, package(signing))
    bootstrap.apply_pending(installed, signing[1], lambda *args: None)
    paths = [installed / MARKER, installed / '.updates/attempted.json', installed / '.updates/result.json']
    before = [path.read_bytes() for path in paths]
    def launch(command, **kwargs):
        assert kwargs['env'][RESTART_CAPABILITY] == '1'
        assert '--read-only' in command
        return exit_code
    monkeypatch.setattr(bootstrap.subprocess, 'call', launch)
    assert bootstrap.run_app(installed, installed.parent / 'data', read_only=True) == exit_code
    assert [path.read_bytes() for path in paths] == before
    assert (installed / '.updates/pending' / ARCHIVE).exists()


@pytest.mark.parametrize('probe_fails', [False, True])
def test_automatic_restart_handoff_applies_or_keeps_old_app(installed, signing, monkeypatch, probe_fails):
    data = installed.parent / '기록 폴더'
    assets = package(signing)
    launches, handoffs = [], []
    monkeypatch.setattr(bootstrap.sys, 'executable', str(installed / 'BongoCatChat.exe'))
    monkeypatch.setattr(bootstrap.sys, 'argv', ['launcher', '--data-dir', str(data), '--read-only'])
    monkeypatch.setattr(bootstrap, 'config', lambda: signing[1])
    def launch(command, **kwargs):
        launches.append(command)
        assert kwargs['env'][RESTART_CAPABILITY] == '1'
        assert command[command.index('--data-dir')+1] == str(data)
        assert '--read-only' in command
        if len(launches) == 1:
            # The running session downloaded a new release before its normal
            # shutdown. No pointer or launcher is replaced while it is alive.
            check_and_stage(installed, '0.1.0', signing[1], FixtureTransport(assets), lambda *args: None)
            assert installation(installed)['active'] == '0.1.0'
            return RESTART_FOR_UPDATE
        return 0
    monkeypatch.setattr(bootstrap.subprocess, 'call', launch)
    monkeypatch.setattr(bootstrap.subprocess, 'Popen', lambda command, **kwargs: handoffs.append(command))
    assert bootstrap.main() == 0
    assert len(handoffs) == 1 and len(launches) == 1
    assert installation(installed)['active'] == '0.1.0'
    command = handoffs[0]
    assert command[command.index('--apply-root')+1] == str(installed)
    # The next process can acquire the lock after the old launcher returns.
    with bootstrap.install_lock(installed):
        pass
    monkeypatch.setattr(bootstrap.sys, 'executable', command[0])
    monkeypatch.setattr(bootstrap.sys, 'argv', command)
    waited = []
    class Parent:
        def create_time(self):
            return float(command[command.index('--parent-created')+1])
        def wait(self, timeout):
            waited.append(timeout)
    monkeypatch.setattr(bootstrap.psutil, 'Process', lambda pid: Parent())
    apply = bootstrap.apply_pending
    def probe(*args):
        assert waited == [30]
        if probe_fails:
            raise UpdateError('probe_failed')
    monkeypatch.setattr(bootstrap, 'apply_pending', lambda root, settings: apply(root, settings, probe))
    assert bootstrap.main() == 0
    expected = '0.1.0' if probe_fails else '0.2.0'
    assert installation(installed)['active'] == expected
    assert launches[-1][0] == str(installed / 'versions' / expected / bootstrap.APP)
    assert len(launches) == 2 and len(handoffs) == 1
    assert (installed.parent / 'history.sqlite3').read_bytes() == b'fixture history never opened'
    assert (installed / 'unrelated.txt').read_text() == 'preserve'


def test_normal_app_close_does_not_relaunch(installed, monkeypatch):
    monkeypatch.setattr(bootstrap.sys, 'executable', str(installed / 'BongoCatChat.exe'))
    monkeypatch.setattr(bootstrap.sys, 'argv', ['launcher', '--data-dir', str(installed.parent / 'data')])
    monkeypatch.setattr(bootstrap.subprocess, 'call', lambda *args, **kwargs: 0)
    monkeypatch.setattr(bootstrap, 'handoff', lambda *args: pytest.fail('ordinary close must stay closed'))
    assert bootstrap.main() == 0


@pytest.mark.parametrize('failure', ['copy', 'launch'])
def test_failed_restart_handoff_reopens_current_app_without_retry(installed, signing, monkeypatch, failure):
    launches = []
    assets = package(signing)
    monkeypatch.setattr(bootstrap.sys, 'executable', str(installed / 'BongoCatChat.exe'))
    monkeypatch.setattr(bootstrap.sys, 'argv', ['launcher', '--data-dir', str(installed.parent / 'data'), '--read-only'])
    monkeypatch.setattr(bootstrap, 'config', lambda: signing[1])
    def launch(command, **kwargs):
        launches.append(command)
        assert '--read-only' in command
        assert kwargs['env'][RESTART_CAPABILITY] == ('1' if len(launches) == 1 else '0')
        if len(launches) == 1:
            check_and_stage(installed, '0.1.0', signing[1], FixtureTransport(assets), lambda *args: None)
            return RESTART_FOR_UPDATE
        assert command[0] == str(installed / 'versions/0.1.0' / bootstrap.APP)
        return 0
    def fail(*args, **kwargs):
        raise OSError('synthetic disk or executable failure')
    monkeypatch.setattr(bootstrap.subprocess, 'call', launch)
    monkeypatch.setattr(bootstrap.shutil if failure == 'copy' else bootstrap.subprocess,
                        'copyfile' if failure == 'copy' else 'Popen', fail)
    assert bootstrap.main() == 0
    assert len(launches) == 2
    assert installation(installed)['active'] == '0.1.0'
    assert (installed / '.updates/pending' / ARCHIVE).exists()
    assert (installed.parent / 'history.sqlite3').read_bytes() == b'fixture history never opened'


@pytest.mark.parametrize('corrupt', [False, True])
def test_background_check_resumes_or_repairs_pending(installed, signing, corrupt):
    assets = package(signing)
    pending(installed, assets)
    if corrupt:
        (installed / '.updates/pending' / ARCHIVE).write_bytes(b'corrupt')
    transport = FixtureTransport(assets)
    manager = UpdateManager(installed, '0.1.0', settings=signing[1], transport=transport)
    manager.request()
    manager.thread.join(10)
    assert not manager.thread.is_alive()
    assert manager.snapshot()['state'] == 'ready'
    assert bool(transport.calls) == corrupt
    assert staged_manifest(installed, signing[1])['version'] == '0.2.0'
    manager.close()
