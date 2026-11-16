"""Pat forwarding through the real worker loop, without native/game operations."""
import queue
from types import SimpleNamespace

import pytest

from bongo_chat import worker
from test_core import FakeGame, FakeMemory, FakeSteam


@pytest.mark.parametrize('supported', [True, False])
@pytest.mark.parametrize('mode', ['normal', 'pat-full', 'burst'])
def test_worker_preserves_pat_timestamp_and_chat_when_pats_are_disabled_or_full(monkeypatch, supported, mode):
    class Stop:
        tick = 0
        def is_set(self): return self.tick >= 6
        def wait(self, seconds): self.tick += 1
        def set(self): raise AssertionError('Transient pats must not stop chat')
    stop = Stop()
    class Events(queue.Queue):
        dropped = 0
        def put_nowait(self, item):
            if item['type'] == 'pat' and mode == 'pat-full':
                self.dropped += 1
                raise queue.Full
            super().put_nowait(item)
    class Game(FakeGame):
        root = 'synthetic-installation'
    class Steam(FakeSteam):
        def __init__(self, root): super().__init__()
        def start(self): pass
        def close(self): pass
        def pump(self, context, members, accept):
            if not accept or 'fixture-peer' not in members: return []
            return [dict(type='pat', context=context, sender='fixture-peer', target='fixture-self',
                         id=f'pat-{stop.tick}-{n}', observed=123.45)
                    for n in range(1000 if mode == 'burst' else 1)] + [
                    dict(type='message', context=context, sender='fixture-peer', text='합성 발언', observed=99)]
        def send(self, *args): raise AssertionError('Pats must not send anything')
    class Discovery:
        memory, failed = FakeMemory(), False
        done = SimpleNamespace(is_set=lambda: True)
        def __init__(self, *args): pass
        def close(self): pass
    monkeypatch.setattr(worker, 'running_game', lambda: Game())
    monkeypatch.setattr(worker, 'verify_compatibility', lambda *args: SimpleNamespace(check=lambda: None))
    monkeypatch.setattr(worker, 'verify_pat_compatibility', lambda *args: supported)
    monkeypatch.setattr(worker, 'Steam', Steam)
    monkeypatch.setattr(worker, 'MemoryDiscovery', Discovery)
    events = Events(maxsize=2048)  # Same capacity as the real controller; no consumer drains this burst.
    worker.run_worker(queue.Queue(), events, stop, render_avatars=False)
    rows = list(events.queue)
    states = [row for row in rows if row['type'] == 'state']
    messages = [row for row in rows if row['type'] == 'message']
    pats = [row for row in rows if row['type'] == 'pat']
    assert states[-1]['lobby_verified'] and states[-1]['send_enabled']
    assert states[-1]['pats_supported'] is supported
    assert len(messages) > 1
    if supported and mode == 'burst':
        assert 0 < len(pats) <= 1024
    else:
        assert len(pats) == (len(messages) if supported and mode == 'normal' else 0)
    assert events.dropped == (len(messages) if supported and mode == 'pat-full' else 0)
    assert all(row['observed'] == 123.45 for row in pats)
