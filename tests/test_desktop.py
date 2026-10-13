"""Offscreen Qt integration: actual renderer, bridge and SQLite; no Steam calls."""
import json
import os
import time
import pytest
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineScript

from bongo_chat.desktop import Controller, window
from test_core import received, state


def wait_until(app, predicate, seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        time.sleep(.01)
    raise AssertionError("Qt UI condition timed out")


def js(app,page,code):
    result=[]
    page.runJavaScript(code,lambda x:result.append(x))
    wait_until(app,lambda:bool(result))
    return result[0]


def test_actual_qt_bridge_history_theme_hide_ime(tmp_path):
    app=QApplication.instance() or QApplication([])
    controller=Controller(tmp_path,offline=True)
    controller.service.update(state(profiles={"fixture-peer":{"name":"검증 고양이"},"fixture-self":{"name":"테스트 계정"}}))
    received(controller.service,"한글 <script>alert(1)</script> 검증")
    view=window(controller);view.show();page=view.page()
    heartbeat=QTimer();heartbeat.timeout.connect(lambda:controller.service.update(dict(controller.service.state)));heartbeat.start(300)
    try:
        wait_until(app,lambda:js(app,page,"document.querySelectorAll('.message-bubble').length") == 1)
        assert js(app,page,"document.querySelector('.message-bubble').textContent") == "한글 <script>alert(1)</script> 검증"
        assert js(app,page,"document.querySelectorAll('.message-bubble script').length") == 0
        js(app,page,"document.querySelector('#message-input').value='작성 중 한글';document.querySelector('#message-input').dispatchEvent(new Event('input'));document.querySelector('[value=dark]').click()")
        wait_until(app,lambda:controller.store.setting("theme") == "dark")
        assert js(app,page,"document.documentElement.dataset.theme") == "dark"
        js(app,page,"document.querySelector('#message-input').dispatchEvent(new CompositionEvent('compositionstart'));document.querySelector('#message-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,isComposing:true}))")
        assert controller.store.db.execute("SELECT count(*) FROM messages").fetchone()[0]==1
        js(app,page,"document.querySelector('#message-input').dispatchEvent(new CompositionEvent('compositionend'))")
        wait_until(app,lambda:controller.store.draft("fixture-self","fixture-room-a") == "작성 중 한글")
        js(app,page,"document.querySelector('#sidebar-toggle').click()")
        wait_until(app,lambda:controller.store.setting("collapsed") is True)
        assert js(app,page,"document.querySelector('#message-input').value") == "작성 중 한글"
        controller.service.update(state(hidden={"fixture-peer":True}))
        wait_until(app,lambda:js(app,page,"document.querySelectorAll('.message-bubble').length") == 0)
        assert js(app,page,"document.body.textContent.includes('한글 <script>')") is False
        assert not page.console_errors, page.console_errors
    finally:
        heartbeat.stop();view.close();controller.close();view.deleteLater();app.processEvents()


@pytest.fixture
def qt_chat(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = Controller(tmp_path, offline=True)
    controller.service.update(state())
    controller.known_accounts.add('fixture-self')
    received(controller.service, '보존할 기록')
    view = window(controller)
    # Delay one real QWebChannel reply, without replacing the native controller.
    hook = QWebEngineScript()
    hook.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    hook.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    hook.setSourceCode("""
      Object.defineProperty(window, 'QWebChannel', {configurable:true, set(ctor) {
        Object.defineProperty(window, 'QWebChannel', {configurable:true, value:function(transport, ready) {
          return new ctor(transport, channel => {
            const bridge=channel.objects.bridge, request=bridge.request.bind(bridge);
            bridge.request=(raw, done)=>request(raw, result=>{
              if (window.holdNextView && JSON.parse(raw).action==='view') {
                window.holdNextView=false; window.releaseView=()=>{window.releaseView=null;done(result);};
              } else done(result);
            });
            ready(channel);
          });
        }});
      }});
    """)
    view.page().scripts().insert(hook)
    view.reload(); view.show(); page = view.page()
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: controller.service.update(dict(controller.service.state)))
    heartbeat.start(300)
    try:
        wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
        yield app, controller, page
        assert not page.console_errors, page.console_errors
    finally:
        heartbeat.stop(); view.close(); controller.close(); view.deleteLater(); app.processEvents()


def test_lobby_transition_during_view_reply_keeps_editor_ownership(qt_chat):
    app, controller, page = qt_chat
    controller.store.draft('fixture-self', 'fixture-room-b', '새 방에 저장한 초안')
    js(app, page, 'window.holdNextView=true')
    controller.service.update(state(lobby='fixture-room-b', generation='fixture-segment-b'))
    wait_until(app, lambda: js(app, page, "typeof window.releaseView==='function'"))
    js(app, page, "document.querySelector('#message-input').value='응답 대기 중 이전 방 입력';document.querySelector('#message-input').dispatchEvent(new Event('input'));window.releaseView()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#message-input').value") == '새 방에 저장한 초안')
    assert controller.store.draft('fixture-self', 'fixture-room-a') == '응답 대기 중 이전 방 입력'
    js(app, page, "document.querySelector('#send-button').click()")
    wait_until(app, lambda: controller.store.db.execute('SELECT count(*) FROM messages WHERE own=1').fetchone()[0] == 1)
    row = controller.store.db.execute('SELECT lobby,body FROM messages WHERE own=1').fetchone()
    assert tuple(row) == ('fixture-room-b', '새 방에 저장한 초안')
    assert controller.worker is None  # Only the local send intent, no native send.


def test_delete_confirmation_does_not_follow_new_account(qt_chat):
    app, controller, page = qt_chat
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#delete-all').click()")
    controller.service.update(state(account='fixture-second', generation='fixture-second-segment', profiles={'fixture-second':{'name':'새 계정'}}))
    received(controller.service, '다른 계정의 기록')
    wait_until(app, lambda: js(app, page, "document.querySelector('.account-copy strong').textContent") == '새 계정')
    js(app, page, "document.querySelector('#confirm-delete').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#toast').hidden"))
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 2


def test_deleting_archived_room_returns_to_current_room(qt_chat):
    app, controller, page = qt_chat
    controller.service.update(state(lobby='fixture-room-b', generation='fixture-segment-b', name='현재 방'))
    wait_until(app, lambda: js(app, page, "document.querySelector('#room-title').textContent") == '현재 방')
    js(app, page, "document.querySelector('#archived-rooms button').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#room-title').textContent") == '테스트 로비')
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#delete-room').click();document.querySelector('#confirm-delete').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#room-title').textContent") == '현재 방')
    assert controller.store.rooms('fixture-self')[0]['lobby'] == 'fixture-room-b'
    assert not controller.store.draft('fixture-self', 'fixture-room-a')


def test_view_failure_clears_stale_peer_display(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    original = controller.dispatch
    def dispatch(args):
        if args['action'] == 'view':
            raise sqlite3.OperationalError('synthetic read failure')
        return original(args)
    monkeypatch.setattr(controller, 'dispatch', dispatch)
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 0)
    assert js(app, page, "document.querySelector('#send-button').disabled") is True
    assert js(app, page, "document.querySelectorAll('#participant-list li').length") == 0


def test_unsaved_first_message_keeps_search_jump_and_older_page(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    for i in range(5):
        received(controller.service, f'이전 기록 {i}')
    original = controller.store.add
    monkeypatch.setattr(controller.store, 'add', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('disk full')))
    received(controller.service, '미저장 검색 대상')
    monkeypatch.setattr(controller.store, 'add', original)
    for i in range(100):
        received(controller.service, f'복구 뒤 기록 {i}')
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 101)
    assert js(app, page, "document.querySelector('.message-bubble').textContent") == '미저장 검색 대상'
    assert js(app, page, "document.querySelector('.message-status').textContent") == '이 기록은 저장되지 않았어요'
    js(app, page, "document.querySelector('#message-search').value='미저장';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
    js(app, page, "document.querySelector('.message-content .page-button').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 101)
    js(app, page, "document.querySelector('#older').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 6)
    assert js(app, page, "document.querySelector('.message-bubble').textContent") == '보존할 기록'
    assert js(app, page, "document.querySelectorAll('.message-status').length") == 0
    js(app, page, "document.querySelector('#latest').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 101)
