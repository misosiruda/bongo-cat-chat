"""Best-effort Windows installed-app version, bound to an existing owned entry."""
import os
from pathlib import Path
import threading

from .exit_codes import PROFILE_IN_USE, RESTART_FOR_UPDATE, UPDATE_DIAGNOSTIC_FAILED
from .updates import child, installation, no_links

UNINSTALL_KEYS = (
    r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BongoCatChat',
    r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BongoCatChatInstallerTest',
)
# dev34's launcher rolls back abnormal exits during its first 45 seconds.
# The app starts this timer later than the launcher starts its rollback clock.
LEGACY_STARTUP_GRACE = 45
ACCEPTED_EXITS = (0, PROFILE_IN_USE, RESTART_FOR_UPDATE, UPDATE_DIAGNOSTIC_FAILED)


def sync_installed_version(root, expected_version=None):
    """Never create a key, follow a junction, or modify another installation."""
    if os.name != 'nt' or root is None:
        return False
    import winreg
    try:
        root = no_links(root)
        active = installation(root)['active']
        if expected_version is not None and active != expected_version:
            return False
        if not child(root, 'versions', active, 'BongoCatChatApp', 'BongoCatChatApp.exe').is_file():
            return False
        for key_path in UNINSTALL_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                    winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
                    location, kind = winreg.QueryValueEx(key, 'InstallLocation')
                    if kind != winreg.REG_SZ or not isinstance(location, str) or not Path(location).is_absolute():
                        continue
                    if no_links(location) != root:
                        continue
                    uninstall, kind = winreg.QueryValueEx(key, 'UninstallString')
                    if kind != winreg.REG_SZ or uninstall != f'"{child(root, "Uninstall.exe")}"':
                        continue
                    winreg.SetValueEx(key, 'DisplayVersion', 0, winreg.REG_SZ, active)
                    return True
            except (OSError, ValueError):
                continue
    except (OSError, ValueError):
        pass
    return False


def run_with_install_metadata(root, expected_version, run):
    """Support the first upgrade launched by dev34 without racing its rollback.

    A fast successful exit is accepted by the old launcher. An abnormal early
    exit leaves its previous DisplayVersion intact. Long-running apps report
    after the old launcher's rollback window has elapsed.
    """
    if root is None:
        return run()
    report = lambda: sync_installed_version(root, expected_version)
    timer = threading.Timer(LEGACY_STARTUP_GRACE, report)
    timer.daemon = True
    timer.start()
    try:
        code = run()
        if code in ACCEPTED_EXITS:
            report()
        return code
    finally:
        timer.cancel()
        timer.join()
