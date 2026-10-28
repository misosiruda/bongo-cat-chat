"""Offscreen Qt integration: actual renderer, bridge and SQLite; no Steam calls."""
import json
import os
import time
import pytest
import sqlite3


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtWebEngineCore import QWebEngineScript

from bongo_chat.desktop import Controller, run, window
from bongo_chat.exit_codes import PROFILE_IN_USE, RESTART_FOR_UPDATE, RESTART_CAPABILITY
from bongo_chat.worker import unavailable
from bongo_chat import desktop
from bongo_chat.protocol import decode
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


def seed_history(service, messages):
    # Direct fixture inserts block the Qt heartbeat. Keep synthetic connection
    # state fresh so slower SQLite commits cannot discard later fixture rows.
    for text in messages:
        service.update(dict(service.state))
        received(service, text)


@pytest.mark.parametrize('diagnostic', [False, True])
def test_busy_profile_returns_operational_exit_without_opening_history(tmp_path, monkeypatch, diagnostic):
    app = QApplication.instance() or QApplication([])
    lock = QLockFile(str(tmp_path / 'app.lock'))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    notices = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: notices.append(args[2]))
    report = tmp_path / 'diagnostic' / 'busy.json' if diagnostic else None
    try:
        assert run(tmp_path, offline=True, smoke_report=report) == PROFILE_IN_USE
        assert not (tmp_path / 'history.sqlite3').exists()
        contender = QLockFile(str(tmp_path / 'app.lock'))
        assert not contender.tryLock(0)  # The original owner still holds the lock.
        if diagnostic:
            assert json.loads(report.read_text())['startup_error'] == 'profile_in_use'
            assert not notices
        else:
            assert notices == ['이미 실행 중인 앱이 있습니다.']
    finally:
        lock.unlock()


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
        controller.service.blocked['fixture-peer'] = '합성 차단 대상'
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


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_multiline_received_message_renders_line_breaks(qt_chat, newline):
    app, controller, page = qt_chat
    text = newline.join(["첫 줄 <검증>", "", "마지막 줄 🙂"])
    packet = json.dumps({"Channel": 3, "Message": text}, ensure_ascii=False).encode("utf-8")
    received(controller.service, decode(packet))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 2)
    displayed = text.replace("\r\n", "\n").replace("\r", "\n")
    assert js(app, page, "document.querySelector('.message:last-child .message-bubble').textContent") == displayed
    assert controller.service.view()["messages"][-1]["body"] == text
    layout = json.loads(js(app, page, """JSON.stringify((() => {
      const bubble=document.querySelector('.message:last-child .message-bubble');
      const text=bubble.firstChild, range=document.createRange();
      range.setStart(text,0);range.setEnd(text,1);const first=range.getBoundingClientRect().top;
      const last=text.textContent.indexOf('마지막');
      range.setStart(text,last);range.setEnd(text,last+1);
      return {gap:range.getBoundingClientRect().top-first,line:parseFloat(getComputedStyle(bubble).lineHeight)};
    })())"""))
    assert layout["gap"] == pytest.approx(2 * layout["line"], abs=1)
    js(app, page, "document.querySelector('#message-search').value='마지막';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble mark').length") == 1)
    assert js(app, page, "document.querySelector('.message-bubble').textContent") == displayed
    assert js(app, page, "document.querySelector('.message-bubble mark').textContent") == "마지막"
    assert js(app, page, "document.querySelectorAll('.message-bubble 검증').length") == 0
    assert controller.worker is None


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
    seed_history(controller.service, (f'이전 기록 {i}' for i in range(5)))
    original = controller.store.add
    monkeypatch.setattr(controller.store, 'add', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('disk full')))
    received(controller.service, '미저장 검색 대상')
    monkeypatch.setattr(controller.store, 'add', original)
    seed_history(controller.service, (f'복구 뒤 기록 {i}' for i in range(100)))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 107)
    assert js(app, page, "document.querySelector('.message-bubble').textContent") == '보존할 기록'
    assert js(app, page, "document.querySelector('.message-status').textContent") == '이 기록은 저장되지 않았어요'
    js(app, page, "document.querySelector('#message-search').value='미저장';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
    js(app, page, "document.querySelector('.message-content .page-button').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 101)
    js(app, page, "document.querySelector('#older').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 107)
    assert js(app, page, "document.querySelector('.message-bubble').textContent") == '보존할 기록'
    assert js(app, page, "document.querySelectorAll('.message-status').length") == 1
    js(app, page, "document.querySelector('#latest').click()")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 101)


def test_update_ready_keeps_editor_and_does_not_restart(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    requests = []
    monkeypatch.setattr(controller.updates, 'request', lambda: requests.append('check'))
    js(app, page, "document.querySelector('#message-input').value='업데이트 중 초안';document.querySelector('#message-input').dispatchEvent(new Event('input'))")
    controller.updates.report('ready', '0.2.0')
    wait_until(app, lambda: js(app, page, "document.querySelector('#update-status').textContent.includes('다음 실행')") is True)
    assert js(app, page, "document.querySelector('#message-input').value") == '업데이트 중 초안'
    assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 1
    js(app, page, "document.querySelector('#check-updates').click()")
    wait_until(app, lambda: len(requests) == 1)
    assert controller.worker is None and not controller.closed


def arm_automatic_restart(app, controller, page):
    # Only the updater capability is substituted. The actual Qt bridge,
    # renderer, countdown, draft writes and restart gate stay in use.
    controller.restart_supported = True
    controller.updates.enabled = True
    controller.updates.next_check = float('inf')
    js(app, page, 'window.realNow=Date.now;window.timeOffset=0;Date.now=()=>window.realNow()+window.timeOffset')
    controller.updates.report('ready', '0.2.0')
    wait_until(app, lambda: js(app, page, "!document.querySelector('#update-notice').hidden"))


def test_automatic_restart_saves_latest_draft_after_ime_and_input_idle(qt_chat):
    app, controller, page = qt_chat
    restarts = []
    controller.restart_requested.connect(lambda: restarts.append(controller.store.draft('fixture-self', 'fixture-room-a')))
    arm_automatic_restart(app, controller, page)
    assert not restarts
    js(app, page, "document.querySelector('#message-input').dispatchEvent(new CompositionEvent('compositionstart'));window.timeOffset=31000")
    wait_until(app, lambda: js(app, page, "document.querySelector('#update-notice').textContent.includes('입력·전송')"))
    assert not restarts
    js(app, page, "document.querySelector('#message-input').value='재시작 직전 한글 초안';document.querySelector('#message-input').dispatchEvent(new CompositionEvent('compositionend'));document.querySelector('#message-input').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: controller.store.draft('fixture-self', 'fixture-room-a') == '재시작 직전 한글 초안')
    assert not restarts
    js(app, page, 'window.timeOffset+=6000')
    wait_until(app, lambda: bool(restarts))
    assert restarts == ['재시작 직전 한글 초안']
    assert controller.restarting
    assert js(app, page, "document.querySelector('#message-input').disabled")


@pytest.mark.parametrize('blocker', ['sending', 'storage', 'volatile', 'draft_failure'])
def test_automatic_restart_waits_for_send_and_storage(qt_chat, monkeypatch, blocker):
    app, controller, page = qt_chat
    restarts = []
    controller.restart_requested.connect(lambda: restarts.append(True))
    command = None
    original_draft = controller.store.draft
    if blocker == 'sending':
        command = controller.service.prepare(controller.service.context(), '전송 완료 대기')
    elif blocker == 'storage':
        controller.service.storage_error = True
    elif blocker == 'volatile':
        # Use a real unsaved message rather than a malformed view fixture.
        original_add = controller.store.add
        def fail_add(*args, **kwargs):
            raise sqlite3.OperationalError('synthetic disk full')
        monkeypatch.setattr(controller.store, 'add', fail_add)
        received(controller.service, '저장 대기 기록')
        monkeypatch.setattr(controller.store, 'add', original_add)
        controller.service.storage_error = False
    else:
        def fail_draft(*args):
            if len(args) == 3:
                raise sqlite3.OperationalError('synthetic draft failure')
            return original_draft(*args)
        monkeypatch.setattr(controller.store, 'draft', fail_draft)
    arm_automatic_restart(app, controller, page)
    js(app, page, 'window.timeOffset=31000')
    expected = '입력·전송' if blocker == 'sending' else '저장되지 않은'
    wait_until(app, lambda: js(app, page, f"document.querySelector('#update-notice').textContent.includes('{expected}')"))
    assert not restarts and not controller.restarting
    assert not js(app, page, 'document.body.inert')
    if command:
        controller.service.result(command['id'], 'accepted')
    controller.service.storage_error = False
    controller.service.volatile.clear()
    monkeypatch.setattr(controller.store, 'draft', original_draft)
    js(app, page, 'window.timeOffset+=31000')
    wait_until(app, lambda: bool(restarts))
    assert restarts == [True]


def test_disabling_updates_cancels_countdown_and_rejects_stale_restart(qt_chat):
    app, controller, page = qt_chat
    restarts = []
    controller.restart_requested.connect(lambda: restarts.append(True))
    arm_automatic_restart(app, controller, page)
    controller.updates.set_allowed(False)
    js(app, page, 'window.timeOffset=31000')
    wait_until(app, lambda: js(app, page, "document.querySelector('#update-notice').hidden"))
    assert controller.dispatch({'action': 'restart_update'}) == {'ok': False, 'reason': 'unavailable'}
    assert not restarts


def test_old_launcher_cannot_request_new_restart_exit(qt_chat):
    app, controller, page = qt_chat
    controller.updates.enabled = True
    controller.updates.next_check = float('inf')
    controller.updates.report('ready', '0.2.0')
    controller.restart_supported = False
    assert controller.dispatch({'action': 'restart_update'}) == {'ok': False, 'reason': 'unavailable'}
    assert not controller.restarting


def test_restart_exit_closes_database_and_releases_profile_lock(tmp_path, monkeypatch):
    controllers = []
    original_window = desktop.window
    def restart_window(controller):
        controllers.append(controller)
        view = original_window(controller)
        QTimer.singleShot(0, controller.restart_requested.emit)
        return view
    monkeypatch.setattr(desktop, 'window', restart_window)
    assert run(tmp_path, offline=True) == RESTART_FOR_UPDATE
    assert controllers[0].closed and controllers[0].updates.closed
    with pytest.raises(sqlite3.ProgrammingError):
        controllers[0].store.db.execute('SELECT 1')
    lock = QLockFile(str(tmp_path / 'app.lock'))
    assert lock.tryLock(0)
    lock.unlock()


@pytest.mark.parametrize('root', [None, 'installation'])
def test_offline_controller_never_enables_restart_from_environment(tmp_path, monkeypatch, root):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv(RESTART_CAPABILITY, '1')
    controller = Controller(tmp_path, offline=True, install_root=tmp_path / root if root else None)
    try:
        assert not controller.restart_supported and not controller.can_restart()
    finally:
        controller.close()


def test_update_diagnostic_uses_real_renderer_without_worker(tmp_path, monkeypatch):
    controllers = []
    original_window = desktop.window
    monkeypatch.setenv(RESTART_CAPABILITY, '1')
    monkeypatch.setattr(desktop, 'update_checks_allowed', lambda: True)
    def diagnostic_window(controller):
        controllers.append(controller)
        assert controller.worker is None and controller.restart_supported
        controller.updates.next_check = float('inf')
        controller.updates.report('current')
        return original_window(controller)
    monkeypatch.setattr(desktop, 'window', diagnostic_window)
    reports = tmp_path / 'reports'
    assert run(tmp_path / 'data', offline=True, install_root=tmp_path / 'installed', update_smoke_dir=reports) == 0
    report = json.loads(next(reports.glob('*.json')).read_bytes())
    assert report['complete'] and report['renderer']
    assert not report['worker_started'] and not report['steam_connected'] and not report['restart_requested']
    assert report['console_errors'] == []
    assert controllers[0].closed


@pytest.mark.parametrize('size', [(1240, 840), (960, 540), (400, 500)])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_settings_close_stays_reachable_after_scroll_and_reopen(qt_chat, size, theme):
    app, controller, page = qt_chat
    page.parent().resize(*size)
    # Qt posts viewport resizing to the renderer asynchronously. In the same
    # theme, the theme check alone can pass before the new scroll geometry exists.
    wait_until(app, lambda: js(app, page, 'JSON.stringify([innerWidth,innerHeight])') == json.dumps(list(size), separators=(',', ':')))
    controller.store.setting('theme', theme)
    wait_until(app, lambda: js(app, page, 'document.documentElement.dataset.theme') == theme)
    js(app, page, """
      document.querySelector('#message-input').value='설정 확인 중 초안';
      document.querySelector('#message-input').dispatchEvent(new Event('input'));
      if (innerWidth <= 760) document.querySelector('#mobile-menu').click();
      document.querySelector('#settings-button').focus();
      document.querySelector('#settings-button').click();
      document.querySelector('#delete-room').click();
      document.querySelector('#confirm-delete').scrollIntoView({block:'end'});
    """)
    # Visible means inside the dialog's clipped viewport and able to receive
    # a pointer click, not merely a DOM element with display != none.
    visible_controls = """(() => {
      const dialog=document.querySelector('#settings-dialog');
      const bounds=dialog.getBoundingClientRect();
      const visible=selector => {
        const element=document.querySelector(selector), rect=element.getBoundingClientRect();
        return rect.top >= bounds.top && rect.bottom <= bounds.bottom
          && rect.left >= bounds.left && rect.right <= bounds.right
          && element.contains(document.elementFromPoint(rect.x+rect.width/2, rect.y+rect.height/2));
      };
      return bounds.top >= 0 && bounds.bottom <= innerHeight
        && bounds.left >= 0 && bounds.right <= innerWidth
        && visible('#settings-title') && visible('[aria-label="설정 닫기"]')
        && visible('#confirm-delete');
    })()"""
    wait_until(app, lambda: js(app, page, visible_controls))
    js(app, page, """
      document.querySelector('[aria-label="설정 닫기"]').click();
      document.querySelector('#settings-button').click();
    """)
    assert js(app, page, "document.querySelector('#delete-confirm').hidden") is True
    assert js(app, page, "document.querySelector('#settings-content').scrollTop") == 0
    assert js(app, page, "document.activeElement.getAttribute('aria-label')") == '설정 닫기'
    js(app, page, "document.querySelector('[aria-label=\"설정 닫기\"]').click()")
    assert js(app, page, "document.querySelector('#settings-dialog').open") is False
    assert js(app, page, "document.activeElement.id") == 'settings-button'
    assert js(app, page, "document.querySelector('#message-input').value") == '설정 확인 중 초안'
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 1
    assert controller.worker is None


@pytest.mark.parametrize('dialog_id,opener', [
    ('settings-dialog', 'settings-button'),
    ('participants-dialog', 'participants-button'),
])
def test_modal_stays_open_during_live_refresh(qt_chat, dialog_id, opener):
    app, controller, page = qt_chat
    js(app, page, f"document.querySelector('#{opener}').click()")
    js(app, page, f"""
      window.modalOpenChanges=0;
      new MutationObserver(records=>window.modalOpenChanges+=records.length)
        .observe(document.querySelector('#{dialog_id}'),{{attributes:true,attributeFilter:['open']}});
    """)
    for index in range(6):
        controller.service.update(state(profiles={
            'fixture-self': {'name': '테스트 계정'},
            'fixture-peer': {'name': f'갱신 고양이 {index}'},
        }))
        received(controller.service, f'모달 뒤에서 수신한 합성 발언 {index}')
        controller.updates.report('checking' if index % 2 else 'ready', '0.2.0')
        wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == index+2)
        assert js(app, page, f"""(() => {{
          const dialog=document.querySelector('#{dialog_id}');
          const heading=dialog.querySelector('h2'), rect=heading.getBoundingClientRect();
          return dialog.open && dialog.matches(':modal') && window.modalOpenChanges===0
            && dialog.contains(document.activeElement)
            && heading.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2));
        }})()""") is True
    # Native open state alone cannot detect a GPU-composited overlay disappearing.
    # Also keep the known problematic Windows Qt blur path out of both modals.
    assert js(app, page, f"getComputedStyle(document.querySelector('#{dialog_id}'),'::backdrop').backdropFilter") == 'none'
    assert controller.worker is None


def test_early_lobby_keeps_draft_and_separates_privacy_from_send(qt_chat):
    app, controller, page = qt_chat
    controller.service.update(state(state='syncing', notice='discovering', lobby_verified=False,
                                    privacy_ready=False, hidden_ok=False, send_enabled=False))
    wait_until(app, lambda: js(app, page, "document.querySelector('#connection-label').textContent.includes('로비 발견')"))
    assert js(app, page, "document.querySelector('#room-title').textContent") == '테스트 로비'
    assert js(app, page, "document.querySelector('#message-input').disabled") is False
    assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 0
    js(app, page, "document.querySelector('#message-input').value='연결 확인 중 작성';document.querySelector('#message-input').dispatchEvent(new Event('input'))")
    assert js(app, page, "document.querySelector('#send-button').disabled") is True
    wait_until(app, lambda: controller.store.draft('fixture-self', 'fixture-room-a') == '연결 확인 중 작성')
    controller.service.update(state(hidden={'fixture-peer':True}))
    wait_until(app, lambda: js(app, page, "document.querySelector('#connection-label').textContent.includes('게임과 연결됨')"))
    assert js(app, page, "document.querySelector('#send-button').disabled") is False
    assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 1
    assert js(app, page, "document.querySelector('#message-input').value") == '연결 확인 중 작성'
    controller.service.update(state())
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
    assert js(app, page, "document.querySelector('#message-input').value") == '연결 확인 중 작성'


def test_game_change_checks_updates_once_and_keeps_privacy_gate(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    requests = []
    monkeypatch.setattr(controller.updates, 'request', lambda: requests.append('check'))
    event = dict(unavailable('unsupported_game_build'), game_build='99999999', build_fingerprint='fixture-new')
    controller.events.put(event)
    wait_until(app, lambda: len(requests) == 1)
    controller.updates.report('checking')
    wait_until(app, lambda: js(app, page, "document.querySelector('#connection-notice').textContent.includes('99999999')"))
    assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 0
    assert js(app, page, "document.querySelector('#send-button').disabled") is True
    # Worker retries go through checking each time; this must not flood GitHub.
    revision = controller.service.revision
    controller.events.put(unavailable('checking'))
    controller.events.put(event)
    wait_until(app, lambda: controller.service.revision >= revision+2)
    assert requests == ['check']
    controller.updates.report('ready', '0.2.0')
    wait_until(app, lambda: js(app, page, "document.querySelector('#connection-notice').textContent.includes('다시 실행')"))
    assert not controller.service.can_send() and not controller.closed
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 1


def test_update_permission_and_local_legal_dialogs(qt_chat, monkeypatch, tmp_path):
    app, controller, page = qt_chat
    saved = []
    monkeypatch.setattr(desktop, 'set_update_checks_allowed', lambda value: saved.append(value))
    monkeypatch.setattr(desktop, 'LEGAL', tmp_path)
    (tmp_path / 'PRIVACY.md').write_text('개인정보 안내: 로컬 30일 보관', encoding='utf-8')
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#allow-update-checks').click()")
    wait_until(app, lambda: saved == [False])
    wait_until(app, lambda: js(app, page, "document.querySelector('#update-status').textContent.includes('껐습니다')"))
    assert js(app, page, "document.querySelector('#check-updates').disabled")
    assert controller.worker is None
    js(app, page, "document.querySelector('[data-legal=privacy]').click()")
    wait_until(app, lambda: len(controller.legal_dialogs) == 1)
    viewer = controller.legal_dialogs[0].findChild(desktop.QTextBrowser)
    assert '로컬 30일' in viewer.toPlainText()
    assert not viewer.openLinks() and not viewer.openExternalLinks()
    controller.legal_dialogs[0].close()
    assert not controller.legal_dialogs
    js(app, page, "document.querySelector('#allow-update-checks').click()")
    wait_until(app, lambda: saved == [False, True])
    assert not controller.updates.enabled  # Offline mode remains offline.
    assert not page.console_errors


@pytest.mark.parametrize('document,expected', [
    ('privacy', 'Privacy policy'), ('licenses', 'MIT License'),
    ('chromium', 'Qt WebEngine and Chromium notices'), ('sources', 'LGPL'),
])
def test_source_run_opens_checked_in_legal_documents(qt_chat, monkeypatch, tmp_path, document, expected):
    app, controller, page = qt_chat
    monkeypatch.setattr(desktop, 'LEGAL', tmp_path / 'no-bundle-notices')
    js(app, page, f"document.querySelector('[data-legal={document}]').click()")
    wait_until(app, lambda: len(controller.legal_dialogs) == 1)
    viewer = controller.legal_dialogs[0].findChild(desktop.QTextBrowser)
    assert expected in viewer.toPlainText()
    assert not viewer.openLinks() and not viewer.openExternalLinks()
    controller.legal_dialogs[0].close()
    app.processEvents()
    assert not controller.service.storage_error and controller.service.can_send()
    assert controller.worker is None and not page.console_errors


@pytest.mark.parametrize('failure', ['missing', 'invalid_utf8', 'permission'])
def test_frozen_notice_failures_do_not_disable_chat(qt_chat, monkeypatch, tmp_path, failure):
    app, controller, page = qt_chat
    monkeypatch.setattr(desktop, 'LEGAL', tmp_path)
    monkeypatch.setattr(desktop.sys, 'frozen', True, raising=False)
    if failure == 'invalid_utf8':
        (tmp_path / 'PRIVACY.md').write_bytes(b'\xff')
    elif failure == 'permission':
        def denied(*args, **kwargs):
            raise PermissionError('private fixture path must not reach the renderer')
        monkeypatch.setattr(desktop.Path, 'read_text', denied)
    result = json.loads(controller.request(json.dumps({'action': 'legal', 'document': 'privacy'})))
    assert result == {'error': 'legal_unavailable'}
    assert not controller.legal_dialogs  # No source fallback from a frozen build.
    assert not controller.service.storage_error and controller.service.can_send()
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 1


def test_update_permission_write_failure_preserves_choice_and_chat(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    before = controller.updates.snapshot()
    def denied(value):
        raise PermissionError('registry fixture error')
    monkeypatch.setattr(desktop, 'set_update_checks_allowed', denied)
    result = json.loads(controller.request(json.dumps({'action': 'update_permission', 'allowed': not before['allowed']})))
    assert result == {'error': 'update_permission_failed'}
    assert controller.updates.snapshot() == before
    assert not controller.service.storage_error and controller.service.can_send()
