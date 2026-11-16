"""Real isolated HKCU entries, inert slots, and controlled startup outcomes."""
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from bongo_chat import bootstrap, install_metadata as metadata
from bongo_chat.updates import MARKER, atomic_json, installation

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows registration')


@pytest.fixture
def registered(tmp_path, monkeypatch):
    import winreg
    key_path = r'Software\BongoCatChatRegistrationTest-' + uuid4().hex
    root = tmp_path / '한글 앱'
    for version in ('0.1.0.dev34', '1.0.0'):
        slot = root / 'versions' / version
        (slot / 'BongoCatChatApp').mkdir(parents=True)
        (slot / 'BongoCatChatApp/BongoCatChatApp.exe').write_bytes(b'inert')
        atomic_json(slot / bootstrap.VERSION_MARKER, {'schema': 1, 'version': version, 'sha256': 'a' * 64})
    atomic_json(root / MARKER, {'schema': 2, 'active': '1.0.0', 'previous': '0.1.0.dev34'})
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as key:
        for name, value in {'InstallLocation': str(root), 'UninstallString': f'"{root / "Uninstall.exe"}"',
                            'DisplayVersion': '0.1.0.dev34', 'DisplayName': 'preserve-name'}.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        monkeypatch.setattr(metadata, 'UNINSTALL_KEYS', (key_path,))
        yield root, key
    winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key_path, winreg.KEY_WOW64_64KEY)


def displayed(key):
    import winreg
    return winreg.QueryValueEx(key, 'DisplayVersion')[0]


def test_active_version_only_and_other_values_preserved(registered):
    import winreg
    root, key = registered
    assert metadata.sync_installed_version(root, '1.0.0')
    assert displayed(key) == '1.0.0'
    assert winreg.QueryValueEx(key, 'DisplayName')[0] == 'preserve-name'
    atomic_json(root / MARKER, {'schema': 2, 'active': '0.1.0.dev34', 'previous': None})
    assert not metadata.sync_installed_version(root, '1.0.0')
    assert metadata.sync_installed_version(root)
    assert displayed(key) == '0.1.0.dev34'


@pytest.mark.parametrize('field,value', [('InstallLocation', 'C:\\other'), ('InstallLocation', 'relative'),
                                       ('UninstallString', '"C:\\other\\Uninstall.exe"')])
def test_foreign_or_malformed_registration_is_untouched(registered, field, value):
    import winreg
    root, key = registered
    winreg.SetValueEx(key, field, 0, winreg.REG_SZ, value)
    assert not metadata.sync_installed_version(root)
    assert displayed(key) == '0.1.0.dev34'


def test_missing_key_never_created_and_access_errors_are_best_effort(registered, monkeypatch):
    import winreg
    root, _ = registered
    monkeypatch.setattr(metadata, 'UNINSTALL_KEYS', (r'Software\BongoCatChatMissing-' + uuid4().hex,))
    assert not metadata.sync_installed_version(root)
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, metadata.UNINSTALL_KEYS[0])
    monkeypatch.setattr(winreg, 'OpenKey', lambda *args: (_ for _ in ()).throw(PermissionError()))
    assert not metadata.sync_installed_version(root)


@pytest.mark.parametrize('code', [0, 20, 21, 22, 1])
def test_first_upgrade_under_legacy_launcher_fast_exit(registered, code):
    root, key = registered
    def run():
        assert displayed(key) == '0.1.0.dev34'  # no premature candidate registration
        return code
    assert metadata.run_with_install_metadata(root, '1.0.0', run) == code
    assert displayed(key) == ('0.1.0.dev34' if code == 1 else '1.0.0')


def test_first_upgrade_exception_keeps_legacy_version(registered):
    root, key = registered
    with pytest.raises(RuntimeError):
        metadata.run_with_install_metadata(root, '1.0.0', lambda: (_ for _ in ()).throw(RuntimeError()))
    assert displayed(key) == '0.1.0.dev34'


def test_healthy_long_running_legacy_upgrade_reports_after_grace(registered, monkeypatch):
    root, key = registered
    timers = []
    class Timer:
        def __init__(self, interval, callback):
            assert interval >= 45
            self.callback = callback
            timers.append(self)
        def start(self): pass
        def cancel(self): self.cancelled = True
        def join(self): assert self.cancelled
    monkeypatch.setattr(metadata.threading, 'Timer', Timer)
    def run():
        assert displayed(key) == '0.1.0.dev34'
        timers[0].callback()
        assert displayed(key) == '1.0.0'
        return 1  # after 45 seconds the legacy launcher keeps this slot
    assert metadata.run_with_install_metadata(root, '1.0.0', run) == 1


def test_new_launcher_restores_registration_on_rollback(registered, monkeypatch):
    root, key = registered
    monkeypatch.setattr(bootstrap.subprocess, 'call', lambda *args, **kwargs: 1)
    assert bootstrap.run_app(root, root.parent / 'data', offline=True) == 1
    assert installation(root)['active'] == displayed(key) == '0.1.0.dev34'


def test_source_runs_never_register(monkeypatch):
    monkeypatch.setattr(metadata, 'sync_installed_version', lambda *args: pytest.fail('source run touched registry'))
    assert metadata.run_with_install_metadata(None, '1.0.0', lambda: 0) == 0
