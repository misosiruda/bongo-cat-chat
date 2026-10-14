"""Measure startup without sends, chat decoding, a database or game mutations.

Uses the real worker and discovery thread. Steam callbacks are drained without
reading chat entries; output contains only durations, counts and fixed statuses.
"""
import argparse
import json
import threading
import time

from bongo_chat import worker
from bongo_chat.memory import GameMemory, Reader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=150)
    parser.add_argument('--avatars', action='store_true')
    args = parser.parse_args()
    if not 10 <= args.timeout <= 300:
        parser.error('timeout must be 10..300')
    stop = threading.Event()
    started = time.perf_counter()
    observations, scans, gaps, discoveries = [], [], [], []
    first = {}
    previous, last_emit = None, None
    game = None
    original_steam, original_game, original_scan = worker.Steam, worker.running_game, Reader.scan
    original_discover = GameMemory.discover

    class ReadOnlySteam(original_steam):
        def pump(self, context, members, accept=True):
            if accept and members - {context['account']} and 'receive_eligible' not in first:
                first['receive_eligible'] = round(time.perf_counter()-started, 4)
            return super().pump(context, members, accept=False)

        def send(self, *_):
            raise AssertionError('diagnostic_send_forbidden')

    def running_game():
        nonlocal game
        game = original_game()
        return game

    def scan(reader, *scan_args, **options):
        begin = time.perf_counter()
        result = original_scan(reader, *scan_args, **options)
        scans.append(round(time.perf_counter()-begin, 4))
        return result

    def discover(memory):
        begin = time.perf_counter()
        result = original_discover(memory)
        discoveries.append(dict(method=memory.diagnostics.get('discovery_method'),
                                seconds=round(time.perf_counter()-begin, 4)))
        return result

    class Events:
        def put(self, event, timeout=None):
            nonlocal previous, last_emit
            if event['type'] != 'state':
                return
            elapsed = time.perf_counter()-started
            if last_emit is not None and first.get('connected') is not None:
                gaps.append(elapsed-last_emit)
            last_emit = elapsed
            for key in ('connected', 'lobby_verified', 'privacy_ready', 'hidden_ok'):
                if event.get(key) and key not in first:
                    first[key] = round(elapsed, 4)
            status = {key: event.get(key) for key in
                      ('state', 'notice', 'connected', 'lobby_verified', 'privacy_ready', 'hidden_ok', 'send_enabled')}
            if status != previous:
                previous = status
                row = dict(seconds=round(elapsed, 4), **status)
                observations.append(row)
                print(json.dumps(row), flush=True)
            if 'hidden_ok' in first and elapsed-first['hidden_ok'] >= 3:
                stop.set()

    import queue
    timer = threading.Timer(args.timeout, stop.set)
    timer.daemon = True
    worker.Steam, worker.running_game, Reader.scan = ReadOnlySteam, running_game, scan
    GameMemory.discover = discover
    timer.start()
    try:
        worker.run_worker(queue.Queue(), Events(), stop, read_only=True, render_avatars=args.avatars)
    finally:
        stop.set()
        timer.cancel()
        worker.Steam, worker.running_game, Reader.scan = original_steam, original_game, original_scan
        GameMemory.discover = original_discover
    print(json.dumps(dict(first_seconds=first, scan_seconds=scans, discoveries=discoveries,
                          maximum_state_gap_seconds=round(max(gaps, default=0), 4),
                          avatars_enabled=args.avatars, ready='hidden_ok' in first,
                          sends=0, decoded_messages=0, chat_database_opened=False,
                          lobby_mutations=0, game_writes=0,
                          game_still_running=game.alive() if game else None)), flush=True)
    return 0 if 'hidden_ok' in first else 2


if __name__ == '__main__':
    raise SystemExit(main())
