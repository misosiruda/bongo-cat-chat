"""Real Qt renderer/QWebChannel regression checks; no Steam or game startup."""
import sqlite3
from unittest.mock import Mock

from test_core import state
from test_desktop import js, qt_chat, seed_history, wait_until
from test_scroll_desktop import scroll_anchor


def title_is(app, page, title):
    return js(app, page, "document.querySelector('#room-title').textContent") == title


def queue_title(controller, title):
    controller.events.put(dict(controller.service.state, name=title, type='state'))


def test_title_refresh_keeps_draft_search_scroll_and_connection(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    service = controller.service
    seed_history(service, (f'가상 읽기 기록 {i}' for i in range(110)))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 111)
    incoming = Mock()
    monkeypatch.setattr(controller.notifications, 'incoming', incoming)
    context, session = service.context(), service.session
    js(app, page, """document.querySelector('#message-input').value='보존할 한글 초안';
        document.querySelector('#message-input').dispatchEvent(new Event('input'));
        const scroller=document.querySelector('#message-scroll');
        scroller.scrollTop=(scroller.scrollHeight-scroller.clientHeight)/2""")
    anchor = scroll_anchor(app, page)
    title = '<img src=x onerror=alert(1)> 변경된 한글 방 🙂'
    queue_title(controller, title)
    wait_until(app, lambda: title_is(app, page, title))
    assert js(app, page, "document.querySelector('#live-rooms .room-name').textContent") == title
    assert js(app, page, "document.querySelector('#live-rooms button').getAttribute('aria-label')") == title
    assert js(app, page, "document.querySelector('#live-rooms button').title") == title
    assert js(app, page, "document.querySelectorAll('#room-title img, .room-name img').length") == 0
    assert js(app, page, "document.querySelector('#message-input').value") == '보존할 한글 초안'
    after = scroll_anchor(app, page)
    assert after['id'] == anchor['id'] and abs(after['offset'] - anchor['offset']) < 2
    assert service.context() == context and service.session == session
    assert js(app, page, "document.querySelectorAll('.presence-notice').length") == 0
    assert controller.worker is None and controller.commands.empty()
    incoming.assert_not_called()

    js(app, page, """document.querySelector('#message-search').value='가상 읽기 기록';
        document.querySelector('#message-search').dispatchEvent(new Event('input'))""")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble mark').length") == 100)
    queue_title(controller, '검색 중 변경한 방')
    wait_until(app, lambda: title_is(app, page, '검색 중 변경한 방'))
    assert js(app, page, "document.querySelector('#message-search').value") == '가상 읽기 기록'
    assert js(app, page, "document.querySelectorAll('.message-bubble mark').length") == 100
    assert js(app, page, "document.querySelector('#message-input').value") == '보존할 한글 초안'


def test_live_rename_does_not_select_archived_room_or_change_its_title(qt_chat):
    app, controller, page = qt_chat
    controller.service.update(state(lobby='fixture-room-b', generation='fixture-segment-b', name='현재 방 B'))
    wait_until(app, lambda: title_is(app, page, '현재 방 B'))
    js(app, page, "document.querySelector('#archived-rooms button').click()")
    wait_until(app, lambda: title_is(app, page, '테스트 로비'))
    js(app, page, """document.querySelector('#message-input').value='보관 방 초안';
        document.querySelector('#message-input').dispatchEvent(new Event('input'))""")
    queue_title(controller, '현재 방 B 변경')
    wait_until(app, lambda: js(app, page, "document.querySelector('#live-rooms .room-name').textContent") == '현재 방 B 변경')
    assert title_is(app, page, '테스트 로비')
    assert js(app, page, "document.querySelector('#message-input').value") == '보관 방 초안'
    assert js(app, page, "document.querySelector('#archived-rooms button').getAttribute('aria-current')") == 'page'
    assert js(app, page, "document.querySelector('#send-button').disabled")


def test_storage_failure_shows_live_title_error_and_manual_refresh_recovers(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    rename = controller.store.rename_session
    monkeypatch.setattr(controller.store, 'rename_session', Mock(side_effect=sqlite3.OperationalError('synthetic')))
    queue_title(controller, '저장 실패 중 새 제목')
    wait_until(app, lambda: title_is(app, page, '저장 실패 중 새 제목'))
    assert js(app, page, "document.querySelector('#storage-label').textContent").startswith('저장 실패')
    assert js(app, page, "document.querySelector('#send-button').disabled")
    assert controller.store.rooms('fixture-self')[0]['name'] == '테스트 로비'
    monkeypatch.setattr(controller.store, 'rename_session', rename)
    js(app, page, "document.querySelector('#refresh-button').click()")
    wait_until(app, lambda: not js(app, page, "document.querySelector('#storage-label').textContent").startswith('저장 실패'))
    assert controller.store.rooms('fixture-self')[0]['name'] == '저장 실패 중 새 제목'
    page.triggerAction(page.WebAction.Reload)
    wait_until(app, lambda: title_is(app, page, '저장 실패 중 새 제목'))
    assert controller.worker is None and controller.commands.empty()
