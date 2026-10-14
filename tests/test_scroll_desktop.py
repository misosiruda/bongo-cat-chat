import json

import pytest

from test_core import received
from test_desktop import js, qt_chat, wait_until

def scroll_anchor(app, page):
    return json.loads(js(app, page, """JSON.stringify((() => {
      const el=document.querySelector('#message-scroll'), rect=el.getBoundingClientRect();
      const row=[...el.querySelectorAll('.message')].find(x=>x.getBoundingClientRect().bottom>rect.top);
      return {id:row?.id,offset:row?row.getBoundingClientRect().top-rect.top:0,
        gap:el.scrollHeight-el.scrollTop-el.clientHeight};
    })())"""))


def test_qt_incoming_preserves_message_anchor_and_manual_bottom_clears_badge(qt_chat):
    app, controller, page = qt_chat
    for i in range(180):
        received(controller.service, f'스크롤 가상 기록 {i}')
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 181)
    js(app, page, "const s=document.querySelector('#message-scroll');s.scrollTop=(s.scrollHeight-s.clientHeight)/2")
    before = scroll_anchor(app, page)
    for i in range(5):
        received(controller.service, f'새 가상 기록 {i}')
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 186)
    after = scroll_anchor(app, page)
    assert after['id'] == before['id'] and abs(after['offset'] - before['offset']) < 2
    assert js(app, page, "!document.querySelector('#new-messages').hidden")
    js(app, page, "document.querySelector('#message-scroll').scrollTop=document.querySelector('#message-scroll').scrollHeight")
    wait_until(app, lambda: js(app, page, "document.querySelector('#new-messages').hidden && document.querySelector('#latest').hidden"))
    assert scroll_anchor(app, page)['gap'] <= 1
    assert controller.worker is None


def test_qt_older_history_is_continuous_and_own_send_returns_to_latest(qt_chat):
    app, controller, page = qt_chat
    for i in range(350):
        received(controller.service, f'연속 가상 기록 {i}')
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 351)
    js(app, page, "document.querySelector('#latest').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 100)
    assert scroll_anchor(app, page)['gap'] <= 1
    first = js(app, page, "document.querySelector('.message').id")
    js(app, page, "document.querySelector('#message-scroll').scrollTop=0")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 200)
    assert js(app, page, f"document.getElementById({json.dumps(first)})!==null")
    js(app, page, "document.querySelector('#message-input').value='과거 열람 중 내 가상 메시지';document.querySelector('#message-input').dispatchEvent(new Event('input'));document.querySelector('#send-button').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message.is-own').length") == 1)
    wait_until(app, lambda: js(app, page, "document.querySelector('#message-input').value") == '')
    assert scroll_anchor(app, page)['gap'] <= 1
    assert js(app, page, "document.querySelector('.message.is-own .message-status').textContent") == '전송 중'
    assert controller.worker is None  # Local intent only, never Steam transmission.


def test_qt_search_restore_keeps_window_and_message_anchor(qt_chat):
    app, controller, page = qt_chat
    for i in range(250):
        received(controller.service, f'검색 가상 기록 {i:03d}')
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 251)
    js(app, page, "const s=document.querySelector('#message-scroll');s.scrollTop=(s.scrollHeight-s.clientHeight)/2")
    before = scroll_anchor(app, page)
    js(app, page, "document.querySelector('#message-search').value='검색 가상 기록 050';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 1)
    js(app, page, "document.querySelector('#clear-search').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 251)
    after = scroll_anchor(app, page)
    assert after['id'] == before['id'] and abs(after['offset'] - before['offset']) < 2
    js(app, page, "document.querySelector('#message-search').value='검색 가상 기록 050';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") == 1)
    js(app, page, "document.querySelector('.message-content .page-button').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message').length") > 1)
    assert js(app, page, "[...document.querySelectorAll('.message-bubble')].some(x=>x.textContent==='검색 가상 기록 051')")


@pytest.mark.parametrize('changes', [
    {'start':True}, {'seen':-1}, {'limit':1001}, {'limit':True}, {'start':1,'before':2},
])
def test_history_bridge_rejects_invalid_window_arguments(qt_chat, changes):
    _, controller, _ = qt_chat
    with pytest.raises(ValueError, match='invalid_query'):
        controller.dispatch(dict(action='view', **changes))


