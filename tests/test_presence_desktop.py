"""Actual Qt renderer/bridge with synthetic membership and an isolated database."""
from unittest.mock import Mock

from test_desktop import js, qt_chat, seed_history, wait_until
from test_localization import choose_language
from test_presence import SELF, PEER, NEW, snapshot, persisted_block
from test_scroll_desktop import scroll_anchor


def test_membership_notice_renders_safely_without_message_or_os_alert(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    controller.service.update(snapshot())
    incoming = Mock()
    monkeypatch.setattr(controller.notifications, 'incoming', incoming)
    name = '<img src=x onerror=alert(1)> 가상 고양이'
    controller.events.put(dict(snapshot((SELF, PEER, NEW), profiles={NEW: {'name': name}}), type='state'))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 1)
    assert js(app, page, "document.querySelector('.presence-text').textContent") == f'{name}님이 들어왔습니다.'
    assert js(app, page, "document.querySelectorAll('.presence-notice img,.presence-notice button,.presence-notice .message-bubble').length") == 0
    assert js(app, page, "document.querySelector('.presence-notice').getAttribute('role')") == 'listitem'
    assert js(app, page, "document.querySelector('.presence-time').dateTime")
    assert controller.worker is None and controller.commands.empty()
    incoming.assert_not_called()
    controller.events.put(dict(snapshot(), type='state'))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 2)
    assert js(app, page, "document.querySelector('.presence-notice:last-child .presence-text').textContent") == f'{name}님이 나갔습니다.'
    incoming.assert_not_called()
    js(app, page, "document.querySelector('#settings-button').click()")
    choose_language(app, page, 'en')
    assert js(app, page, "document.querySelector('.presence-text').textContent") == f'{name} joined the lobby.'
    assert js(app, page, "document.querySelector('.presence-notice:last-child .presence-text').textContent") == f'{name} left the lobby.'
    page.triggerAction(page.WebAction.Reload)
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 2)


def test_notices_preserve_reading_position_draft_search_and_block_policy(qt_chat):
    app, controller, page = qt_chat
    service = controller.service
    service.update(snapshot())
    seed_history(service, (f'가상 읽기 기록 {i}' for i in range(110)))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 111)
    js(app, page, "document.querySelector('#message-input').value='작성 중 초안';document.querySelector('#message-input').dispatchEvent(new Event('input'));const s=document.querySelector('#message-scroll');s.scrollTop=(s.scrollHeight-s.clientHeight)/2")
    before = scroll_anchor(app, page)
    service.update(snapshot((SELF, PEER, NEW)))
    service.update(snapshot())
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 2)
    after = scroll_anchor(app, page)
    assert after['id'] == before['id'] and abs(after['offset'] - before['offset']) < 2
    assert js(app, page, "document.querySelector('#new-messages').hidden")
    assert js(app, page, "document.querySelector('#message-input').value") == '작성 중 초안'
    js(app, page, "document.querySelector('#message-search').value='가상 읽기 기록';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 0)
    assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 100
    js(app, page, "document.querySelector('#clear-search').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 2)
    persisted_block(service, NEW, True)
    service.update(snapshot())
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 0)
    persisted_block(service, NEW, False)
    service.update(snapshot())
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.presence-notice').length") == 2)
