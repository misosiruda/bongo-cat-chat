"""No real applications, registry writes, Steam calls or inventory are used."""
from contextlib import nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace
import winreg

import pytest

from bongo_chat import game_recovery as recovery
from bongo_chat.auto_chest import DEFAULTS
from bongo_chat.auto_merge import AutoMerge
from bongo_chat.exit_codes import RECOVERY_RETURN, RECOVERY_TOKEN
from bongo_chat.store import Store
from merge_fixture import FakeGameUI


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv(RECOVERY_TOKEN, 'a'*32)
    monkeypatch.delenv(RECOVERY_RETURN, raising=False)
    now = [1000.]
    clock = lambda: now[0]
    store = Store(tmp_path / 'history.sqlite3')
    r = recovery.GameRecovery(tmp_path, store, True, clock)
    assert not r.enabled
    r.set_enabled(True)
    game = FakeGameUI(clock)
    game.begin_run = lambda obs, limit, attempt: game.calls.append(('authorize', limit))
    runner = AutoMerge(game, clock)
    identity = [15, 123, 'a'*32]
    link = SimpleNamespace(recovery_identity=lambda: tuple(identity),
                           connection_snapshot=lambda: dict(state='connected'))
    state = dict(game_pid=15, game_created=1.0, account='101', lobby='202')
    service = SimpleNamespace(verified=lambda: True, state=state)
    chest = dict(armed=False, enabled=False, fresh=True, unknown=False, pending=False,
                 can_start=True, supported=True, reason='ready')
    calls = []
    chests = SimpleNamespace(snapshot=chest.copy, preferences=DEFAULTS.copy(),
                             start=lambda **kw: calls.append(kw) or True)
    s = SimpleNamespace(r=r, now=now, game=game, merger=runner, store=store, link=link, identity=identity,
                        service=service, chests=chests, chest=chest, chest_calls=calls, path=tmp_path, clock=clock)
    s.tick = lambda: s.r.tick(service, runner, chests, link)
    yield s
    store.close()


@pytest.mark.parametrize('token', ['', 'old-launcher', 'a' * 31])
def test_legacy_or_invalid_launcher_cannot_enable_recovery(tmp_path, monkeypatch, token):
    monkeypatch.setenv(RECOVERY_TOKEN, token)
    monkeypatch.delenv(RECOVERY_RETURN, raising=False)
    store = Store(tmp_path / 'history.sqlite3')
    try:
        r = recovery.GameRecovery(tmp_path, store, True)
        assert not r.supported and not r.enabled
        with pytest.raises(ValueError, match='invalid_setting'):
            r.set_enabled(True)
        assert store.setting('unattended_recovery', default=False) is False
    finally:
        store.close()


def interrupt_merge(s):
    assert s.merger.start(9)
    s.merger.completed = 4
    s.merger.tick()
    s.tick()
    s.game.value = replace(s.game.value, ready=False, reason='inventory_refreshing')
    s.merger.tick()
    s.tick()
    s.now[0] += recovery.OUTAGE_SECONDS - 1
    s.tick()
    assert s.r.candidate is None
    s.now[0] += 1
    s.tick()


def relaunch(s, monkeypatch, plan):
    s.merger.close()
    s.merger.__init__(s.game, s.clock)
    s.game.closed = False
    s.identity[:] = [24, 456, 'b'*32]
    s.service.state.update(game_pid=24, game_created=2.0)
    monkeypatch.setenv(RECOVERY_RETURN, json.dumps(dict(plan, new_pid=24, new_created=2.0)))
    s.r = recovery.GameRecovery(s.path, s.store, True, s.clock)
    s.game.value = replace(s.game.value, ready=True, reason='ready', run_attempt='')


def test_interrupted_merge_resumes_only_remaining_budget_once(session, monkeypatch):
    s = session
    interrupt_merge(s)
    assert s.r.handoff()
    plan = json.loads(recovery.handoff_path(s.path, s.r.token).read_bytes())
    assert plan['completed'] == 4 and plan['limit'] == 9
    relaunch(s, monkeypatch, plan)
    s.service.verified = lambda: False
    s.tick()
    assert s.r.status == 'waiting_room' and not s.merger.active
    s.service.verified = lambda: True
    s.tick()
    assert s.r.status == 'resumed' and s.merger.completed == 4
    s.tick()
    assert [n for op,n in s.game.calls if op=='authorize'] == [9, 5]
    assert not s.chest_calls
    s.merger.recovering_since = s.clock()
    s.now[0] += 300
    s.tick()
    assert not s.r.candidate  # Server outage continued after restart.


@pytest.mark.parametrize('change', ['room', 'account', 'process', 'protection', 'cancel', 'legacy'])
def test_recovery_does_not_transfer_authority(session, monkeypatch, change):
    s = session
    interrupt_merge(s)
    relaunch(s, monkeypatch, s.r.candidate)
    if change == 'room': s.service.state['lobby'] = '999'
    if change == 'account': s.service.state['account'] = '999'
    if change == 'process': s.service.state['game_created'] += 1
    if change == 'protection': s.game.value = replace(s.game.value, favorites_allowed=True)
    if change == 'cancel': s.r.cancel()
    if change == 'legacy': s.chest['legacy_detected'] = True
    s.tick()
    assert not s.merger.active and s.r.resume is None
    assert s.game.calls == [('authorize', 9)]


def test_chest_wait_result_pause_stop_and_resume(session, monkeypatch):
    s = session
    s.chest.update(armed=True, enabled=True, owned_run='explicit-start', reason='running')
    s.tick()
    s.chest.update(reason='connection_recovering', fresh=False, pending=True)
    s.tick()
    s.now[0] += 180
    s.tick()
    assert not s.r.candidate
    s.chest['pending'] = False
    s.tick()
    s.now[0] += 120
    s.tick()
    plan = s.r.candidate
    assert plan['mode'] == 'chest'
    s.chest['enabled'] = False
    s.tick()
    assert not s.r.handoff()
    s.chest.update(armed=False, fresh=True, owned_run='', reason='ready')
    relaunch(s, monkeypatch, plan)
    monkeypatch.setattr(recovery, 'previous_chest_requests', lambda plan: ['F'*64])
    s.tick()
    s.tick()
    assert s.chest_calls == [{'remote_keys': ['F'*64]}] and not s.merger.active


def test_pending_or_stopped_merge_withdraws_handoff(session):
    s = session
    interrupt_merge(s)
    assert s.r.candidate
    s.merger.pending_attempt = 'outstanding'
    s.tick()
    assert not s.r.handoff()
    s.merger.stop()
    s.now[0] += 130
    s.tick()
    assert not s.r.handoff()


@pytest.mark.parametrize('mode', ['merge', 'chest'])
def test_run_first_seen_without_verified_room_cannot_adopt_a_later_room(session, mode):
    s = session
    s.service.verified = lambda: False
    if mode == 'merge':
        assert s.merger.start(3)
        s.merger.recovering_since = s.clock()
    else:
        s.chest.update(armed=True, enabled=True, owned_run='original', reason='connection_recovering')
    s.tick()
    s.service.state['lobby'] = '999'
    s.service.verified = lambda: True
    s.tick()
    s.now[0] += recovery.OUTAGE_SECONDS
    s.tick()
    assert not s.r.handoff()


def test_paused_chest_cannot_adopt_a_different_room(session):
    s = session
    s.chest.update(armed=True, enabled=True, owned_run='original', reason='running')
    s.tick()
    s.chest.update(enabled=False, reason='paused')
    s.tick()
    s.service.state['lobby'] = '999'
    s.tick()
    s.chest.update(enabled=True, reason='connection_recovering')
    s.tick()
    s.now[0] += recovery.OUTAGE_SECONDS
    s.tick()
    assert not s.r.handoff()
    # A new start in this room has its own identity.
    s.chest.update(owned_run='new-run', reason='running')
    s.tick()
    s.chest['reason'] = 'connection_recovering'
    s.tick()
    s.now[0] += recovery.OUTAGE_SECONDS
    s.tick()
    assert s.r.handoff() and s.r.candidate['lobby'] == recovery.fingerprint('999')


def test_registry_preserves_last_lobby_and_checks_persisted_value(monkeypatch):
    values = {'LAST_LOBBY_h626087530': (b'12\0', winreg.REG_BINARY),
              'JoinLastLobby_h3133418007': (0, winreg.REG_DWORD)}
    monkeypatch.setattr(winreg, 'OpenKey', lambda *args: nullcontext('game'))
    monkeypatch.setattr(winreg, 'QueryValueEx', lambda handle,key: values[key])
    monkeypatch.setattr(winreg, 'SetValueEx', lambda h,k,z,t,v: values.update({k:(v,t)}))
    monkeypatch.setattr(winreg, 'FlushKey', lambda h: None)
    with pytest.raises(ValueError, match='different_saved_lobby'):
        recovery.saved_lobby_setting(recovery.fingerprint(3), enable=True)
    expected = recovery.fingerprint(61)
    recovery.saved_lobby_setting(expected)
    assert values['JoinLastLobby_h3133418007'][0] == 0
    recovery.saved_lobby_setting(expected, enable=True)
    assert values['JoinLastLobby_h3133418007'] == (1, winreg.REG_DWORD)
    assert values['LAST_LOBBY_h626087530'][0] == b'12\0'


def test_durable_chest_result_and_remote_keys_cross_game_lifetime(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery.Path, 'home', lambda: tmp_path)
    session_path = tmp_path / '.bongo-cat-chat' / 'merge-bridge' / '15-123'
    session_path.mkdir(parents=True)
    def write(name, payload):
        (session_path/name).write_text(json.dumps(payload))
    plan = dict(mode='chest', pid=15, ticks=123, epoch='abc')
    write('session.json', dict(epoch='abc'))
    write('snapshot.json', dict(epoch='abc', chest=dict(pending=False, unknown=False)))
    write('chest-ledger.json', dict(state='requested', remote_keys=[]))
    with pytest.raises(ValueError, match='unresolved_chest'):
        recovery.previous_chest_requests(plan)
    write('chest-ledger.json', dict(state='remote_requested', remote_keys=['A'*64]))
    assert recovery.previous_chest_requests(plan) == ['A'*64]
    write('snapshot.json', dict(epoch='abc', chest=dict(pending=True, unknown=False)))
    with pytest.raises(ValueError, match='unresolved_chest'):
        recovery.previous_chest_requests(plan)
    for malformed in (None, [], {}, dict(pending=0, unknown=False), dict(pending=False, unknown=None)):
        write('snapshot.json', dict(epoch='abc', chest=malformed))
        with pytest.raises(ValueError, match='unresolved_chest'):
            recovery.previous_chest_requests(plan)


@pytest.mark.parametrize('name', ['session.json', 'chest-ledger.json', 'snapshot.json'])
def test_malformed_chest_record_prevents_restart(tmp_path, monkeypatch, name):
    monkeypatch.setattr(recovery.Path, 'home', lambda: tmp_path)
    folder = tmp_path / '.bongo-cat-chat' / 'merge-bridge' / '15-123'
    folder.mkdir(parents=True)
    for filename, data in [('session.json', dict(epoch='abc')),
                           ('chest-ledger.json', dict(state='armed', remote_keys=[])),
                           ('snapshot.json', dict(epoch='abc', chest=dict(unknown=False, pending=False)))]:
        (folder / filename).write_text(json.dumps(data))
    plan = dict(mode='chest', pid=15, ticks=123, epoch='abc')
    for raw in (b'[' * 2000 + b']' * 2000, b' ' * 65537):
        (folder / name).write_bytes(raw)
        with pytest.raises(ValueError):
            recovery.previous_chest_requests(plan)


@pytest.mark.parametrize('outcome', ['success', 'unsafe', 'save_failure', 'different_process'])
def test_launcher_closes_and_opens_only_the_intended_game(monkeypatch, outcome):
    calls = []
    old = SimpleNamespace(pid=10, created=100, root='game', alive=lambda: True)
    new = SimpleNamespace(pid=20, created=200, root='game')
    monkeypatch.setattr(recovery, 'running_game', lambda: new if 'launch' in calls else old)
    monkeypatch.setattr(recovery.psutil, 'process_iter', lambda attrs: [])
    def save(room, *, enable=False):
        calls.append('on' if enable else 'check')
        if enable and outcome=='save_failure': raise OSError
    monkeypatch.setattr(recovery, 'saved_lobby_setting', save)
    def previous_requests(plan):
        if outcome == 'unsafe': raise ValueError('unresolved_chest')
        return []
    monkeypatch.setattr(recovery, 'previous_chest_requests', previous_requests)
    monkeypatch.setattr(recovery, 'close_game', lambda g: calls.append('close'))
    monkeypatch.setattr(recovery.os, 'startfile', lambda uri: calls.append('launch'))
    monkeypatch.setattr(recovery.time, 'sleep', lambda seconds: None)
    plan = dict(mode='chest', pid=11 if outcome=='different_process' else 10, created=100, lobby='room')
    if outcome=='success':
        result = recovery.restart_game(plan)
        assert result['new_pid'] == 20 and result['new_created'] == 200
    else:
        with pytest.raises((ValueError, RuntimeError)): recovery.restart_game(plan)
    assert calls == {'success':['check','close','on','launch'], 'save_failure':['check','close','on','launch'],
                     'unsafe':['check'], 'different_process':[]}[outcome]
