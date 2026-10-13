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
    parser.add_argument("--smoke-report", type=Path, help="Offline-only renderer smoke report, then exit")
    parser.add_argument("--connection-report", type=Path, help="Read-only native/renderer report, then exit")
    args = parser.parse_args()
    if args.smoke_report and not args.offline:
        parser.error("--smoke-report requires --offline")
    if args.connection_report and (not args.read_only or args.offline or args.smoke_report):
        parser.error("--connection-report requires --read-only and an actual connection")
    from .desktop import run
    return run(args.data_dir.resolve(), args.offline, args.read_only, args.smoke_report, args.connection_report)


if __name__ == "__main__":
    raise SystemExit(main())
