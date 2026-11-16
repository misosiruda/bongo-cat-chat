"""First updated session under an older, already-running launcher.

The signed updater has replaced the launcher on disk, but its old helper still
owns the installation lock and waits for this app. This process can host the
current session loop before creating any Qt window, worker or data profile.
The child receives a recovery token, so it opens the UI without nesting again.
"""
import os
import re
import sys

import psutil

from .exit_codes import RECOVERY_TOKEN, RESTART_CAPABILITY
from .updates import child, no_links


def needs_session_host(root, args):
    if (root is None or not getattr(sys, 'frozen', False)
            or any((args.offline, args.read_only, args.smoke_report, args.connection_report,
                    args.update_smoke_dir, args.merge_bridge_session))
            or os.environ.get(RESTART_CAPABILITY) == '0'
            or re.fullmatch('[0-9a-f]{32}', os.environ.get(RECOVERY_TOKEN, ''))):
        return False
    try:
        parent = psutil.Process().parent()
        # A onefile bootloader may sit between the app and its launcher.
        if parent and no_links(parent.exe()) == no_links(sys.executable):
            parent = parent.parent()
        if not parent:
            return False
        executable = no_links(parent.exe())
        return (executable == child(root, 'BongoCatChat.exe')
                or (executable.parent == child(root, '.updates')
                    and bool(re.fullmatch(r'bootstrap-[0-9a-f]{32}\.exe', executable.name))))
    except (OSError, ValueError, psutil.Error):
        return False


def run_session_host(root, data):
    from .bootstrap import run_app
    # The older launcher keeps its existing installation lock. Do not acquire
    # it again, rewrite executables, or open the user's database in this host.
    return run_app(root, data, legacy_host=True)
