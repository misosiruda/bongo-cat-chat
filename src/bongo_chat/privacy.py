"""Per-Windows-user update permission, shared with the installer (no network)."""
import winreg

KEY = r"Software\BongoCatChat"
VALUE = "AllowUpdateChecks"


def update_checks_allowed():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE)
        return kind == winreg.REG_DWORD and value == 1
    except FileNotFoundError:
        return True  # Preserve the documented behaviour of earlier versions.
    except OSError:
        return False  # Unreadable permission must not enable network traffic.


def set_update_checks_allowed(allowed):
    if type(allowed) is not bool:
        raise ValueError("invalid_update_permission")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE, 0, winreg.REG_DWORD, int(allowed))
