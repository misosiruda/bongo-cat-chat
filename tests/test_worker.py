"""Deterministic startup/callback ordering without native calls or real messages."""
import queue
import pytest

from bongo_chat import worker
from test_core import FakeGame, FakeMemory, FakeSteam


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('read_only', [False, True])
@pytest.mark.parametrize('reported', [(3419430, 'fixture-room-a'), (999, 'fixture-other-game-room'), (0, '0')])
def test_worker_connects_and_drains_callbacks_while_memory_is_pending(monkeypatch, failure, read_only, reported):
    order, frames = [], []
    class Stop:
        tick = 0
        def is_set(self):return self.tick >= 6
        def wait(self, seconds):self.tick += 1
    stop = Stop()
    class Game(FakeGame):
        root = 'synthetic-installation'
    class Compatibility:
        def check(self):pass
    class Steam(FakeSteam):
        def __init__(self, root):super().__init__()
        def reported_game(self, account):return reported
        def start(self):order.append('steam')
        def close(self):order.append('steam_closed')
        def pump(self, context, members, accept):
            frames.append((stop.tick, set(members), accept))
            if accept and 'fixture-peer' in members:
                return [dict(type='message', context=context, sender='fixture-peer', text='합성 발언', observed=99)]
            return []
    class Discovery:
        memory = None if failure else FakeMemory()
        failed = failure
        def __init__(self, game, stop):
            order.append('discovery')
            self.done = self
        def is_set(self):return stop.tick >= 3
        def close(self):order.append('discovery_closed')
    class Avatars:
        stage, error = 'ready', ''
        def __init__(self, root):
            # The normal-mode send-enabled state must reach the UI first.
            assert events.queue[-1]['lobby_verified']
            assert events.queue[-1]['send_enabled'] is not read_only
            order.append('avatars')
        def get(self, *args):return None
        def close(self):order.append('avatars_closed')
    from bongo_chat import avatars
    monkeypatch.setattr(avatars, 'Avatars', Avatars)
    monkeypatch.setattr(worker, 'running_game', lambda: Game())
    monkeypatch.setattr(worker, 'verify_compatibility', lambda root, stop: Compatibility())
    monkeypatch.setattr(worker, 'Steam', Steam)
    monkeypatch.setattr(worker, 'MemoryDiscovery', Discovery)
    events = queue.Queue()
    worker.run_worker(queue.Queue(), events, stop, read_only=read_only, render_avatars=True)
    rows = list(events.queue)
    states = [row for row in rows if row['type'] == 'state']
    assert order[:2] == ['steam', 'discovery']
    provisional = reported[0] == 3419430
    assert states[1]['connected'] == provisional and not states[1]['lobby_verified']
    if failure:
        assert states[-1]['connected'] == provisional and states[-1]['notice'] == 'discovery_failed'
        assert not states[-1]['lobby_verified'] and order.count('steam') == 1
    else:
        assert states[-1]['lobby_verified'] and states[-1]['lobby_verified']
    assert (states[1]['generation'] == states[-1]['generation']) == (provisional or failure)
    assert states[-1]['send_enabled'] == (not failure and not read_only)
    assert all(not state['send_enabled'] for state in states if not state['lobby_verified'])
    assert [tick for tick, _, _ in frames] == list(range(6))
    assert all(not members for tick, members, _ in frames if tick <= 3)
    assert sum(row['type'] == 'message' for row in rows) == (0 if failure else 2)
    assert all(row['observed'] == 99 for row in rows if row['type'] == 'message')
    assert order.count('steam_closed') == order.count('discovery_closed') == 1
    assert order.count('avatars') == order.count('avatars_closed') == (0 if failure else 1)


def test_discovery_retries_without_presence_and_without_restarting_steam(monkeypatch):
    from types import SimpleNamespace
    starts, frames, closed, steam_lifetime = [], [], [], []
    class Stop:
        tick = 0
        def is_set(self):return self.tick >= 20
        def wait(self, seconds):self.tick += 1
    stop = Stop()
    class Game(FakeGame):
        root = 'synthetic-installation'
    class Steam(FakeSteam):
        def __init__(self, root):super().__init__()
        def reported_game(self, account):return 999, 'fixture-other-game-room'
        def start(self):steam_lifetime.append('start')
        def close(self):steam_lifetime.append('close')
        def pump(self, context, members, accept):
            frames.append((stop.tick, context['lobby'], set(members)))
            return []
    class Discovery:
        def __init__(self, game, stop):
            starts.append(stop.tick)
            self.failed = len(starts) == 1
            self.memory = None if self.failed else FakeMemory()
            self.done = SimpleNamespace(is_set=lambda: True)
        def close(self):closed.append(True)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: 100 + stop.tick))
    monkeypatch.setattr(worker, 'running_game', lambda: Game())
    monkeypatch.setattr(worker, 'verify_compatibility', lambda *args: SimpleNamespace(check=lambda: None))
    monkeypatch.setattr(worker, 'Steam', Steam)
    monkeypatch.setattr(worker, 'MemoryDiscovery', Discovery)
    events = queue.Queue()
    worker.run_worker(queue.Queue(), events, stop, render_avatars=False)
    states = [row for row in events.queue if row['type'] == 'state']
    assert starts == [0, 16] and len(closed) == 2
    assert steam_lifetime == ['start', 'close']
    assert any(row['notice'] == 'discovery_failed' for row in states)
    assert states[-1]['lobby_verified'] and states[-1]['send_enabled']
    assert [tick for tick, _, _ in frames] == list(range(20))
    assert all(not members for tick, _, members in frames if tick <= 17)
    assert frames[-1][1:] == ('fixture-room-a', {'fixture-self', 'fixture-peer'})
