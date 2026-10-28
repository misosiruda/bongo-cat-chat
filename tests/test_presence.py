"""Synthetic membership, privacy, history and migration checks. No Steam calls."""
import sqlite3
import time

import pytest

from bongo_chat.service import ChatService
from bongo_chat.store import RETENTION_SECONDS, SCHEMA_VERSION, Store
from bongo_chat.worker import LiveConnection
from test_core import FakeGame, FakeMemory, FakeSteam, received, state, store


SELF, PEER, NEW = 'fixture-self', 'fixture-peer', 'fixture-new'


def snapshot(member_ids=(SELF, PEER), **changes):
    return state(**dict(dict(members=list(member_ids), hidden={PEER: False, NEW: False},
                            profiles={uid: {'name': '새 고양이' if uid == NEW else '검증 고양이'} for uid in member_ids}), **changes))


def notices(service, **kwargs):
    return [row for row in service.view(**kwargs)['messages'] if row.get('kind') != 'chat']


@pytest.fixture
def tracked(store):
    service = ChatService(store, clock=lambda: 100)
    service.update(snapshot())
    return service


def test_first_sample_is_baseline_and_join_leave_are_once_in_chat_order(tracked):
    assert notices(tracked) == []
    received(tracked, '입장 전 대화')
    tracked.update(snapshot((SELF, PEER, NEW)))
    tracked.update(snapshot((SELF, PEER, NEW)))
    received(tracked, '퇴장 전 대화')
    tracked.update(snapshot())
    tracked.update(snapshot())
    rows = tracked.view()['messages']
    assert [row['kind'] for row in rows] == ['chat', 'member_joined', 'chat', 'member_left']
    assert [row['name'] for row in notices(tracked)] == ['새 고양이', '새 고양이']
    assert all(row['sender'] == NEW and not row['body'] and not row['own'] for row in notices(tracked))
    assert not tracked.store.db.execute('SELECT 1 FROM receipts WHERE message=?', (rows[1]['id'],)).fetchone()
    assert len(tracked.pending) == 0


@pytest.mark.parametrize('changes', [dict(generation='next'), dict(lobby='fixture-room-b'),
                                    dict(account='fixture-other', members=['fixture-other', NEW])])
def test_identity_change_starts_silent_baseline(tracked, changes):
    tracked.update(snapshot((SELF, NEW), **changes))
    assert notices(tracked) == []


@pytest.mark.parametrize('changes', [dict(connected=False), dict(lobby_verified=False),
                                    dict(privacy_ready=False), dict(members=None), dict(observed=90),
                                    dict(observed=101), dict(members=[NEW])])
def test_unverified_or_stale_sample_does_not_invent_activity(tracked, changes):
    tracked.update(snapshot((SELF, NEW), **changes))
    tracked.update(snapshot((SELF, NEW)))
    assert notices(tracked) == []


def test_heartbeat_gap_rebaselines_without_false_departures(store):
    clock = [100.0]
    service = ChatService(store, clock=lambda: clock[0])
    service.update(snapshot())
    clock[0] += 2.5
    service.update(snapshot((SELF, NEW)))
    assert notices(service) == []


def test_hide_unhide_profile_delay_and_rename_are_not_membership_events(tracked):
    tracked.update(snapshot(hidden={PEER: True}))
    tracked.update(snapshot(profiles={}))
    tracked.update(snapshot(profiles={PEER: {'name': '변경한 이름'}}))
    assert notices(tracked) == []
    tracked.update(snapshot((SELF,)))
    assert [(row['kind'], row['name']) for row in notices(tracked)] == [('member_left', '변경한 이름')]


def test_pending_new_join_waits_for_name_and_privacy_without_replaying_hidden_users(tracked):
    tracked.update(snapshot((SELF, PEER, NEW), hidden={PEER: False}, profiles={}))
    assert notices(tracked) == []
    tracked.update(snapshot((SELF, PEER, NEW)))
    assert [row['kind'] for row in notices(tracked)] == ['member_joined']
    tracked.update(snapshot(hidden={PEER: False, NEW: True}))
    tracked.update(snapshot((SELF, PEER, NEW), hidden={PEER: False, NEW: True}))
    tracked.update(snapshot((SELF, PEER, NEW)))
    # Re-showing a hidden peer is not a new join. Existing history may reappear.
    assert len(notices(tracked)) == 1


def test_pending_join_expires_and_quick_unknown_visit_is_not_replayed(store):
    clock = [100.0]
    service = ChatService(store, clock=lambda: clock[0])
    service.update(snapshot())
    service.update(snapshot((SELF, PEER, NEW), profiles={}))
    for _ in range(5):
        clock[0] += 1
        service.update(snapshot((SELF, PEER, NEW), profiles={}))
    service.update(snapshot((SELF, PEER, NEW)))
    assert notices(service) == []
    service.update(snapshot())
    count = len(notices(service))
    service.update(snapshot((SELF, PEER, NEW), hidden={PEER: False}, profiles={}))
    service.update(snapshot())
    assert len(notices(service)) == count


@pytest.mark.parametrize('hidden', [{PEER: True}, {}])
def test_departure_requires_current_privacy_allowance(tracked, hidden):
    tracked.update(snapshot((SELF,), hidden=hidden))
    assert notices(tracked) == []
    assert tracked.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_notice_history_obeys_privacy_and_does_not_count_as_unread_or_search(tracked):
    tracked.update(snapshot((SELF, PEER, NEW), send_enabled=False))
    view = tracked.view(seen=0)
    assert len(view['messages']) == 1 and view['latest_seq'] > 0
    assert not view['unseen'] and not view['unseen_seq'] and not view['volatile_peer_ids']
    assert notices(tracked, query='새 고양이') == []
    received(tracked, '안내 이후 대화')
    assert tracked.view(seen=0)['unseen']
    tracked.update(snapshot((SELF, PEER, NEW), hidden={PEER: False, NEW: True}))
    assert notices(tracked) == []
    tracked.update(snapshot((SELF, PEER, NEW)))
    assert len(notices(tracked)) == 1


def test_failed_notice_save_is_visible_unsaved_without_unread_and_can_be_deleted(tracked, monkeypatch):
    original = tracked.store.add
    monkeypatch.setattr(tracked.store, 'add', lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError('fixture')))
    tracked.update(snapshot((SELF, PEER, NEW)))
    view = tracked.view(seen=0)
    assert view['messages'][0]['unsaved'] and view['storage_error']
    assert not view['volatile_peer_ids'] and not view['unseen']
    assert not tracked.view(query='새')['messages']
    monkeypatch.setattr(tracked.store, 'add', original)
    tracked.recover_storage()
    received(tracked, '복구 이후 대화')
    assert [row.get('kind', 'chat') for row in tracked.view()['messages']] == ['member_joined', 'chat']
    tracked.forget(SELF, 'fixture-room-a')
    assert tracked.view()['messages'] == []


def test_rejoin_same_name_and_multiple_users_remain_distinct(tracked):
    tracked.update(snapshot((SELF, PEER, NEW), profiles={PEER: {'name': '같은 이름'}, NEW: {'name': '같은 이름'}}))
    tracked.update(snapshot((SELF,)))
    tracked.update(snapshot((SELF, PEER, NEW)))
    assert [row['kind'] for row in notices(tracked)] == [
        'member_joined', 'member_left', 'member_left', 'member_joined', 'member_joined']
    assert {row['sender'] for row in notices(tracked)} == {PEER, NEW}


def test_notice_history_reopens_pages_prunes_and_deletes_like_chat(tmp_path):
    path = tmp_path / 'history.sqlite3'
    with_store = Store(path)
    service = ChatService(with_store, clock=lambda: 100)
    service.update(snapshot())
    for _ in range(3):
        service.update(snapshot((SELF, PEER, NEW)))
        service.update(snapshot())
    with_store.close()
    reopened = Store(path)
    try:
        service = ChatService(reopened, clock=lambda: 100)
        service.update(snapshot())
        page = service.view(limit=2)
        assert len(page['messages']) == 2 and page['has_more']
        older = service.view(before=page['messages'][0]['seq'], limit=10)
        assert len(older['messages']) == 4 and older['has_newer']
        assert len(notices(service)) == 6  # Reopening does not synthesize joins.
        reopened.db.execute('UPDATE presence_events SET received=? WHERE seq=?',
                            (time.time() - RETENTION_SECONDS - 1, older['messages'][0]['seq']))
        reopened.db.commit()
        assert len(notices(service)) == 5
        reopened.prune()
        assert reopened.db.execute('SELECT count(*) FROM presence_events').fetchone()[0] == 5
        service.forget(SELF)
        assert service.view()['messages'] == []
    finally:
        reopened.close()


def test_v1_extension_preserves_chat_receipts_draft_setting_and_sequence(tmp_path):
    path = tmp_path / 'v1.sqlite3'
    original = Store(path)
    service = ChatService(original, clock=lambda: 100)
    service.update(snapshot())
    received(service, '이전 버전 대화', id='fixture-receipt')
    original.draft(SELF, 'fixture-room-a', '작성 중')
    original.setting('language', 'en')
    original.db.execute('DROP TABLE presence_events')
    original.db.execute('PRAGMA user_version=1')
    original.close()
    for _ in range(2):
        migrated = Store(path)
        try:
            rows = migrated.messages(SELF, 'fixture-room-a', {PEER})
            assert len(rows) == 1 and rows[0]['kind'] == 'chat' and rows[0]['seq'] == 1
            assert rows[0]['body'] == '이전 버전 대화' and migrated.seen('fixture-receipt')
            assert migrated.draft(SELF, 'fixture-room-a') == '작성 중'
            assert migrated.setting('language') == 'en'
            assert migrated.db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        finally:
            migrated.close()


def test_worker_membership_sample_is_separate_from_profile_cache(monkeypatch):
    steam = FakeSteam()
    members = {SELF, PEER}
    monkeypatch.setattr(steam, 'members', lambda lobby: set(members))
    live = LiveConnection(FakeGame(), FakeMemory(), steam, read_only=True)
    initial, _, _ = live.snapshot()
    members.add(NEW)
    changed, _, _ = live.snapshot()
    assert set(changed['members']) == {SELF, PEER, NEW}
    assert NEW not in changed['profiles']  # Unknown privacy/profile is not absence.
    assert initial['generation'] == changed['generation']
    assert not changed['send_enabled'] and not steam.sent
