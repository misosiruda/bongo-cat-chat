"""Synthetic diagnostics and real offline Qt UI; never creates an external issue."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from bongo_chat import desktop
from bongo_chat.bug_report import ReportPreview, collect, ISSUES
from bongo_chat.diagnostics import clean_details
from bongo_chat.merge_connection import MergeConnection
from test_desktop import qt_chat, js, wait_until


def failure():
    error = RuntimeError('attach_not_confirmed_no_retry')
    error.connection_diagnostics = dict(phase='bootstrap', source='new', status=2, stage=7,
        managed_exception=True, load_error=0, token='secret-token', path='C:/private/user',
        exception=123456789, load_message='private native error', account='private-account')
    raise error


def failed_connection():
    connection = MergeConnection(failure)
    connection._connect()
    return connection


def test_report_uses_allowlist_instead_of_copying_chat_or_raw_logs():
    connection = failed_connection()
    raw = connection.diagnostic_snapshot()
    raw.update(token='secret-token', path='C:/private/user')
    raw['attempts'][0].update(message='private-chat', stack='private-stack')
    report = collect('chest', dict(notice='checking', connected=True, account='private-account',
        lobby='private-lobby', profiles={'peer': {'name': 'private-name'}}, body='private-chat',
        game_build='26431657'), raw)
    encoded = json.dumps(report)
    for secret in ('secret-token', 'C:/private', 'private-account', 'private-lobby', 'private-name',
                   'private-chat', 'private-stack', 'private native error', '123456789'):
        assert secret not in encoded
    attempt = report['automation']['attempts'][0]
    assert report['chat']['game_build'] == '26431657'
    assert attempt == dict(error='attach_not_confirmed_no_retry', phase='bootstrap', source='new',
                          status=2, stage=7, managed_exception=True, load_error=0)


def test_malformed_and_untrusted_fields_cannot_enter_a_public_report():
    assert clean_details(dict(phase=['bootstrap'], status=True, stage=1000, load_error=-1,
                             winerror='C:/secret', managed_exception=1, source='private')) == {}
    result = collect('app', {'notice': 'private-chat', 'game_build': 'private-build'}, {'state': 'private-path', 'error': 'private-error',
        'attempts': [None, {'error': 'private-error', 'native_error': 'private-native', 'token': 'secret'}]})
    assert 'private' not in json.dumps(result) and 'secret' not in json.dumps(result)
    assert result['automation']['error'] == 'bridge_connection_failed'


def test_failure_history_is_bounded_and_does_not_expose_mutable_internal_state():
    connection = failed_connection()
    for _ in range(5):
        connection._connect()
    snapshot = connection.diagnostic_snapshot()
    assert len(snapshot['attempts']) == 3
    snapshot['attempts'][0]['phase'] = 'private-text'
    assert connection.diagnostic_snapshot()['attempts'][0]['phase'] == 'bootstrap'


@pytest.mark.parametrize('area', [None, [], 'https://attacker.invalid', 'private-user'])
def test_invalid_report_area_is_rejected(area):
    with pytest.raises(ValueError):
        collect(area, {}, None)


@pytest.mark.parametrize('language', ['ko', 'en'])
def test_github_draft_contains_exact_preview_and_has_bounded_url(language):
    preview = ReportPreview()
    connection = failed_connection()
    for _ in range(4):
        connection._connect()
    result = preview.prepare('chest', {}, connection.diagnostic_snapshot(), language)
    target = preview.get(result['id'])
    parsed = urlsplit(target['url'])
    assert parsed.scheme + '://' + parsed.netloc + parsed.path == ISSUES
    query = parse_qs(parsed.query)
    assert query == {'title': [result['title']], 'body': [result['body']]}
    assert len(target['url']) < 7500
    assert '"managed_exception": true' in result['body']
    if language == 'en':
        assert 'What happened?' in result['body']
    preview.prepare('app', {}, None)
    with pytest.raises(ValueError, match='report_expired'):
        preview.get(result['id'])
    preview.clear()
    with pytest.raises(ValueError, match='report_expired'):
        preview.get(None)


@pytest.mark.parametrize('area,button', [('app', 'settings-button'), ('chest', 'chest-open'), ('merge', 'merge-open')])
def test_real_report_ui_previews_copies_then_opens_exact_draft(qt_chat, monkeypatch, area, button):
    app, controller, page = qt_chat
    controller.merge_connection = failed_connection()
    opened = []
    monkeypatch.setattr(desktop.QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()) or True)
    app.clipboard().setText('untouched clipboard')
    before = list(controller.store.db.execute('SELECT * FROM messages'))
    js(app, page, f"document.querySelector('#{button}').click();document.querySelector('[data-report={area}]').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#bug-report-copy').disabled"))
    body = js(app, page, "document.querySelector('#bug-report-preview').textContent")
    assert 'attach_not_confirmed_no_retry' in body and '"stage": 7' in body
    assert '보존할 기록' not in body and 'fixture-self' not in body and 'secret-token' not in body
    assert opened == [] and app.clipboard().text() == 'untouched clipboard'
    assert controller.worker is None and not controller.service.storage_error
    js(app, page, "document.querySelector('#bug-report-copy').click()")
    wait_until(app, lambda: app.clipboard().text() == body)
    js(app, page, "document.querySelector('#bug-report-open').click()")
    wait_until(app, lambda: len(opened) == 1)
    assert parse_qs(urlsplit(opened[0]).query)['body'] == [body]
    wait_until(app, lambda: js(app, page, "document.querySelector('#bug-report-status').textContent.includes('등록을 눌러야')"))
    old_id = controller.bug_report.current['id']
    js(app, page, "document.querySelector('#bug-report-dialog').close()")
    wait_until(app, lambda: controller.bug_report.current is None)
    assert controller.dispatch({'action': 'bug_report_open', 'id': old_id}) == {'error': 'report_expired'}
    assert len(opened) == 1 and list(controller.store.db.execute('SELECT * FROM messages')) == before
    assert not page.console_errors


def test_browser_failure_keeps_report_and_copy_available_without_storage_error(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    monkeypatch.setattr(desktop.QDesktopServices, 'openUrl', lambda url: False)
    controller.dispatch({'action': 'setting', 'key': 'language', 'value': 'en'})
    wait_until(app, lambda: js(app, page, 'document.documentElement.lang') == 'en')
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('[data-report=app]').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#bug-report-open').disabled"))
    assert 'What happened?' in js(app, page, "document.querySelector('#bug-report-preview').textContent")
    js(app, page, "document.querySelector('#bug-report-open').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#bug-report-status').textContent.includes('Could not open')"))
    assert controller.bug_report.current and not controller.service.storage_error
    assert js(app, page, "!document.querySelector('#bug-report-copy').disabled")


def test_report_blocks_update_restart_until_closed(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    controller.restart_supported = True
    monkeypatch.setattr(controller.updates, 'enabled', True)
    monkeypatch.setattr(controller.updates, 'snapshot', lambda: {'state': 'ready'})
    assert controller.can_restart()
    result = controller.dispatch({'action': 'bug_report_prepare', 'area': 'app'})
    assert not controller.can_restart()
    assert controller.dispatch({'action': 'restart_update'}) == {'ok': False, 'reason': 'unavailable'}
    controller.dispatch({'action': 'bug_report_close'})
    assert controller.can_restart()
    assert controller.dispatch({'action': 'bug_report_copy', 'id': result['id']}) == {'error': 'report_expired'}


def test_report_does_not_claim_stale_chat_is_connected(qt_chat, monkeypatch):
    app, controller, page = qt_chat
    assert controller.service.state['connected'] is True
    monkeypatch.setattr(controller.service, 'clock', lambda: controller.service.updated + 3)
    result = controller.dispatch({'action': 'bug_report_prepare', 'area': 'app'})
    report = json.loads(result['body'].split('```json\n', 1)[1].split('\n```', 1)[0])
    assert report['chat']['connected'] is False


def test_report_actions_use_cached_content_and_reject_after_shutdown(tmp_path, monkeypatch):
    # This backend lifecycle check owns its controller. Do not close the shared
    # Qt fixture's controller while its live view/heartbeat still use it.
    app = desktop.QApplication.instance() or desktop.QApplication([])
    controller = desktop.Controller(tmp_path, offline=True)
    opened = []
    monkeypatch.setattr(desktop.QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()) or True)
    try:
        result = controller.dispatch({'action': 'bug_report_prepare', 'area': 'app'})
        forged = dict(id=result['id'], url='https://attacker.invalid', body='private-chat')
        assert controller.dispatch(dict(forged, action='bug_report_open')) == {'ok': True}
        assert opened[0].startswith(ISSUES + '?')
        assert parse_qs(urlsplit(opened[0]).query)['body'] == [result['body']]
        assert controller.dispatch(dict(forged, action='bug_report_copy')) == {'ok': True}
        assert app.clipboard().text() == result['body']
        controller.close()
        assert controller.bug_report.current is None
        assert controller.dispatch(dict(forged, action='bug_report_open')) == {'error': 'report_unavailable'}
        assert len(opened) == 1
    finally:
        controller.close()


@pytest.mark.parametrize('size', [(420, 500), (520, 700)])
@pytest.mark.parametrize('language', ['ko', 'en'])
def test_report_actions_remain_reachable_with_long_diagnostics(qt_chat, size, language):
    app, controller, page = qt_chat
    connection = failed_connection()
    for _ in range(3): connection._connect()
    controller.merge_connection = connection
    page.parent().resize(*size)
    assert (page.parent().width(), page.parent().height()) == size
    # Native resize and Chromium's viewport/layout updates are asynchronous.
    wait_until(app, lambda: js(app, page, f'innerWidth === {size[0]} && innerHeight === {size[1]}'))
    controller.dispatch({'action': 'setting', 'key': 'language', 'value': language})
    wait_until(app, lambda: js(app, page, 'document.documentElement.lang') == language)
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('[data-report=app]').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#bug-report-open').disabled"))
    js(app, page, """document.querySelector('#bug-report-dialog details').open=true;
      window.reportLayoutPainted=false;
      requestAnimationFrame(()=>requestAnimationFrame(()=>window.reportLayoutPainted=true));""")
    wait_until(app, lambda: js(app, page, 'window.reportLayoutPainted'))
    geometry = json.loads(js(app, page, """JSON.stringify((() => {
      const selectors=['#bug-report-open','#bug-report-copy','#bug-report-dialog .dialog-heading button'];
      return {width:innerWidth,height:innerHeight,buttons:selectors.map(selector=>{
        const button=document.querySelector(selector), r=button.getBoundingClientRect();
        const hit=document.elementFromPoint((r.left+r.right)/2,(r.top+r.bottom)/2);
        return {selector,top:r.top,bottom:r.bottom,left:r.left,right:r.right,
          visible:r.width>0 && r.height>0 && r.top>=0 && r.bottom<=innerHeight && r.left>=0 && r.right<=innerWidth,
          reachable:hit===button || button.contains(hit)};
      })};
    })())"""))
    assert all(button['visible'] and button['reachable'] for button in geometry['buttons']), geometry
