"""History windows, paging boundaries and privacy-safe new-message indicators."""
import time

import pytest

from bongo_chat.store import RETENTION_SECONDS
from bongo_chat.service import ChatService
from test_core import received, state, store


@pytest.fixture
def service(store):
    # History fixtures may take longer than the live connection's 2.5 s TTL
    # on CI disks. These tests control history, not the worker's heartbeat.
    result = ChatService(store, clock=lambda: 100.0)
    result.update(state())
    return result


@pytest.mark.parametrize('count, more', [(0, False), (99, False), (100, False), (101, True), (200, True)])
def test_history_end_uses_an_actual_older_row(service, count, more):
    for i in range(count):
        received(service, f'가상 기록 {i}')
    page = service.view()
    assert len(page['messages']) == min(100, count)
    assert page['has_more'] is more
    assert page['has_newer'] is False
    if count == 200:
        oldest = service.view(before=page['messages'][0]['seq'])
        assert len(oldest['messages']) == 100
        assert not oldest['has_more']


def test_anchored_window_keeps_old_rows_and_includes_later_messages(service):
    for i in range(300):
        received(service, f'가상 기록 {i}')
    initial = service.view()
    first = initial['messages'][0]['seq']
    for i in range(5):
        received(service, f'새 가상 기록 {i}')
    page = service.view(start=first, seen=initial['latest_seq'], limit=1000)
    assert [r['id'] for r in page['messages'][:100]] == [r['id'] for r in initial['messages']]
    assert len(page['messages']) == 105
    assert page['unseen'] and page['has_more'] and not page['has_newer']


def test_bounded_history_window_reports_forward_context(service):
    for i in range(1050):
        received(service, f'가상 기록 {i}')
    page = service.view(start=1, seen=1050, limit=1000)
    assert len(page['messages']) == 1000
    assert not page['has_more'] and page['has_newer'] and not page['unseen']
    assert page['latest_seq'] == 1050
    following = service.view(start=901, limit=1000)
    assert following['messages'][0]['seq'] == 901
    assert following['messages'][-1]['seq'] == 1050
    assert not following['has_newer']


def test_unseen_metadata_is_filtered_even_outside_history_window(service):
    for i in range(110):
        received(service, f'기존 가상 기록 {i}', sender='fixture-self')
    received(service, '숨김 검사 가상 기록')
    page = service.view(start=1, seen=110, limit=10)
    assert page['unseen'] and page['has_newer']
    assert page['unseen_seq'] == 111
    service.update(state(hidden={'fixture-peer': True}))
    hidden = service.view(start=1, seen=110, limit=10)
    assert not hidden['unseen'] and hidden['latest_seq'] == 110
    assert hidden['unseen_seq'] == 0
    service.update(state(hidden_ok=False))
    assert not service.view(start=1, seen=110)['unseen']


def test_metadata_excludes_other_rooms_accounts_and_expired_rows(service, store):
    received(service, '현재 방 가상 기록')
    seen = service.view()['latest_seq']
    service.update(state(lobby='fixture-room-b', generation='fixture-b'))
    received(service, '다른 방 가상 기록')
    service.update(state(account='fixture-other', generation='fixture-other'))
    received(service, '다른 계정 가상 기록')
    service.update(state())
    received(service, '만료될 가상 기록')
    store.db.execute('UPDATE messages SET received=? WHERE seq=(SELECT max(seq) FROM messages)',
                     (time.time() - RETENTION_SECONDS - 1,))
    page = service.view(seen=seen)
    assert not page['unseen'] and page['latest_seq'] == seen
    assert not page['has_more'] and not page['has_newer']


def test_unsaved_peer_indicator_respects_hidden_filter(service, store, monkeypatch):
    import sqlite3
    monkeypatch.setattr(store, 'add', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('full')))
    received(service, '미저장 가상 기록', id='fixture-unsaved')
    assert service.view()['volatile_peer_ids'] == ['fixture-unsaved']
    service.update(state(hidden={'fixture-peer': True}))
    assert service.view()['volatile_peer_ids'] == []


def test_legacy_meow_rows_do_not_affect_paging_or_unread_metadata(service, store):
    received(service, '이전 저장 형식의 가상 기록')
    store.db.execute("UPDATE messages SET body='Meow Meow'")
    page = service.view(start=0, seen=0)
    assert page['messages'] == []
    assert not page['has_more'] and not page['has_newer'] and not page['unseen']
    assert page['latest_seq'] == 0
