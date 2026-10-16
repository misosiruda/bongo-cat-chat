"""Actual Qt/QWebChannel with synthetic peers and a blocked OS protocol handler."""
import json

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import QApplication

from bongo_chat import desktop
from bongo_chat.desktop import Controller, window
from test_core import received
from test_desktop import js, wait_until
from test_profiles import PEER, SECOND, SELF, profile_state


@pytest.fixture
def profile_controller(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr(desktop.QDesktopServices, 'openUrl', lambda url: calls.append(url.toString()) or True)
    controller = Controller(tmp_path, offline=True)  # No worker; inject a synthetic live snapshot.
    controller.service.update(profile_state(hidden={PEER: False, SECOND: False}))
    yield app, controller, calls
    controller.close()


def request(controller, **changes):
    payload = dict(action='open_steam_profile', steam_id=PEER, context=controller.service.context())
    payload.update(changes)
    return json.loads(controller.request(json.dumps(payload)))


def test_native_adapter_passes_exact_fixed_qurl_once(profile_controller):
    _, controller, calls = profile_controller
    assert request(controller) == {'ok': True}
    assert calls == ['steam://url/SteamIDPage/' + PEER]
    assert controller.worker is None


@pytest.mark.parametrize('failure', [False, OSError('handler missing'), RuntimeError('handler error')])
def test_os_failure_is_isolated_from_storage_and_messages(profile_controller, monkeypatch, failure):
    _, controller, calls = profile_controller
    def fail(url):
        calls.append(url.toString())
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(desktop.QDesktopServices, 'openUrl', fail)
    service = controller.service
    service.update(dict(service.state, send_enabled=True))
    assert service.can_send()
    service.store.draft(SELF, service.context()['lobby'], '보존할 한글 초안')
    received(service, '보존할 합성 기록', sender=PEER)
    before = service.view()
    assert request(controller) == {'error': 'steam_profile_failed'}
    after = service.view()
    assert len(calls) == 1 and not service.storage_error
    assert service.can_send()
    assert after['messages'] == before['messages'] and after['draft'] == before['draft']
    assert not service.pending and not controller.opening_profile


@pytest.mark.parametrize('kind', ['closed', 'restarting', 'opening_profile', 'invalid', 'self', 'unknown', 'stale', 'context'])
def test_rejected_requests_never_reach_os(profile_controller, kind):
    _, controller, calls = profile_controller
    changes = {}
    if kind in ('closed', 'restarting', 'opening_profile'):
        setattr(controller, kind, True)
    elif kind == 'invalid': changes['steam_id'] = int(PEER)
    elif kind == 'self': changes['steam_id'] = SELF
    elif kind == 'unknown': changes['steam_id'] = '76561190000000003'
    elif kind == 'stale': controller.service.updated -= 3
    else: changes['context'] = dict(controller.service.context(), generation='old')
    result = request(controller, **changes)
    assert result['error'] in {'invalid_steam_id', 'steam_profile_unavailable'}
    assert not calls and not controller.service.storage_error
    controller.closed = False  # Allow fixture teardown to release the store/queues.


def test_reentrant_open_is_rejected_and_restart_removes_view_actions(profile_controller, monkeypatch):
    _, controller, calls = profile_controller
    nested = []
    def open_once(url):
        calls.append(url.toString())
        nested.append(request(controller))
        return True
    monkeypatch.setattr(desktop.QDesktopServices, 'openUrl', open_once)
    assert request(controller) == {'ok': True}
    assert nested == [{'error': 'steam_profile_unavailable'}] and len(calls) == 1
    controller.restarting = True
    assert controller.dispatch({'action': 'view'})['profile_targets'] == []


@pytest.fixture
def profile_ui(profile_controller):
    app, controller, calls = profile_controller
    received(controller.service, '프로필 시험 대화', sender=PEER)
    received(controller.service, '동명이인 시험 대화', sender=SECOND)
    received(controller.service, '내 시험 대화', sender=SELF)
    view = window(controller)
    hook = QWebEngineScript()
    hook.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    hook.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    hook.setSourceCode("""
      Object.defineProperty(window, 'QWebChannel', {configurable:true, set(ctor) {
        Object.defineProperty(window, 'QWebChannel', {configurable:true, value:function(transport, ready) {
          return new ctor(transport, channel => {
            const bridge=channel.objects.bridge, request=bridge.request.bind(bridge);
            window.profileRequests=[];
            bridge.request=(raw, done)=>{
              const args=JSON.parse(raw);
              if (args.action==='open_steam_profile') window.profileRequests.push(args);
              request(raw, result=>{
                if (window.holdProfile && args.action==='open_steam_profile') {
                  window.releaseProfile=()=>{window.holdProfile=false;done(result);};
                } else done(result);
              });
            };
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
        wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 3)
        yield app, controller, page, calls, heartbeat
        assert not page.console_errors, page.console_errors
    finally:
        heartbeat.stop(); view.close(); view.deleteLater(); app.processEvents()


def test_real_bridge_exact_id_context_one_click_and_busy_guard(profile_ui):
    app, controller, page, calls, _ = profile_ui
    assert not controller.service.can_send()  # Read-only profiles still work.
    js(app, page, "document.querySelector('#participants-button').click();window.holdProfile=true;"
       "const b=document.querySelector('.participant-profile');b.focus();b.click();b.click();")
    wait_until(app, lambda: len(calls) == 1)
    payload = json.loads(js(app, page, 'JSON.stringify(window.profileRequests)'))
    assert payload == [dict(action='open_steam_profile', steam_id=PEER, context=controller.service.context())]
    assert js(app, page, "document.activeElement.classList.contains('participant-profile')")
    assert js(app, page, "document.querySelector('.participant-profile').getAttribute('aria-disabled')") == 'true'
    js(app, page, 'window.releaseProfile()')
    wait_until(app, lambda: js(app, page, "document.querySelector('.participant-profile').getAttribute('aria-disabled')") == 'false')
    assert js(app, page, "document.querySelector('#participants-dialog').open")
    # The other identical display name must preserve its own, distinct ID.
    js(app, page, "document.querySelectorAll('.participant-profile')[1].click()")
    wait_until(app, lambda: len(calls) == 2)
    assert calls == ['steam://url/SteamIDPage/' + PEER, 'steam://url/SteamIDPage/' + SECOND]


def test_actions_follow_connection_and_membership_without_message_changes(profile_ui):
    app, controller, page, calls, heartbeat = profile_ui
    assert js(app, page, "document.querySelectorAll('.profile-name').length") == 2
    assert js(app, page, "document.querySelectorAll('.message.is-own .steam-profile-action').length") == 0
    js(app, page, "window.oldProfileButton=document.querySelector('.profile-name')")
    controller.service.update(profile_state(profiles={SELF: {'name': '시험 계정'}}, hidden={PEER: False, SECOND: False}))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.profile-name').length") == 0)
    assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 3
    js(app, page, 'window.oldProfileButton.click()')
    assert not calls
    controller.service.update(profile_state(hidden={PEER: False, SECOND: False}))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.profile-name').length") == 2)
    heartbeat.stop(); controller.service.updated -= 3
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.steam-profile-action').length") == 0)


def test_old_buttons_keep_original_generation_and_participant_focus_survives_refresh(profile_ui):
    app, controller, page, calls, _ = profile_ui
    js(app, page, "document.querySelector('#participants-button').click();"
       "window.oldProfileButton=document.querySelector('.participant-profile');window.oldProfileButton.focus()")
    for index in range(3):
        profiles = dict(controller.service.state['profiles'])
        profiles[PEER] = {'name': f'이름 갱신 {index}'}
        controller.service.update(dict(controller.service.state, profiles=profiles))
        wait_until(app, lambda: js(app, page, "document.activeElement.getAttribute('aria-label')") == f'Steam 프로필 열기 · 이름 갱신 {index}')
        assert js(app, page, "document.querySelector('#participants-dialog').open")
    controller.service.update(profile_state(generation='new-segment', hidden={PEER: False, SECOND: False}))
    wait_until(app, lambda: js(app, page, "document.querySelector('.participant-profile').dataset.profileContext.includes('new-segment')"))
    js(app, page, 'window.oldProfileButton.click()')
    assert not calls


def test_profile_failure_keeps_editor_search_room_scroll_and_send_state(profile_ui, monkeypatch):
    app, controller, page, calls, _ = profile_ui
    monkeypatch.setattr(desktop.QDesktopServices, 'openUrl', lambda url: calls.append(url.toString()) or False)
    js(app, page, "document.querySelector('#message-input').value='작성 중인 한글';document.querySelector('#message-input').dispatchEvent(new Event('input'));"
       "document.querySelector('#message-search').value='프로필';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
    before = js(app, page, "[document.querySelector('#message-scroll').scrollTop,document.querySelector('#room-title').textContent]")
    js(app, page, "document.querySelector('.profile-avatar').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#toast').textContent.includes('열지 못했어요')"))
    assert len(calls) == 1 and not controller.service.storage_error
    assert js(app, page, "document.querySelector('#message-input').value") == '작성 중인 한글'
    assert js(app, page, "document.querySelector('#message-search').value") == '프로필'
    assert js(app, page, "[document.querySelector('#message-scroll').scrollTop,document.querySelector('#room-title').textContent]") == before
    assert js(app, page, "document.querySelector('#send-button').disabled")


def test_renderer_navigation_and_body_urls_do_not_gain_protocol_permission(profile_ui):
    app, controller, page, calls, _ = profile_ui
    uri = 'steam://url/SteamIDPage/' + PEER
    assert not page.acceptNavigationRequest(QUrl(uri), page.NavigationType.NavigationTypeLinkClicked, True)
    assert not page.acceptNavigationRequest(QUrl('https://steamcommunity.com/'), page.NavigationType.NavigationTypeLinkClicked, True)
    class Request:
        blocked = None
        def requestUrl(self): return QUrl(uri)
        def block(self, blocked): self.blocked = blocked
    info = Request()
    desktop.Requests().interceptRequest(info)
    assert info.blocked
    received(controller.service, uri, sender=PEER)
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 4)
    assert js(app, page, "document.querySelectorAll('.message-bubble a,.message-bubble button').length") == 0
    assert not calls
