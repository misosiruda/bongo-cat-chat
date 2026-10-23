"""Real WinRT XML construction and shell registration, with OS delivery mocked."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from bongo_chat import windows_notifications as native
from test_packaging import installation, bundle, run, POWERSHELL, REPO

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows notification adapter')


def shortcut_code(env, code):
    # Reuse the real installer interop without executing the install body.
    interop = (REPO / 'packaging/install.ps1').read_text(encoding='utf-8-sig').split('# Also used by Setup.exe.')[0]
    script = Path(env['LOCALAPPDATA']) / 'shortcut-inspection.ps1'
    script.write_text(interop + '\nInitialize-ShortcutInterop\n' + code, encoding='utf-8-sig')
    result = subprocess.run([str(POWERSHELL), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)], env=env,
                            capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr
    return result.stdout.decode('utf-8-sig').strip()


def ps(path):
    return "'" + str(path).replace("'", "''") + "'"


def test_real_shortcut_identity_upgrade_and_uninstall_ownership(installation, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, env, data = installation
    source = bundle(root)
    target = root / 'installed'
    assert run(source / 'install.ps1', target, env, shortcut=True).returncode == 0
    shortcut = Path(env['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk'
    assert shortcut_code(env, f'[BongoChatShortcut]::ReadAppId({ps(shortcut)})') == native.APP_ID
    for _ in range(2):
        assert run(source / 'install.ps1', target, env, shortcut=True).returncode == 0
        assert shortcut_code(env, f'[BongoChatShortcut]::ReadAppId({ps(shortcut)})') == native.APP_ID
    monkeypatch.setenv('APPDATA', env['APPDATA'])
    native.repair_shortcut(target)
    # Read an existing legacy shortcut, then repair only the matching launcher.
    shortcut.unlink()
    code = f"$shell=New-Object -ComObject WScript.Shell; $link=$shell.CreateShortcut({ps(shortcut)}); $link.TargetPath={ps(target / 'BongoCatChat.exe')}; $link.Save()"
    shortcut_code(env, code)
    assert shortcut_code(env, f'[BongoChatShortcut]::ReadAppId({ps(shortcut)})') == ''
    native.repair_shortcut(target)
    assert shortcut_code(env, f'[BongoChatShortcut]::ReadAppId({ps(shortcut)})') == native.APP_ID
    assert run(REPO / 'packaging/uninstall.ps1', target, env, shortcut=True).returncode == 0
    assert not shortcut.exists()
    assert (data / 'history.sqlite3').read_bytes() == b'synthetic history sentinel'
    app.processEvents()


def test_runtime_never_creates_missing_or_changes_foreign_shortcut(installation, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root, env, _ = installation
    source = bundle(root)
    target, other = root / 'installed', root / 'second'
    assert run(source / 'install.ps1', target, env, shortcut=True).returncode == 0
    assert run(source / 'install.ps1', other, env).returncode == 0
    shortcut = Path(env['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk'
    monkeypatch.setenv('APPDATA', env['APPDATA'])
    before = shortcut.read_bytes()
    with pytest.raises(OSError, match='foreign'):
        native.repair_shortcut(other)
    assert shortcut.read_bytes() == before
    shortcut.unlink()
    with pytest.raises(OSError, match='missing'):
        native.repair_shortcut(target)
    assert not shortcut.exists()
    app.processEvents()


@pytest.mark.parametrize('language,text', [('ko','새 메시지가 도착했어요.'),('en','You have a new message.')])
def test_native_toast_builds_fixed_real_xml_and_respects_os(monkeypatch,language,text):
    app = QApplication.instance() or QApplication([])
    from winrt.windows.ui.notifications import NotificationSetting
    adapter = native.WindowsToast(None,language=lambda:language)
    notifier = SimpleNamespace(setting=NotificationSetting.ENABLED, show=Mock())
    monkeypatch.setattr(adapter, 'prepare', lambda: notifier)
    assert adapter.show() == 'sent'
    toast = notifier.show.call_args.args[0]
    assert toast.tag == native.TOAST_TAG and toast.group == native.TOAST_GROUP
    assert text in toast.content.get_xml()
    assert toast.expiration_time is not None
    notifier.setting = NotificationSetting.DISABLED_FOR_APPLICATION
    assert adapter.show() == 'disabled'
    assert notifier.show.call_count == 1
    app.processEvents()


def test_native_registration_and_cleanup_use_only_own_identity(monkeypatch):
    import winrt.windows.ui.notifications as api
    repair = Mock()
    manager = SimpleNamespace(create_toast_notifier_with_id=Mock(return_value=object()),
                              history=SimpleNamespace(remove_group_with_id=Mock()))
    monkeypatch.setattr(native, 'repair_shortcut', repair)
    monkeypatch.setattr(api, 'ToastNotificationManager', manager)
    adapter = native.WindowsToast('synthetic-root')
    assert adapter.prepare() is adapter.prepare()
    repair.assert_called_once_with('synthetic-root')
    manager.create_toast_notifier_with_id.assert_called_once_with(native.APP_ID)
    adapter.clear()
    manager.history.remove_group_with_id.assert_called_once_with(native.TOAST_GROUP, native.APP_ID)


@pytest.mark.parametrize('error,first_registration', [(-2147023728, True), (5, False)])
def test_initial_settings_row_is_created_by_first_show_only(monkeypatch, error, first_registration):
    import ctypes
    from unittest.mock import PropertyMock
    app = QApplication.instance() or QApplication([])
    notifier = Mock()
    type(notifier).setting = PropertyMock(side_effect=ctypes.WinError(error))
    adapter = native.WindowsToast(None)
    monkeypatch.setattr(adapter, 'prepare', lambda: notifier)
    if first_registration:
        assert adapter.show() == 'sent'
        notifier.show.assert_called_once()
    else:
        with pytest.raises(OSError):
            adapter.show()
        notifier.show.assert_not_called()
    app.processEvents()
