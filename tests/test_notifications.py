"""Product notification contracts; OS calls are fakes, messages are synthetic."""
import json
import queue
import sqlite3
from unittest.mock import Mock
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QApplication

from bongo_chat.desktop import Controller
from bongo_chat.notifications import Notifications, TOAST_INTERVAL
from bongo_chat.service import AcceptedIncoming, ChatService, NOTIFICATION_KEYS
from bongo_chat.store import Store
from bongo_chat.windows_notifications import APP_ID, TOAST_GROUP, TOAST_TAG, TOAST_XML
from test_core import state


class Toast:
    def __init__(self, result='sent'):
        self.shown = 0
        self.cleared = 0
        self.result = result

    def show(self):
        self.shown += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def clear(self):
        self.cleared += 1


class Attention:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def event(service, **changes):
    return dict(dict(type='message', id=str(uuid4()), text='합성 수신 문장', sender='fixture-peer',
                     context=service.context()), **changes)


@pytest.fixture
def rig(tmp_path):
    store = Store(tmp_path / 'history.sqlite3')
    now = [100.0]
    service = ChatService(store, clock=lambda: now[0])
    service.update(state())
    toast, attention = Toast(), Attention()
    active = [False]
    notifications = Notifications(service, toast, clock=lambda: now[0])
    notifications.bind(attention, lambda: active[0])
    yield service, notifications, toast, attention, now, active
    notifications.close()
    store.close()


@pytest.mark.parametrize('active', [True, False, 'minimized'])
@pytest.mark.parametrize('flash,toast_on', [(True, True), (True, False), (False, True), (False, False)])
def test_product_focus_and_independent_switches(rig, active, flash, toast_on):
    service, notifications, toast, attention, _, focus = rig
    focus[0] = active is True
    service.set_notification('notification_flash', flash)
    service.set_notification('notification_toast', toast_on)
    accepted = service.receive(event(service))
    assert isinstance(accepted, AcceptedIncoming)
    notifications.incoming(accepted)
    assert attention.started == int(flash and active is not True)
    assert toast.shown == int(toast_on and active is not True)
    assert focus[0] is (active is True)  # No focus mutation.


@pytest.mark.parametrize('case', ['self', 'echo', 'hidden', 'unknown', 'partial_unknown', 'old_context', 'stale', 'unverified', 'meow', 'no_session'])
def test_no_result_for_excluded_incoming(rig, case):
    service, notifications, toast, attention, now, _ = rig
    incoming = event(service)
    if case in ('self', 'echo'):
        incoming['sender'] = 'fixture-self'
        if case == 'echo':
            service.prepare(service.context(), incoming['text'])
    elif case == 'hidden':
        service.update(state(hidden={'fixture-peer': True}))
    elif case == 'unknown':
        service.update(state(privacy_ready=False))
    elif case == 'partial_unknown':
        service.update(state(hidden_ok=False, privacy_ready=True, hidden={}))
    elif case == 'old_context':
        incoming['context'] = dict(service.context(), generation='old')
    elif case == 'stale':
        now[0] += 2.5
    elif case == 'unverified':
        service.update(state(lobby_verified=False))
    elif case == 'meow':
        incoming['text'] = 'Meow Meow'
    elif case == 'no_session':
        service.session = ''
    assert service.receive(incoming) is None
    notifications.incoming(None)
    assert toast.shown == attention.started == 0


def test_partial_privacy_and_read_only_are_allowed(rig):
    service, notifications, toast, attention, _, _ = rig
    service.update(state(hidden_ok=False, privacy_ready=True, send_enabled=False))
    assert not service.can_send()
    notifications.incoming(service.receive(event(service)))
    assert toast.shown == attention.started == 1


def test_receipt_deduplication_and_same_text_are_separate(rig):
    service, _, _, _, _, _ = rig
    incoming = event(service)
    assert service.receive(incoming)
    assert service.receive(incoming) is None
    assert service.receive(event(service))
    assert len(service.view()['messages']) == 2


def test_storage_failure_is_one_new_volatile_message(rig, monkeypatch):
    service, notifications, toast, _, _, _ = rig
    incoming = event(service)
    monkeypatch.setattr(service.store, 'add', Mock(side_effect=sqlite3.OperationalError('synthetic')))
    notifications.incoming(service.receive(incoming))
    assert service.storage_error and incoming['id'] in service.volatile
    assert service.receive(incoming) is None
    assert toast.shown == 1
    for _ in range(4):
        assert service.view()['messages'][0]['unsaved']
    assert toast.shown == 1


def test_burst_is_bounded_with_no_deferred_delivery(rig):
    service, notifications, toast, attention, now, _ = rig
    for _ in range(260):
        notifications.incoming(service.receive(event(service)))
    assert len(service.view(limit=1000)['messages']) == 260
    assert toast.shown == attention.started == 1
    now[0] += TOAST_INTERVAL
    service.update(state())
    notifications.sync()
    assert toast.shown == 1  # No queued messages to flush.
    notifications.incoming(service.receive(event(service)))
    assert toast.shown == 2


@pytest.mark.parametrize('boundary', ['active', 'hidden', 'room', 'account', 'generation', 'stale', 'close'])
def test_boundaries_clear_owned_attention_and_never_replay(rig, boundary):
    service, notifications, toast, attention, now, active = rig
    receipt = service.receive(event(service))
    notifications.incoming(receipt)
    if boundary == 'active':
        active[0] = True
    elif boundary == 'hidden':
        service.update(state(hidden={'fixture-peer': True}))
    elif boundary in ('room', 'account', 'generation'):
        service.update(state(**{dict(room='lobby', account='account', generation='generation')[boundary]: 'changed'}))
    elif boundary == 'stale':
        now[0] += 2.5
    elif boundary == 'close':
        notifications.close()
    notifications.sync()
    assert attention.stopped == toast.cleared == 1
    for _ in range(5):
        notifications.sync()
    assert toast.shown == attention.started == 1
    assert toast.cleared == attention.stopped == 1


def test_off_cancels_each_channel_and_on_does_not_replay(rig):
    service, notifications, toast, attention, _, _ = rig
    notifications.incoming(service.receive(event(service)))
    for key in NOTIFICATION_KEYS:
        service.set_notification(key, False)
        notifications.settings_changed(key, False)
    assert toast.cleared == attention.stopped == 1
    for key in NOTIFICATION_KEYS:
        service.set_notification(key, True)
        notifications.settings_changed(key, True)
    notifications.sync()
    assert toast.shown == attention.started == 1
    notifications.incoming(service.receive(event(service)))
    assert toast.shown == attention.started == 2


@pytest.mark.parametrize('result', [False, None, OSError('synthetic OS failure'), RuntimeError('registration')])
def test_os_failure_isolated_and_retry_only_after_switch_cycle(rig, result):
    service, notifications, toast, attention, now, _ = rig
    toast.result = result
    for _ in range(3):
        now[0] += 10
        service.update(state())
        notifications.incoming(service.receive(event(service)))
    assert toast.shown == 1 and attention.started == 1
    assert not service.storage_error and service.can_send()
    assert len(service.view()['messages']) == 3
    notifications.settings_changed('notification_toast', False)
    notifications.settings_changed('notification_toast', True)
    toast.result = 'sent'
    notifications.incoming(service.receive(event(service)))
    assert toast.shown == 2


def test_disabled_os_is_rate_limited_without_overriding_os(rig):
    service, notifications, toast, _, now, _ = rig
    toast.result = 'disabled'
    notifications.incoming(service.receive(event(service)))
    notifications.incoming(service.receive(event(service)))
    assert toast.shown == 1 and notifications.snapshot()['toast'] == 'disabled'
    now[0] += 5
    service.update(state())
    notifications.incoming(service.receive(event(service)))
    assert toast.shown == 2 and not service.storage_error


def test_cleanup_failure_not_retried_each_poll(rig, monkeypatch):
    service, notifications, toast, _, _, active = rig
    notifications.incoming(service.receive(event(service)))
    cleanup = Mock(side_effect=OSError('synthetic'))
    monkeypatch.setattr(toast, 'clear', cleanup)
    active[0] = True
    for _ in range(10):
        notifications.sync()
    assert cleanup.call_count == 1
    assert notifications.snapshot()['toast'] == 'cleanup_failed'
    assert not service.storage_error


@pytest.mark.parametrize('flash,toast_on', [(True, True), (True, False), (False, True), (False, False)])
def test_committed_settings_survive_reopen_and_old_schema(tmp_path, flash, toast_on):
    path = tmp_path / 'history.sqlite3'
    with_store = Store(path)
    service = ChatService(with_store)
    assert service.notifications == dict(notification_flash=True, notification_toast=True)
    service.set_notification('notification_flash', flash)
    service.set_notification('notification_toast', toast_on)
    with_store.close()
    reopened = Store(path)
    try:
        assert ChatService(reopened).view()['notifications'] == dict(notification_flash=flash, notification_toast=toast_on)
        assert reopened.setting('theme', default='system') == 'system'
        assert reopened.db.execute('PRAGMA user_version').fetchone()[0] == 1
    finally:
        reopened.close()


@pytest.mark.parametrize('unreadable_key', sorted(NOTIFICATION_KEYS))
def test_startup_settings_read_failure_never_enables_saved_off(tmp_path, monkeypatch, unreadable_key):
    store = Store(tmp_path / 'history.sqlite3')
    try:
        store.setting('notification_flash', False)
        store.setting('notification_toast', False)
        original = store.setting

        def read(key, *args, **kwargs):
            if key == unreadable_key:
                raise sqlite3.OperationalError('synthetic read failure')
            return original(key, *args, **kwargs)

        monkeypatch.setattr(store, 'setting', read)
        service = ChatService(store)
        service.update(state())
        toast = Toast()
        notifications = Notifications(service, toast)
        attention = Attention()
        notifications.bind(attention, lambda: False)
        notifications.incoming(service.receive(event(service)))
        assert service.storage_error
        assert not any(service.notifications.values())
        assert toast.shown == attention.started == 0
        monkeypatch.setattr(store, 'setting', original)
        service.recover_storage()
        assert not service.storage_error
        assert service.notifications == dict(notification_flash=False, notification_toast=False)
        assert len(service.view()['messages']) == 1
    finally:
        store.close()


@pytest.fixture
def controller(tmp_path):
    app = QApplication.instance() or QApplication([])
    toast = Toast()
    value = Controller(tmp_path, offline=True, notification_backend=toast)
    value.timer.stop()
    value.service.update(state())
    value.notifications.bind(Attention(), lambda: False)
    yield value, toast
    value.close()
    app.processEvents()


@pytest.mark.parametrize('key,value', [('notification_flash', 'false'), ('notification_flash', 0),
    ('notification_toast', 1), ('notification_toast', None), ('notification_toast', []), ('unknown', True)])
def test_native_bridge_rejects_bad_setting(controller, key, value):
    value_controller, _ = controller
    result = json.loads(value_controller.request(json.dumps(dict(action='setting', key=key, value=value))))
    assert result['error'] == 'request_failed'
    assert all(value_controller.service.notifications.values())


def test_native_bridge_storage_failure_keeps_last_committed(controller, monkeypatch):
    value, _ = controller
    original = value.store.setting
    monkeypatch.setattr(value.store, 'setting', Mock(side_effect=sqlite3.OperationalError('synthetic')))
    result = json.loads(value.request(json.dumps(dict(action='setting', key='notification_toast', value=False))))
    assert result['error'] == 'storage_failed'
    assert value.service.view()['notifications']['notification_toast'] is True
    monkeypatch.setattr(value.store, 'setting', original)
    assert value.store.setting('notification_toast', default=True) is True


def deliver(controller, monkeypatch, events):
    pending = iter(events)

    def take():
        try:
            return next(pending)
        except StopIteration:
            raise queue.Empty from None

    monkeypatch.setattr(controller.events, 'get_nowait', take)
    controller.poll()


def test_actual_poll_and_reloads_only_notify_new_peer(controller, monkeypatch):
    value, toast = controller
    incoming = event(value.service)
    deliver(value, monkeypatch, [incoming, incoming, event(value.service, sender='fixture-self')])
    assert toast.shown == 1
    for args in [dict(action='view'), dict(action='view', query='합성'), dict(action='setting', key='theme', value='dark')]:
        assert 'error' not in json.loads(value.request(json.dumps(args)))
    value.poll()
    assert toast.shown == 1 and not value.service.storage_error


@pytest.mark.parametrize('boundary', ['close', 'restart'])
def test_final_poll_and_update_handoff_never_notify(controller, monkeypatch, boundary):
    value, toast = controller
    if boundary == 'restart':
        monkeypatch.setattr(value, 'can_restart', lambda: True)
        assert value.dispatch(dict(action='restart_update'))['ok']
        assert value.restarting
        deliver(value, monkeypatch, [event(value.service)])
    else:
        incoming = event(value.service)
        pending = iter([incoming])
        def take():
            try:
                return next(pending)
            except StopIteration:
                raise queue.Empty from None
        monkeypatch.setattr(value.events, 'get_nowait', take)
        value.close()
    assert toast.shown == 0 and value.notifications.closed


def test_os_payload_and_identity_have_no_user_content():
    assert APP_ID == 'BongoCatChat.Desktop'
    assert TOAST_GROUP == 'incoming' and TOAST_TAG == 'new-message'
    assert '새 메시지가 도착했어요.' in TOAST_XML
    for private in ('fixture', 'Steam', 'sender', 'lobby', 'launch=', 'arguments='):
        assert private not in TOAST_XML
