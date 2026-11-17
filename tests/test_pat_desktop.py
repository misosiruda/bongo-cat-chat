"""Real Qt renderer + controller, synthetic pats only; no Steam/game mutations."""
import json
import sqlite3
import time

import pytest

from test_desktop import qt_chat, js, wait_until, seed_history
from test_pats import pat


def connect(app, controller, page):
    service = controller.service
    members = ['fixture-self', 'fixture-peer', 'fixture-third', 'fixture-fourth', 'fixture-fifth']
    service.update(dict(service.state, pats_supported=True, members=members,
                        profiles={uid: dict(name=name) for uid, name in zip(members, ['두부', '모카', '밤이', '유자', '솜이'])}))
    wait_until(app, lambda: js(app, page, "document.querySelector('#pats-enabled').checked"))
    return service


def incoming(service, target='fixture-peer', sender='fixture-self'):
    service.receive_pat(pat(service, sender=sender, target=target))


def row_count(app, page):
    return js(app, page, "document.querySelectorAll('.pat-row').length")


def test_qt_streak_fade_revival_same_node_and_no_side_effects(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    service = connect(app, controller, page)
    notifications = []
    monkeypatch.setattr(controller.notifications, 'incoming', notifications.append)
    js(app, page, "document.querySelector('#message-input').value='복복 중에도 초안 유지';document.querySelector('#message-input').dispatchEvent(new Event('input'))")
    for _ in range(3): controller.events.put(pat(service, sender='fixture-self', target='fixture-peer'))
    wait_until(app, lambda: row_count(app, page) == 1)
    assert js(app, page, "document.querySelector('.pat-count').textContent") == '×3'
    js(app, page, "window.originalPat=document.querySelector('.pat-row')")
    incoming(service)
    wait_until(app, lambda: js(app, page, "document.querySelector('.pat-count').textContent") == '×4')
    wait_until(app, lambda: js(app, page, "document.querySelector('.pat-row')?.classList.contains('is-fading')"))
    incoming(service)
    wait_until(app, lambda: js(app, page, "document.querySelector('.pat-count')?.textContent === '×1' && getComputedStyle(originalPat).opacity === '1'"))
    assert js(app, page, "originalPat === document.querySelector('.pat-row')")
    assert js(app, page, "document.querySelector('#message-input').value") == '복복 중에도 초안 유지'
    assert not notifications
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 1
    # The fixture added three lobby members; their legitimate join notices are
    # independent of pats. Pat receipts only stay in the in-memory tracker.
    assert all(row[0] in {'member_joined', 'member_left'} for row in controller.store.db.execute('SELECT kind FROM presence_events'))
    wait_until(app, lambda: row_count(app, page) == 0)
    assert js(app, page, "document.querySelector('#pat-zone').hidden")


def test_cap_overflow_live_names_and_safe_markup(qt_chat):
    app, controller, page = qt_chat
    service = connect(app, controller, page)
    service.nicknames['fixture-peer'] = '<img onerror=alert(1)>{sender}'
    for sender, target in [('fixture-self','fixture-peer'), ('fixture-peer','fixture-self'),
                           ('fixture-third','fixture-peer'), ('fixture-fourth','fixture-peer'),
                           ('fixture-fifth','fixture-peer'), ('fixture-peer','fixture-third')]:
        incoming(service, target, sender)
    wait_until(app, lambda: row_count(app, page) == 3)
    assert js(app, page, "document.querySelector('#pat-overflow').textContent") == '+3쌍도 복복 중'
    assert js(app, page, "document.querySelectorAll('.pat-row img').length") == 0
    assert '<img onerror=alert(1)>{sender}' in js(app, page, "document.querySelector('#pat-list').textContent")
    service.nicknames['fixture-peer'] = '바뀐 별명'
    wait_until(app, lambda: '바뀐 별명' in js(app, page, "document.querySelector('#pat-list').textContent"))
    service.blocked['fixture-peer'] = 'blocked target'
    wait_until(app, lambda: row_count(app, page) == 0)
    assert js(app, page, "document.querySelector('#pat-overflow').hidden")


def test_setting_failure_persistence_and_delayed_reply_cannot_replay(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    service = connect(app, controller, page)
    incoming(service)
    wait_until(app, lambda: row_count(app, page) == 1)
    original = controller.store.setting
    def fail(key, value=None, default=None):
        if key == 'pats_enabled' and value is not None: raise sqlite3.OperationalError('fixture')
        return original(key, value, default)
    monkeypatch.setattr(controller.store, 'setting', fail)
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#pats-enabled').click()")
    wait_until(app, lambda: '이전 값' in js(app, page, "document.querySelector('#pat-save-status').textContent"))
    assert service.pats_enabled and js(app, page, "document.querySelector('#pats-enabled').checked")
    monkeypatch.setattr(controller.store, 'setting', original)
    js(app, page, 'window.holdNextPatView=true')
    incoming(service)
    wait_until(app, lambda: js(app, page, "typeof window.releasePatView === 'function'"))
    js(app, page, "document.querySelector('#pats-enabled').click()")
    wait_until(app, lambda: original('pats_enabled') is False)
    assert not row_count(app, page)
    js(app, page, "document.querySelector('#pats-enabled').click()")
    wait_until(app, lambda: original('pats_enabled') is True)
    js(app, page, "window.releasePatView()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#pats-enabled').disabled"))
    assert not row_count(app, page)
    incoming(service)
    wait_until(app, lambda: row_count(app, page) == 1)
    assert js(app, page, "document.querySelector('.pat-count').textContent") == '×1'
    js(app, page, "document.querySelector('#pats-enabled').click()")
    wait_until(app, lambda: original('pats_enabled') is False)
    page.triggerAction(page.WebAction.Reload)
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
    assert js(app, page, "document.querySelector('#pats-enabled').checked") is False


def test_delayed_pat_snapshot_expires_while_bridge_reply_is_held(qt_chat):
    app, controller, page = qt_chat
    service = connect(app, controller, page)
    js(app, page, 'window.holdNextPatView=true')
    incoming(service)
    wait_until(app, lambda: js(app, page, "typeof window.releasePatView === 'function'"))
    deadline = time.monotonic() + 2.1
    wait_until(app, lambda: time.monotonic() > deadline)
    js(app, page, 'window.releasePatView()')
    deadline = time.monotonic() + .25
    wait_until(app, lambda: time.monotonic() > deadline)
    assert not row_count(app, page)


def test_banners_preserve_scroll_anchor_draft_and_count_at_minimum_width(qt_chat):
    app, controller, page = qt_chat
    service = connect(app, controller, page)
    seed_history(service, [f'스크롤 보존 검증 {i}' for i in range(45)])
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") > 40)
    js(app, page, """(() => {
      const scroll=document.querySelector('#message-scroll');scroll.scrollTop=300;
      window.anchor=[...document.querySelectorAll('.message')].find(el=>el.getBoundingClientRect().bottom>scroll.getBoundingClientRect().top);
      window.anchorOffset=anchor.getBoundingClientRect().top-scroll.getBoundingClientRect().top;
      document.querySelector('#message-input').value='남겨둔 초안';
    })()""")
    for target in ('fixture-peer','fixture-third','fixture-fourth'): incoming(service, target)
    wait_until(app, lambda: row_count(app, page) == 3)
    assert abs(js(app, page, "anchor.getBoundingClientRect().top-document.querySelector('#message-scroll').getBoundingClientRect().top-anchorOffset")) < 2
    assert js(app, page, "document.querySelector('#message-input').value") == '남겨둔 초안'
    wait_until(app, lambda: row_count(app, page) == 0)
    assert abs(js(app, page, "anchor.getBoundingClientRect().top-document.querySelector('#message-scroll').getBoundingClientRect().top-anchorOffset")) < 2
    page.parent().resize(400, 500)
    # QWidget resize and Chromium viewport updates cross a process boundary.
    wait_until(app, lambda: js(app, page, 'innerWidth === 400 && innerHeight === 500'))
    service.state['profiles']['fixture-peer']['name'] = '아주 긴 고양이 이름' * 10
    for target in ('fixture-peer','fixture-third','fixture-fourth'): incoming(service, target)
    wait_until(app, lambda: row_count(app, page) == 3)
    assert js(app, page, "[...document.querySelectorAll('.pat-count')].every(el=>el.getBoundingClientRect().right<=innerWidth)")
    layout = json.loads(js(app, page, "JSON.stringify({bottom:document.querySelector('.composer-region').getBoundingClientRect().bottom, height:innerHeight, width:innerWidth, scrollHeight:document.querySelector('#message-scroll').clientHeight})"))
    assert layout['bottom'] <= layout['height'], layout
    assert layout['scrollHeight'] > 40, layout


@pytest.mark.parametrize('value', [None, 0, 1, 'false', [], {}])
def test_pat_setting_native_validation(qt_chat, value):
    _, controller, _ = qt_chat
    result = json.loads(controller.request(json.dumps(dict(action='setting', key='pats_enabled', value=value))))
    assert result == {'error':'request_failed'}
    assert controller.service.pats_enabled


def test_overflow_summary_preserves_bottom_pin(qt_chat):
    app, controller, page = qt_chat
    service = connect(app, controller, page)
    seed_history(service, [f'하단 유지 검증 {i}' for i in range(45)])
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") > 40)
    js(app, page, "document.querySelector('#message-scroll').scrollTop=document.querySelector('#message-scroll').scrollHeight")
    for target in ('fixture-peer','fixture-third','fixture-fourth','fixture-fifth'): incoming(service, target)
    wait_until(app, lambda: js(app, page, "!document.querySelector('#pat-overflow').hidden"))
    gap = js(app, page, "(() => {const el=document.querySelector('#message-scroll');return el.scrollHeight-el.scrollTop-el.clientHeight})()")
    assert gap <= 1
    wait_until(app, lambda: row_count(app, page) == 0)
    assert js(app, page, "(() => {const el=document.querySelector('#message-scroll');return el.scrollHeight-el.scrollTop-el.clientHeight})()") <= 1


@pytest.mark.parametrize('size', [(400, 500), (536, 1000), (1240, 840)])
@pytest.mark.parametrize('at_bottom', [False, True])
def test_pat_overlay_keeps_viewport_geometry(qt_chat, size, at_bottom):
    app, controller, page = qt_chat
    page.parent().resize(*size)
    wait_until(app, lambda: js(app, page, f'innerWidth === {size[0]} && innerHeight === {size[1]}'))
    service = connect(app, controller, page)
    seed_history(service, [f'겹침 검증 {i}' for i in range(45)])
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") > 40)
    top = "el.scrollHeight" if at_bottom else "300"
    js(app, page, f"(()=>{{const el=document.querySelector('#message-scroll');el.scrollTop={top}}})()")
    measure = "JSON.stringify((()=>{const el=document.querySelector('#message-scroll');return [el.scrollTop,el.scrollHeight,el.clientHeight,el.getBoundingClientRect().top]})())"
    baseline = js(app, page, measure)
    for target in ('fixture-peer', 'fixture-third', 'fixture-fourth', 'fixture-fifth'):
        incoming(service, target)
    wait_until(app, lambda: js(app, page, "!document.querySelector('#pat-overflow').hidden"))
    assert js(app, page, measure) == baseline
    wait_until(app, lambda: row_count(app, page) == 0)
    assert js(app, page, measure) == baseline
