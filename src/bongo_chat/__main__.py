import argparse
import multiprocessing
import os
from pathlib import Path


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Bongo Cat Chat Windows development app")
    parser.add_argument("--offline", action="store_true", help="Do not initialize Steam or read the game")
    parser.add_argument("--read-only", action="store_true", help="Connect but reject all outgoing messages")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ".")) / "BongoCatChat")
    parser.add_argument("--install-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-report", type=Path, help="Offline-only renderer smoke report, then exit")
    parser.add_argument("--connection-report", type=Path, help="Read-only native/renderer report, then exit")
    parser.add_argument('--merge-bridge-session',type=Path,help='Opt-in connection to a separately installed local test bridge')
    parser.add_argument('--update-smoke-dir', type=Path, help='Offline-worker installed updater diagnostic; requires --offline and explicit --data-dir')
    args = parser.parse_args()
    if args.merge_bridge_session and (args.offline or args.read_only):
        parser.error('--merge-bridge-session cannot be used in offline or read-only mode')
    if args.smoke_report and not args.offline:
        parser.error("--smoke-report requires --offline")
    if args.connection_report and (not args.read_only or args.offline or args.smoke_report):
        parser.error("--connection-report requires --read-only and an actual connection")
    if args.update_smoke_dir:
        import sys
        if (not args.offline or not args.install_root or args.smoke_report or args.connection_report
                or not any(value == '--data-dir' or value.startswith('--data-dir=') for value in sys.argv[1:])):
            parser.error('--update-smoke-dir requires an installed offline app and explicit --data-dir')
    from .desktop import run
    install_root = None
    if args.install_root:
        from . import __version__
        from .updates import child, installation, no_links
        install_root = no_links(args.install_root)
        marker = installation(install_root)
        expected = child(install_root, 'versions', __version__, 'BongoCatChatApp', 'BongoCatChatApp.exe')
        import sys
        if marker['active'] != __version__ or no_links(sys.executable) != expected or args.data_dir.resolve().is_relative_to(install_root):
            parser.error('invalid installation or data directory')
    return run(args.data_dir.resolve(), args.offline, args.read_only, args.smoke_report, args.connection_report, install_root,
               update_smoke_dir=args.update_smoke_dir, merge_bridge_session=args.merge_bridge_session)


if __name__ == "__main__":
    raise SystemExit(main())
