"""Synthetic pat packets and monotonic clocks; no live game or participant data."""
import ctypes as C
import json
import sqlite3
from uuid import uuid4

import pytest

from bongo_chat.protocol import decode_event, decode, InvalidMessage
from bongo_chat.service import ChatService
from bongo_chat.steam import Steam, Callback, ChatHeader
from test_core import store, state


def pat(service, sender='1001', target='1002', **changes):
    return dict(dict(type='pat', id=str(uuid4()), context=service.context(), sender=sender,
                     target=target, observed=service.clock()), **changes)


@pytest.fixture
def pats(store):
    now = [100.0]
    service = ChatService(store, clock=lambda: now[0])
    service.update(state(account='1001', members=[str(i) for i in range(1001, 1010)], pats_supported=True,
                         profiles={str(i): dict(name=f'고양이 {i-1000}') for i in range(1001, 1010)}))
    return service, now


def snapshot(service):
    return service.pat_view(service.state['lobby'])


@pytest.mark.parametrize('target', ['1', '1002', '18446744073709551615'])
def test_pat_decode_is_not_a_chat_message(target):
    raw = json.dumps(dict(Channel=8, Message=target)).encode()
    assert decode_event(raw) == dict(type='pat', target=target)
    assert decode(raw) is None


@pytest.mark.parametrize('target', [0, 1, True, None, [], {}, '', '0', '01', '+1', '-1',
                                  ' 1', '1\n', '１', '١', '18446744073709551616'])
def test_pat_target_must_be_canonical_uint64(target):
    with pytest.raises(InvalidMessage):
        decode_event(json.dumps(dict(Channel=8, Message=target)).encode())


def test_callback_copies_every_pat_and_rejects_nonmember_and_self_target():
    steam = Steam.__new__(Steam)
    steam.pipe = steam.matchmaking = 1
    steam.rejected = 0
    steam.run_frame = lambda _: None
    packets = [dict(Channel=8, Message=x) for x in ('1002', '1002', '1003', '1001', '9999')]
    header = ChatHeader(10, 1001, 1, 0)
    freed, index = [], [-1]
    def next_callback(_, out):
        index[0] += 1
        if index[0] == len(packets): return False
        header.chat_id = index[0]
        cb = C.cast(out, C.POINTER(Callback)).contents
        cb.kind, cb.size, cb.data = 507, C.sizeof(header), C.addressof(header)
        return True
    def read(_, lobby, chat_id, sender, buffer, size, kind):
        assert chat_id not in freed
        C.cast(sender, C.POINTER(C.c_uint64))[0] = 1001
        C.cast(kind, C.POINTER(C.c_int))[0] = 1
        raw = json.dumps(packets[chat_id]).encode()
        C.memmove(buffer, raw, len(raw))
        return len(raw)
    steam.next_callback, steam.read_entry = next_callback, read
    steam.free_callback = lambda _: freed.append(index[0])
    events = steam.pump(dict(lobby='10', account='1002', generation='test'), {'1001','1002','1003'})
    assert [e['target'] for e in events] == ['1002','1002','1003']
    assert all(e['sender'] == '1001' and 'chat_id' not in e for e in events)
    assert len({e['id'] for e in events}) == 3
    assert freed == list(range(5)) and steam.rejected == 2


@pytest.mark.parametrize('gap,count', [(0, 2), (.999, 2), (1, 1), (1.001, 1), (1.4, 1), (2, 1)])
def test_streak_boundary_and_fade_restart(pats, gap, count):
    service, now = pats
    service.receive_pat(pat(service))
    now[0] += gap
    service.receive_pat(pat(service))
    view = snapshot(service)
    assert len(view['rows']) == 1
    assert view['rows'][0]['count'] == count
    assert view['rows'][0]['expires_in_ms'] == 2000


def test_duplicate_receipt_not_content_deduplicated_and_no_history(pats):
    service, _ = pats
    before = service.view()
    first = pat(service)
    service.receive_pat(first)
    service.receive_pat(first)
    service.receive_pat(pat(service))
    assert snapshot(service)['rows'][0]['count'] == 2
    after = service.view()
    for key in ('messages', 'unseen', 'unseen_seq', 'latest_seq', 'revision'):
        assert before[key] == after[key]
    assert service.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    assert not service.receipts and not service.volatile and not service.reactions


def test_direction_identity_and_names(pats):
    service, _ = pats
    service.state['profiles']['1001']['name'] = service.state['profiles']['1002']['name'] = '같은 이름'
    service.nicknames['1003'] = '<script>별명</script>'
    for sender, target in [('1001','1002'), ('1002','1001'), ('1002','1003')]:
        service.receive_pat(pat(service, sender, target))
    rows = snapshot(service)['rows']
    assert [(r['sender'], r['target']) for r in rows] == [('1001','1002'), ('1002','1001'), ('1002','1003')]
    assert rows[-1]['target_name'] == '<script>별명</script>'


def test_same_pair_stays_in_slot_and_overflow_retains_count(pats):
    service, now = pats
    for target in ('1002','1003','1004'):
        service.receive_pat(pat(service, target=target)); now[0] += .1
    service.receive_pat(pat(service, target='1002'))
    assert [r['target'] for r in snapshot(service)['rows']] == ['1002','1003','1004']
    now[0] += .1
    service.receive_pat(pat(service, target='1005'))
    assert [r['target'] for r in snapshot(service)['rows']] == ['1002','1005','1004']
    assert len(snapshot(service)['hidden_active_ms']) == 1
    now[0] += .1
    service.receive_pat(pat(service, target='1003'))
    row = next(r for r in snapshot(service)['rows'] if r['target'] == '1003')
    assert row['count'] == 2


def test_fading_slot_replaced_first(pats):
    service, now = pats
    for target in ('1002','1003','1004'):
        service.receive_pat(pat(service, target=target)); now[0] += .3
    now[0] = 101.1
    service.receive_pat(pat(service, target='1005'))
    assert [r['target'] for r in snapshot(service)['rows']] == ['1005','1003','1004']
    assert not snapshot(service)['hidden_active_ms']  # Old pair is fading, not active.


def test_vacancy_promotes_freshest_hidden_pair_without_resetting_count(pats):
    service, now = pats
    for target in ('1002','1003','1004','1005','1006'):
        service.receive_pat(pat(service, target=target))
        if target == '1003': service.receive_pat(pat(service, target=target))
        now[0] += .1
    assert [r['target'] for r in snapshot(service)['rows']] == ['1005','1006','1004']
    service.set_blocked('1005', True, '1001')
    view = snapshot(service)
    assert [r['target'] for r in view['rows']] == ['1006','1004','1003']
    assert view['rows'][-1]['count'] == 2
    assert len(view['hidden_active_ms']) == 1
    now[0] = 101.1
    service.set_blocked('1006', True, '1001')
    view = snapshot(service)
    assert [r['target'] for r in view['rows']] == ['1004','1003']
    assert not view['hidden_active_ms']  # An old hidden pair is never queued for replay.


def test_hidden_pair_reentry_after_one_second_starts_at_one(pats):
    service, now = pats
    service.receive_pat(pat(service))
    service.receive_pat(pat(service))
    now[0] += .1
    for target in ('1003','1004','1005'): service.receive_pat(pat(service, target=target))
    assert len(snapshot(service)['hidden_active_ms']) == 1
    now[0] = 101.0
    service.receive_pat(pat(service))
    assert next(row for row in snapshot(service)['rows'] if row['target'] == '1002')['count'] == 1


@pytest.mark.parametrize('changes', [dict(sender='9999'), dict(target='9999'), dict(target='1001'),
    dict(context={}), dict(observed=97), dict(observed=101), dict(observed=float('nan'))])
def test_invalid_or_stale_event_never_enters_tracker(pats, changes):
    service, _ = pats
    service.receive_pat(pat(service, **changes))
    assert not snapshot(service)['rows'] and not service.pats.pairs


@pytest.mark.parametrize('who', ['1002','1003'])
def test_both_endpoints_blocked_and_pre_unblock_events_discarded(pats, who):
    service, now = pats
    service.receive_pat(pat(service, '1002', '1003'))
    service.set_blocked(who, True, '1001')
    assert not snapshot(service)['rows']
    delayed = pat(service, '1002', '1003')
    now[0] += .2
    service.set_blocked(who, False, '1001')
    service.receive_pat(delayed)
    assert not snapshot(service)['rows']
    service.receive_pat(pat(service, '1002', '1003'))
    assert snapshot(service)['rows'][0]['count'] == 1


@pytest.mark.parametrize('changes', [dict(connected=False), dict(lobby_verified=False), dict(generation='new'),
                                    dict(lobby='new'), dict(account='1002')])
def test_connection_boundary_clears_without_replay(pats, changes):
    service, _ = pats
    old = pat(service)
    service.receive_pat(old)
    service.update(dict(service.state, **changes))
    assert not snapshot(service)['rows']
    service.receive_pat(old)
    assert not snapshot(service)['rows']


def test_setting_default_persistence_and_failed_write(pats, monkeypatch):
    service, now = pats
    assert service.pats_enabled
    service.receive_pat(pat(service))
    service.set_pats_enabled(False)
    delayed = pat(service)
    now[0] += .1
    service.set_pats_enabled(True)
    service.receive_pat(delayed)
    assert not snapshot(service)['rows']
    original = service.store.setting
    def fail(*args, **kwargs): raise sqlite3.OperationalError('fixture')
    monkeypatch.setattr(service.store, 'setting', fail)
    with pytest.raises(sqlite3.Error): service.set_pats_enabled(False)
    assert service.pats_enabled
    monkeypatch.setattr(service.store, 'setting', original)
    service.set_pats_enabled(False)
    assert not ChatService(service.store).pats_enabled


def test_fade_deadline_and_expiry(pats):
    service, now = pats
    service.receive_pat(pat(service))
    now[0] += 1
    assert snapshot(service)['rows'][0]['expires_in_ms'] == 1000
    now[0] += 1
    assert not snapshot(service)['rows']


def test_same_generation_reconnect_cannot_accept_delayed_pre_disconnect_pat(pats):
    service, now = pats
    delayed = pat(service)
    service.receive_pat(delayed)
    service.update(dict(service.state, connected=False))
    now[0] += .3
    service.update(dict(service.state, connected=True))
    service.receive_pat(delayed)
    assert not snapshot(service)['rows']
    service.receive_pat(pat(service))
    assert snapshot(service)['rows'][0]['count'] == 1


def test_unsupported_or_stale_connection_clears_pats(pats):
    service, now = pats
    service.receive_pat(pat(service))
    service.state['pats_supported'] = False
    service.receive_pat(pat(service))
    assert not snapshot(service)['rows']
    service.state['pats_supported'] = True
    service.receive_pat(pat(service))
    now[0] += 3
    service.receive_pat(pat(service))
    assert not snapshot(service)['rows']
