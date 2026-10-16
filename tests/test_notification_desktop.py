"""Actual product HTML, QWebChannel, and SQLite. No OS notifications or Steam."""
import sqlite3

import pytest

from test_desktop import qt_chat, js, wait_until


@pytest.mark.parametrize('key,control', [('notification_flash', 'notification-flash'), ('notification_toast', 'notification-toast')])
def test_product_switch_roundtrip_and_preserves_editor(qt_chat, key, control):
    app, controller, page = qt_chat
    js(app, page, "document.querySelector('#message-input').value='알림 설정 중 초안';document.querySelector('#message-input').dispatchEvent(new Event('input'));document.querySelector('#settings-button').click()")
    wait_until(app, lambda: controller.store.draft('fixture-self', 'fixture-room-a') == '알림 설정 중 초안')
    assert js(app, page, f"document.querySelector('#{control}').checked") is True
    js(app, page, f"document.querySelector('#{control}').focus();document.querySelector('#{control}').click()")
    wait_until(app, lambda: controller.store.setting(key) is False)
    wait_until(app, lambda: js(app, page, f"!document.querySelector('#{control}').checked && !document.querySelector('#{control}').disabled"))
    assert controller.service.view()['notifications'][key] is False
    assert js(app, page, "document.querySelector('#message-input').value") == '알림 설정 중 초안'
    assert js(app, page, "document.querySelector('#settings-dialog').open")
    other = 'notification-toast' if key == 'notification_flash' else 'notification-flash'
    assert js(app, page, f"document.querySelector('#{other}').checked") is True
    page.triggerAction(page.WebAction.Reload)
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
    wait_until(app, lambda: js(app, page, f"document.querySelector('#{control}').checked") is False)
    assert js(app, page, "document.querySelector('#message-input').value") == '알림 설정 중 초안'


def test_product_setting_failure_restores_committed_ui(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    original = controller.store.setting

    def failing(key, value=None, default=None):
        if key.startswith('notification_') and value is not None:
            raise sqlite3.OperationalError('synthetic write failure')
        return original(key, value, default)

    monkeypatch.setattr(controller.store, 'setting', failing)
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#notification-toast').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#notification-save-status').textContent.includes('이전 값')"))
    assert js(app, page, "document.querySelector('#notification-toast').checked && !document.querySelector('#notification-toast').disabled")
    assert controller.service.notifications['notification_toast'] is True
    assert original('notification_toast', default=True) is True
    assert js(app, page, "document.querySelector('#settings-dialog').open")


def test_native_os_failure_status_is_separate_from_storage(qt_chat):
    app, controller, page = qt_chat
    controller.notifications.toast_status = 'unavailable'
    js(app, page, "document.querySelector('#settings-button').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#notification-status').textContent.includes('사용할 수 없어요')"))
    assert not controller.service.storage_error
    js(app, page, "document.querySelector('#message-input').value='오류 뒤에도 보낼 문장';document.querySelector('#message-input').dispatchEvent(new Event('input'))")
    assert js(app, page, "document.querySelector('#send-button').disabled") is False
