"""Deterministic startup/callback ordering without native calls or real messages."""
import queue
import pytest

from bongo_chat import worker
from test_core import FakeGame, FakeMemory, FakeSteam


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('read_only', [False, True])
def test_worker_connects_and_drains_callbacks_while_memory_is_pending(monkeypatch, failure, read_only):
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
        def start(self):order.append('steam')
        def close(self):order.append('steam_closed')
        def pump(self, context, members, accept):
            frames.append((stop.tick, set(members), accept))
            if accept and 'fixture-peer' in members:
                return [dict(type='message', context=context, sender='fixture-peer', text='합성 발언')]
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
    assert states[1]['connected'] and not states[1]['lobby_verified']
    if failure:
        assert states[-1]['connected'] and states[-1]['notice'] == 'discovery_failed'
        assert not states[-1]['lobby_verified'] and order.count('steam') == 1
    else:
        assert states[-1]['lobby_verified'] and states[-1]['hidden_ok']
    assert states[1]['generation'] == states[-1]['generation']
    assert states[-1]['send_enabled'] == (not failure and not read_only)
    assert all(not state['send_enabled'] for state in states if not state['lobby_verified'])
    assert [tick for tick, _, _ in frames] == list(range(6))
    assert all(not members for tick, members, _ in frames if tick <= 3)
    assert sum(row['type'] == 'message' for row in rows) == (0 if failure else 2)
    assert order.count('steam_closed') == order.count('discovery_closed') == 1
    assert order.count('avatars') == order.count('avatars_closed') == (0 if failure else 1)
