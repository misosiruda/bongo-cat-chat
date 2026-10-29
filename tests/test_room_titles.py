"""Room metadata regression checks with synthetic Steam and isolated SQLite."""
import sqlite3
from unittest.mock import Mock

import pytest

from bongo_chat.service import ChatService
from bongo_chat.store import Store
from bongo_chat.worker import LiveConnection
from test_core import FakeGame, FakeMemory, FakeSteam, received, state, store, service


def room_name(service, lobby='fixture-room-a'):
    return next(row['name'] for row in service.view()['rooms'] if row['lobby'] == lobby)


def test_worker_rename_updates_saved_title_without_new_segment_or_chat(store):
    steam = FakeSteam()
    steam.room_name = Mock(return_value='처음 방')
    live = LiveConnection(FakeGame(), FakeMemory(), steam)
    service = ChatService(store, clock=lambda: 100.0)
    first, _, _ = live.snapshot()
    service.update(first)
    context, session = service.context(), service.session
    store.draft(context['account'], context['lobby'], '보존할 초안')
    received(service, '검색할 기존 대화')
    command = service.prepare(context, '전송 대기 문장')
    pending = [dict(row) for row in service.pending]
    rows_before = [dict(row) for row in store.db.execute('SELECT * FROM messages')]
    session_before = dict(store.db.execute('SELECT * FROM sessions').fetchone())
    for title in ['두 번째 방', '세 번째 방']:
        steam.room_name.return_value = title
        current, _, changed = live.snapshot()
        service.update(current)
        assert not changed and current['generation'] == first['generation']
        assert room_name(service) == title
        assert store.rooms(context['account'])[0]['name'] == title
    assert service.context() == context and service.session == session
    assert list(service.pending) == pending and pending[0]['id'] == command['id']
    assert service.view()['draft'] == '보존할 초안'
    assert len(service.view(query='검색할')['messages']) == 1
    assert [dict(row) for row in store.db.execute('SELECT * FROM messages')] == rows_before
    assert store.db.execute('SELECT count(*) FROM presence_events').fetchone()[0] == 0
    session_after = dict(store.db.execute('SELECT * FROM sessions').fetchone())
    assert {k: v for k, v in session_after.items() if k != 'name'} == {
        k: v for k, v in session_before.items() if k != 'name'}
    assert store.rooms(context['account'])[0]['segments'] == 1
    assert not steam.sent


def test_unchanged_title_performs_no_database_writes(service):
    service.update(state(name='갱신한 방'))
    writes_before = service.store.db.total_changes
    for _ in range(20):
        service.update(state(name='갱신한 방'))
    assert service.store.db.total_changes == writes_before
    assert room_name(service) == '갱신한 방'


@pytest.mark.parametrize('missing', ['', None, '   ', 123])
def test_unknown_title_keeps_last_known_name_only_within_same_context(service, missing):
    service.update(state(name='확인한 제목'))
    writes_before = service.store.db.total_changes
    service.update(state(name=missing))
    assert service.state['name'] == '확인한 제목'
    assert room_name(service) == '확인한 제목'
    assert service.store.db.total_changes == writes_before
    service.update(state(lobby='fixture-room-b', generation='fixture-segment-b', name=missing))
    assert service.state['name'] == ''
    assert room_name(service, 'fixture-room-b') == ''
    assert room_name(service) == '확인한 제목'


def test_initial_empty_title_is_filled_without_reconnection(store):
    service = ChatService(store, clock=lambda: 100.0)
    service.update(state(name=''))
    session = service.session
    service.update(state(name='늦게 도착한 방 제목'))
    assert room_name(service) == '늦게 도착한 방 제목'
    assert store.rooms('fixture-self')[0]['name'] == '늦게 도착한 방 제목'
    assert service.session == session and store.rooms('fixture-self')[0]['segments'] == 1


def test_rename_is_scoped_to_active_session_account_and_lobby(service):
    store = service.store
    first_session = service.session
    service.update(state(lobby='fixture-room-b', generation='fixture-segment-b', name='다른 방'))
    second_session = service.session
    service.update(state(generation='returned', name='다시 방문한 방'))
    current = service.session
    service.update(state(generation='returned', name='현재 제목'))
    store.session('other-account-session', 'fixture-other', 'fixture-room-a', '다른 계정 제목')
    # Late metadata for an ended segment, and mismatched account/lobby targets.
    store.rename_session(first_session, 'fixture-self', 'fixture-room-a', '늦은 이전 제목')
    store.rename_session(current, 'fixture-other', 'fixture-room-a', '잘못된 계정')
    store.rename_session(current, 'fixture-self', 'fixture-room-b', '잘못된 로비')
    rows = {r['id']: r['name'] for r in store.db.execute('SELECT id,name FROM sessions')}
    assert rows == {first_session: '테스트 로비', second_session: '다른 방',
                    current: '현재 제목', 'other-account-session': '다른 계정 제목'}
    archived = service.view(lobby='fixture-room-b')
    assert archived['lobby'] == 'fixture-room-b' and not archived['can_send']
    assert {r['lobby']: r['name'] for r in archived['rooms']} == {
        'fixture-room-a': '현재 제목', 'fixture-room-b': '다른 방'}


def test_new_title_survives_close_and_database_reopen(tmp_path):
    path = tmp_path / 'history.sqlite3'
    store = Store(path)
    service = ChatService(store, clock=lambda: 100.0)
    service.update(state())
    service.update(state(name="한글 <b>제목</b> ' OR 1=1"))
    service.end('test_closed')
    store.close()
    reopened = Store(path)
    try:
        assert reopened.rooms('fixture-self')[0]['name'] == "한글 <b>제목</b> ' OR 1=1"
        assert reopened.rooms('fixture-self')[0]['segments'] == 1
        assert reopened.db.execute('PRAGMA user_version').fetchone()[0] == 1
    finally:
        reopened.close()


@pytest.mark.parametrize('error', [sqlite3.OperationalError, OSError])
def test_write_failure_keeps_live_title_and_recovers_latest_without_busy_retry(service, monkeypatch, error):
    store = service.store
    rename = store.rename_session
    failed = Mock(side_effect=error('synthetic write failure'))
    monkeypatch.setattr(store, 'rename_session', failed)
    service.update(state(name='저장 실패한 제목'))
    assert room_name(service) == '저장 실패한 제목'
    assert store.rooms('fixture-self')[0]['name'] == '테스트 로비'
    assert service.view()['storage_error'] and not service.view()['can_send']
    for _ in range(20):
        service.update(state(name='가장 최근 제목'))
    assert failed.call_count == 1
    assert room_name(service) == '가장 최근 제목'
    with pytest.raises(error):
        service.recover_storage()
    assert service.storage_error
    monkeypatch.setattr(store, 'rename_session', rename)
    service.recover_storage()
    assert not service.storage_error and service.can_send()
    assert store.rooms('fixture-self')[0]['name'] == '가장 최근 제목'
    assert store.rooms('fixture-self')[0]['segments'] == 1


def test_title_overlay_does_not_apply_to_stale_or_other_account_rooms(store, monkeypatch):
    clock = [100.0]
    service = ChatService(store, clock=lambda: clock[0])
    service.update(state())
    monkeypatch.setattr(store, 'rename_session', Mock(side_effect=sqlite3.OperationalError('synthetic')))
    service.update(state(name='메모리에만 있는 제목'))
    assert room_name(service) == '메모리에만 있는 제목'
    clock[0] += 3
    assert room_name(service) == '테스트 로비'
    service.update(state(account='fixture-other', members=['fixture-other'], generation='other', name='다른 계정'))
    assert room_name(service) == '다른 계정'
    assert store.rooms('fixture-self')[0]['name'] == '테스트 로비'


def test_recovery_after_initial_insert_failure_saves_latest_title(store, monkeypatch):
    service = ChatService(store, clock=lambda: 100.0)
    create = store.session
    monkeypatch.setattr(store, 'session', Mock(side_effect=sqlite3.OperationalError('synthetic')))
    service.update(state(name='처음 제목'))
    service.update(state(name='복구 시 제목'))
    assert service.storage_error
    monkeypatch.setattr(store, 'session', create)
    service.recover_storage()
    assert room_name(service) == '복구 시 제목'
    assert store.rooms('fixture-self')[0]['name'] == '복구 시 제목'
    assert not service.storage_error


def test_read_only_title_sync_and_disconnected_sample_preserves_known_title(service):
    service.update(state(name='읽기 전용 제목', send_enabled=False))
    assert room_name(service) == '읽기 전용 제목' and not service.can_send()
    service.update(state(name='연결 미확인 제목', connected=False, send_enabled=False))
    assert service.state['name'] == '읽기 전용 제목'
    assert service.store.rooms('fixture-self')[0]['name'] == '읽기 전용 제목'


def test_failed_old_room_title_is_not_saved_to_new_room_on_recovery(service, monkeypatch):
    store = service.store
    rename = store.rename_session
    monkeypatch.setattr(store, 'rename_session', Mock(side_effect=sqlite3.OperationalError('synthetic')))
    service.update(state(name='이전 방 미저장 제목'))
    service.update(state(lobby='fixture-room-b', generation='next', name='새 방 제목'))
    monkeypatch.setattr(store, 'rename_session', rename)
    service.recover_storage()
    assert {r['lobby']: r['name'] for r in store.rooms('fixture-self')} == {
        'fixture-room-a': '테스트 로비', 'fixture-room-b': '새 방 제목'}
