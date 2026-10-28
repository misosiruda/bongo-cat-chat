"""Real dev16 database code across a synthetic updater rollback; no real install."""
import importlib.util
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

import pytest

from bongo_chat import bootstrap
from bongo_chat.service import ChatService
from bongo_chat.store import Store
from bongo_chat.updates import installation
from test_core import received
from test_presence import SELF, PEER, NEW, snapshot
from test_updates import installed, signing, package, pending


@pytest.fixture
def legacy_store():
    path = Path(__file__).parent / 'fixtures/legacy_store_v1.py'
    spec = importlib.util.spec_from_file_location('bongo_chat.legacy_store_v1', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Store


def legacy_message(store, body):
    session = str(uuid4())
    store.session(session, SELF, 'fixture-room-a', '가상 로비')
    return store.add(dict(id=str(uuid4()), session=session, account=SELF, lobby='fixture-room-a',
                         sender=PEER, name='구름', body=body, received=time.time(), own=0,
                         status='received', echo=0))


def test_actual_schema1_rollback_after_candidate_opens_and_writes_database(installed, signing, monkeypatch, legacy_store):
    data = installed.parent / 'isolated-data'
    path = data / 'history.sqlite3'
    old = legacy_store(path)
    assert legacy_message(old, '업데이트 전 대화') == 1
    old.draft(SELF, 'fixture-room-a', '기존 초안')
    old.setting('language', 'en')
    original_columns = [row['name'] for row in old.db.execute('PRAGMA table_info(messages)')]
    old.close()
    pending(installed, package(signing))
    bootstrap.apply_pending(installed, signing[1], probe=lambda *args: None)
    assert installation(installed)['active'] == '0.2.0'
    launches = []

    def launch(command, **kwargs):
        launches.append(command[0])
        if len(launches) == 1:
            current = Store(path)
            try:
                service = ChatService(current, clock=lambda: 100)
                service.update(snapshot())
                service.update(snapshot((SELF, PEER, NEW)))
                service.update(snapshot())
            finally:
                current.close()
            return 1  # Fails inside the real bootstrap's 45-second window.
        restored = legacy_store(path)
        try:
            assert [row['body'] for row in restored.messages(SELF, 'fixture-room-a', {PEER, NEW})] == ['업데이트 전 대화']
            assert restored.draft(SELF, 'fixture-room-a') == '기존 초안'
            assert restored.setting('language') == 'en'
            assert [row['name'] for row in restored.db.execute('PRAGMA table_info(messages)')] == original_columns
            assert restored.db.execute('PRAGMA user_version').fetchone()[0] == 1
            assert legacy_message(restored, '롤백 후 대화') == 4
        finally:
            restored.close()
        return 0

    monkeypatch.setattr(bootstrap.subprocess, 'call', launch)
    assert bootstrap.run_app(installed, data, offline=True) == 1
    assert installation(installed)['active'] == '0.1.0'
    assert bootstrap.run_app(installed, data, offline=True) == 0
    assert '0.2.0' in launches[0] and '0.1.0' in launches[1]
    reopened = Store(path)
    try:
        service = ChatService(reopened, clock=lambda: 100)
        service.update(snapshot())
        service.update(snapshot((SELF, PEER, NEW)))
        rows = service.view()['messages']
        assert [row['seq'] for row in rows] == [1, 2, 3, 4, 5]
        assert [row['kind'] for row in rows] == ['chat', 'member_joined', 'member_left', 'chat', 'member_joined']
        assert service.view(seen=4)['unseen_seq'] == 0
    finally:
        reopened.close()


@pytest.mark.parametrize('lobby', [None, 'fixture-room-a'])
def test_legacy_history_delete_also_removes_extension_via_session_cascade(tmp_path, legacy_store, lobby):
    path = tmp_path / 'history.sqlite3'
    current = Store(path)
    service = ChatService(current, clock=lambda: 100)
    service.update(snapshot())
    received(service, '가상 대화')
    service.update(snapshot((SELF, PEER, NEW)))
    current.close()
    restored = legacy_store(path)
    try:
        restored.delete(SELF, lobby)
        assert restored.db.execute('SELECT count(*) FROM presence_events').fetchone()[0] == 0
        assert restored.messages(SELF, 'fixture-room-a', {PEER, NEW}) == []
    finally:
        restored.close()


def test_notice_sequence_reservation_rolls_back_with_failed_insert(tmp_path):
    store = Store(tmp_path / 'history.sqlite3')
    try:
        service = ChatService(store, clock=lambda: 100)
        service.update(snapshot())
        row = dict(id='fixture-notice', session=service.session, account=SELF, lobby='fixture-room-a',
                   sender=NEW, name='초코', received=time.time(), kind='invalid')
        with pytest.raises(sqlite3.IntegrityError):
            store.add(row)
        assert store.db.execute("SELECT 1 FROM sqlite_sequence WHERE name='messages'").fetchone() is None
        row['kind'] = 'member_joined'
        assert store.add(row) == store.add(row) == 1
        received(service, '안내 다음 대화')
        assert [message['seq'] for message in service.view()['messages']] == [1, 2]
        assert store.db.execute('SELECT count(*) FROM presence_events').fetchone()[0] == 1
    finally:
        store.close()
