"""Account-local Steam ID blocking with synthetic IDs; no Steam or game calls."""
import json
import sqlite3
import time
from uuid import uuid4

import pytest

from bongo_chat.service import ChatService
from bongo_chat.store import Store, RETENTION_SECONDS
from test_profiles import SELF, PEER, SECOND, profile_state
from test_profile_desktop import profile_controller
from test_desktop import js, wait_until
from bongo_chat.desktop import window
from PySide6.QtCore import QTimer


@pytest.fixture
def blocked_service(tmp_path):
    store = Store(tmp_path / 'blocking.sqlite3')
    service = ChatService(store, clock=lambda: 100.0)
    service.update(profile_state(send_enabled=True))
    yield service
    store.close()


def incoming(service, sender=PEER, **changes):
    return service.receive(dict(dict(id=str(uuid4()), sender=sender, text='합성 차단 시험',
                                     context=service.context(), observed=service.clock()), **changes))


def test_block_filters_history_search_unread_profiles_notifications_and_new_storage(blocked_service):
    service = blocked_service
    receipt = incoming(service)
    incoming(service, SECOND)
    service.set_blocked(PEER, True, SELF)
    assert not receipt.current(service)
    view = service.view(query='차단', seen=0)
    assert [r['sender'] for r in view['messages']] == [SECOND]
    assert view['unseen_seq'] == 2 and PEER not in view['profiles']
    assert view['participants'][PEER]['blocked']
    assert view['profile_targets'] == [SECOND]
    assert incoming(service) is None
    assert service.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 2
    service.set_blocked(PEER, False, SELF)
    assert len(service.view()['messages']) == 2
    assert incoming(service) is not None


def test_cross_lobby_restart_account_isolation_and_history_deletion(blocked_service):
    service = blocked_service
    incoming(service)
    service.set_blocked(PEER, True, SELF)
    service.update(profile_state(lobby='second-room', generation='second'))
    assert incoming(service) is None
    assert not service.view(lobby='fixture-room-a')['messages']
    service.forget(SELF)
    service.store.prune()
    assert PEER in service.store.blocked_users(SELF)
    reopened = ChatService(service.store, clock=lambda: 100)
    reopened.update(profile_state(lobby='third-room', generation='third'))
    assert incoming(reopened) is None
    reopened.update(profile_state(account=SECOND, members=[SECOND, PEER]))
    assert incoming(reopened) is not None
    reopened.update(profile_state())
    assert incoming(reopened) is None


def test_persistence_reopens_sqlite_and_does_not_expire_with_history(tmp_path):
    path = tmp_path / 'old-v1.sqlite3'
    store = Store(path)
    store.db.execute('DROP TABLE blocked_users')  # Existing dev16 schema.
    store.close()
    store = Store(path)
    service = ChatService(store, clock=lambda: 100)
    service.update(profile_state())
    incoming(service)
    service.set_blocked(PEER, True, SELF)
    store.db.execute('UPDATE messages SET received=?', (time.time() - RETENTION_SECONDS - 1,))
    store.db.commit()
    store.prune()
    store.close()
    with_store = Store(path)
    try:
        restored = ChatService(with_store, clock=lambda: 100)
        restored.update(profile_state())
        assert restored.blocked == {PEER: '동일 이름'}
        assert incoming(restored) is None
        assert with_store.db.execute('PRAGMA user_version').fetchone()[0] == 1
    finally:
        with_store.close()


def test_history_from_departed_peer_is_visible_in_another_lobby(blocked_service):
    service = blocked_service
    incoming(service)
    service.update(profile_state(lobby='new-room', generation='new', members=[SELF, SECOND]))
    assert len(service.view(lobby='fixture-room-a')['messages']) == 1
    assert incoming(service) is None  # Nonmembers cannot inject new messages.
    service.set_blocked(PEER, True, SELF)
    assert not service.view(lobby='fixture-room-a')['messages']


@pytest.mark.parametrize('uid', [SELF, 76561190000000001, None, True, '01', '0', '-1',
                               '18446744073709551616', '1e17', '１', PEER + ' '])
def test_invalid_and_self_targets_do_not_change_list(blocked_service, uid):
    with pytest.raises(ValueError):
        blocked_service.set_blocked(uid, True, SELF)
    assert blocked_service.store.blocked_users(SELF) == {}


@pytest.mark.parametrize('value,owner', [(1, SELF), ('true', SELF), (None, SELF), (True, SECOND), (True, '')])
def test_invalid_boolean_and_old_account_rejected(blocked_service, value, owner):
    with pytest.raises(ValueError, match='block_unavailable'):
        blocked_service.set_blocked(PEER, value, owner)


def test_write_failure_retains_committed_policy(blocked_service, monkeypatch):
    service = blocked_service
    service.set_blocked(PEER, True, SELF)
    def fail(*args): raise sqlite3.OperationalError('synthetic failure')
    monkeypatch.setattr(service.store, 'set_blocked', fail)
    for uid, blocked in [(PEER, False), (SECOND, True)]:
        with pytest.raises(sqlite3.Error): service.set_blocked(uid, blocked, SELF)
    assert service.blocked == service.store.blocked_users(SELF) == {PEER: '동일 이름'}
    assert incoming(service) is None and incoming(service, SECOND)


def test_block_read_failure_fails_closed_and_refresh_restores(blocked_service, monkeypatch):
    service = blocked_service
    service.set_blocked(PEER, True, SELF)
    original = service.store.blocked_users
    def fail(*args): raise sqlite3.OperationalError('synthetic read failure')
    monkeypatch.setattr(service.store, 'blocked_users', fail)
    service.update(profile_state(account=SECOND))
    assert service.blocked is None and service.storage_error
    assert incoming(service) is None and not service.view()['blocks_ready']
    with pytest.raises(ValueError): service.set_blocked(PEER, False, SECOND)
    monkeypatch.setattr(service.store, 'blocked_users', original)
    service.update(profile_state())
    service.recover_storage()
    assert not service.storage_error and PEER in service.blocked


def test_delayed_events_cannot_reappear_after_unblock(blocked_service):
    service = blocked_service
    service.clock = lambda: 101
    service.set_blocked(PEER, True, SELF)
    service.clock = lambda: 102
    service.set_blocked(PEER, False, SELF)
    service.update(dict(service.state))
    assert incoming(service, observed=101.5) is None
    assert incoming(service, observed=102.1) is not None


def test_blocking_cancels_pending_join_before_unblocking(blocked_service):
    service = blocked_service
    service.update(profile_state(generation='presence', members=[SELF, SECOND]))
    service.update(profile_state(generation='presence', profiles={}))
    assert PEER in service.presence.pending
    service.set_blocked(PEER, True, SELF)
    service.set_blocked(PEER, False, SELF)
    service.update(profile_state(generation='presence'))
    assert not service.store.db.execute('SELECT 1 FROM presence_events').fetchone()


def test_delayed_membership_observed_while_blocked_does_not_replay(blocked_service):
    service = blocked_service
    service.update(profile_state(generation='presence', members=[SELF, SECOND]))
    service.clock = lambda: 101
    service.set_blocked(PEER, True, SELF)
    service.clock = lambda: 102
    service.set_blocked(PEER, False, SELF)
    service.update(profile_state(generation='presence', observed=101.5))
    service.update(profile_state(generation='presence', observed=102))
    assert not service.store.db.execute('SELECT 1 FROM presence_events').fetchone()


def test_departure_history_obeys_account_blocks_after_lobby_move(blocked_service):
    service = blocked_service
    service.update(profile_state(members=[SELF, SECOND]))
    assert [r['kind'] for r in service.view()['messages']] == ['member_left']
    service.update(profile_state(lobby='next-room', generation='next'))
    service.set_blocked(PEER, True, SELF)
    assert not service.view(lobby='fixture-room-a')['messages']
    service.set_blocked(PEER, False, SELF)
    assert [r['kind'] for r in service.view(lobby='fixture-room-a')['messages']] == ['member_left']


def test_real_bridge_block_controls_keep_draft_and_survive_reload(profile_controller):
    app, controller, _ = profile_controller
    service = controller.service
    incoming(service)
    view = window(controller); view.show(); page = view.page()
    heartbeat = QTimer(); heartbeat.timeout.connect(lambda: service.update(dict(service.state))); heartbeat.start(300)
    try:
        wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
        js(app, page, "document.querySelector('#message-input').value='차단 중 초안';document.querySelector('#message-input').dispatchEvent(new Event('input'));document.querySelector('#participants-button').click()")
        js(app, page, f"document.querySelector('#participant-more-{PEER}').click();document.querySelector('[data-profile-key=block-{PEER}]').focus();document.querySelector('[data-profile-key=block-{PEER}]').click()")
        wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 0)
        wait_until(app, lambda: js(app, page, f"document.querySelector('[data-profile-key=block-{PEER}]').textContent") == '차단 해제')
        assert PEER in controller.store.blocked_users(SELF)
        assert js(app, page, "document.querySelector('#message-input').value") == '차단 중 초안'
        wait_until(app, lambda: js(app, page, "!document.querySelector('#blocked-list button').disabled"))
        loaded = []
        page.loadFinished.connect(loaded.append)
        page.triggerAction(page.WebAction.Reload)
        wait_until(app, lambda: loaded == [True])
        wait_until(app, lambda: js(app, page, "document.querySelectorAll('#blocked-list li').length") == 1)
        wait_until(app, lambda: js(app, page, "!document.querySelector('#blocked-list button').disabled"))
        js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#blocked-list button').click()")
        wait_until(app, lambda: controller.store.blocked_users(SELF) == {})
        wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
        assert controller.store.blocked_users(SELF) == {}
        assert not page.console_errors
        assert controller.worker is None
    finally:
        heartbeat.stop(); view.close(); view.deleteLater(); app.processEvents()
