"""Immutable dev34 updater + current entry/session loop; synthetic apps only."""
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from bongo_chat import __version__, __main__ as entry, bootstrap, launcher_compat as compat
from bongo_chat.exit_codes import RECOVERY_RETURN, RECOVERY_TOKEN, RESTART_CAPABILITY
from bongo_chat.game_recovery import GameRecovery, handoff_path
from bongo_chat.updates import atomic_json, installation
from test_updates import installed, signing, package, pending


def args(**overrides):
    return SimpleNamespace(**(dict(offline=False, read_only=False, smoke_report=None,
                                  connection_report=None, update_smoke_dir=None,
                                  merge_bridge_session=None) | overrides))


@pytest.fixture
def old_parent(installed, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(installed / 'versions' / __version__ / 'BongoCatChatApp/BongoCatChatApp.exe'))
    monkeypatch.delenv(RECOVERY_TOKEN, raising=False)
    monkeypatch.delenv(RECOVERY_RETURN, raising=False)
    monkeypatch.setenv(RESTART_CAPABILITY, '1')
    parent = SimpleNamespace(exe=lambda: str(installed / '.updates' / ('bootstrap-' + 'a'*32 + '.exe')))
    monkeypatch.setattr(compat.psutil, 'Process', lambda: SimpleNamespace(parent=lambda: parent))
    return parent


@pytest.mark.parametrize('location', ['helper', 'root', 'foreign', 'wrong_helper'])
def test_only_verified_installed_launcher_parent_needs_host(installed, monkeypatch, old_parent, location):
    if location == 'root': old_parent.exe = lambda: str(installed / 'BongoCatChat.exe')
    if location == 'foreign': old_parent.exe = lambda: str(installed.parent / 'other/BongoCatChat.exe')
    if location == 'wrong_helper': old_parent.exe = lambda: str(installed / '.updates/other.exe')
    assert compat.needs_session_host(installed, args()) == (location in ('helper','root'))


@pytest.mark.parametrize('mode', ['offline','read_only','smoke_report','connection_report',
                                 'update_smoke_dir','merge_bridge_session','source','no_root','disabled','modern'])
def test_diagnostics_sources_and_new_children_never_nest(installed, monkeypatch, old_parent, mode):
    options = args()
    if mode == 'source': monkeypatch.setattr(sys, 'frozen', False)
    elif mode == 'no_root': installed = None
    elif mode == 'disabled': monkeypatch.setenv(RESTART_CAPABILITY, '0')
    elif mode == 'modern': monkeypatch.setenv(RECOVERY_TOKEN, 'b'*32)
    else: setattr(options, mode, True)
    assert not compat.needs_session_host(installed, options)


def test_onefile_parent_and_missing_old_capability(installed, monkeypatch, old_parent):
    monkeypatch.delenv(RESTART_CAPABILITY)
    bootloader = SimpleNamespace(exe=lambda: sys.executable, parent=lambda: old_parent)
    monkeypatch.setattr(compat.psutil, 'Process', lambda: SimpleNamespace(parent=lambda: bootloader))
    assert compat.needs_session_host(installed, args())
    monkeypatch.setattr(compat.psutil, 'Process', lambda: (_ for _ in ()).throw(PermissionError()))
    assert not compat.needs_session_host(installed, args())


@pytest.mark.parametrize('child_exit', [0, 1, 20, 21, 23, 'launch_error'])
def test_dev34_signed_update_first_session_without_setup(installed, signing, monkeypatch, old_parent, child_exit):
    # Source is copied unchanged from 22d91a292c3f0e498d25c95221f2e1bdd77b194b.
    legacy = ModuleType('bongo_chat._dev34_bootstrap')
    legacy.__package__ = 'bongo_chat'
    source = Path(__file__).with_name('fixtures').joinpath('dev34_bootstrap.py').read_text(encoding='utf-8-sig')
    exec(compile(source, '<dev34 bootstrap>', 'exec'), legacy.__dict__)
    assets = package(signing, release_version=__version__)
    pending(installed, assets)
    legacy.apply_pending(installed, signing[1], probe=lambda *a: None)
    # The old updater already replaces the launcher on disk, before opening UI.
    assert (installed / 'BongoCatChat.exe').read_bytes() == b'new launcher'
    data = installed.parent / '별도 기록'
    data.mkdir()
    history = data / 'history.sqlite3'
    history.write_bytes(b'unchanged history and preferences')
    monkeypatch.setattr(sys, 'argv', ['app', '--install-root', str(installed), '--data-dir', str(data)])
    monkeypatch.setattr(bootstrap, 'sync_installed_version', lambda *a: None)
    restarts, children = [], []
    monkeypatch.setattr(bootstrap, 'restart_game', lambda plan: restarts.append(plan) or dict(plan, new_pid=2, new_created=2.0))
    plan = dict(mode='merge', pid=1, ticks=1, created=1.0, epoch='c'*32, account='d'*64,
                lobby='e'*64, group='cosmetics', favorites=False, events=True, completed=4, limit=9)

    def launch(command, **kwargs):
        env = kwargs['env']
        if RECOVERY_TOKEN not in env:
            assert compat.needs_session_host(installed, args())
            return entry.main()  # Same first app entry used by the old helper.
        with monkeypatch.context() as child:
            child.setenv(RECOVERY_TOKEN, env[RECOVERY_TOKEN])
            assert not compat.needs_session_host(installed, args())
            settings = SimpleNamespace(setting=lambda name, default=False: default)
            recovery = GameRecovery(data, settings, True)
            assert recovery.supported and not recovery.enabled
        assert command[command.index('--data-dir')+1] == str(data)
        children.append(dict(env))
        if child_exit == 'launch_error':
            raise OSError('synthetic quarantined executable')
        if child_exit == 23 and len(children) == 1:
            atomic_json(handoff_path(data, env[RECOVERY_TOKEN]), plan)
            return 23
        return 0 if child_exit == 23 else child_exit

    monkeypatch.setattr(bootstrap.subprocess, 'call', launch)
    # Real old ownership is retained; taking another install lock would fail.
    with bootstrap.install_lock(installed):
        result = legacy.run_app(installed, data)
    assert result == (1 if child_exit == 'launch_error' else 0 if child_exit == 23 else child_exit)
    assert len(children) == (2 if child_exit == 23 else 1)
    if child_exit == 23:
        assert restarts == [plan]
        assert json.loads(children[1][RECOVERY_RETURN])['completed'] == 4
        assert children[0][RECOVERY_TOKEN] != children[1][RECOVERY_TOKEN]
    else:
        assert not restarts
    assert installation(installed)['active'] == ('0.1.0' if child_exit in (1, 'launch_error') else __version__)
    assert history.read_bytes() == b'unchanged history and preferences'
    assert (installed / 'unrelated.txt').read_text() == 'preserve'
