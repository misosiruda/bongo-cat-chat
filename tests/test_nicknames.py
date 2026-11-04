"""Private display names using synthetic Steam IDs and an offline Qt bridge."""
import json
import sqlite3

import pytest

from bongo_chat.service import ChatService
from bongo_chat.store import Store
from test_core import received
from test_desktop import arm_automatic_restart, js, wait_until
from test_profile_desktop import profile_controller, profile_ui
from test_profiles import PEER, SECOND, SELF, profile_service, profile_state
from test_reactions import reaction


def test_nickname_overlays_same_name_peers_history_presence_and_blocks(profile_service):
    service = profile_service
    received(service, '같은 본문', sender=PEER)
    received(service, '같은 본문', sender=SECOND)
    service.set_nickname(PEER, '  단짝 🐾  ', service.context())
    profile = dict(service.state['profiles'], **{PEER: {'name': '바뀐 이름'}})
    service.update(profile_state(profiles=profile))
    view = service.view(query='본문')
    assert [row['name'] for row in view['messages']] == ['단짝 🐾', '동일 이름']
    assert view['profiles'][PEER]['name'] == '단짝 🐾'
    assert view['participants'][PEER]['name'] == '바뀐 이름'
    assert service.state['profiles'][PEER]['name'] == '바뀐 이름'
    service.update(profile_state(members=[SELF, SECOND]))
    assert service.view()['messages'][-1]['kind'] == 'member_left'
    assert service.view()['messages'][-1]['name'] == '단짝 🐾'
    old_room = service.context()['lobby']
    service.update(profile_state(lobby='next-room', generation='next'))
    service.set_blocked(PEER, True, SELF)
    assert service.view()['blocked_users'] == [dict(steam_id=PEER, name='단짝 🐾')]
    assert PEER not in service.view()['profiles']
    assert [row['sender'] for row in service.view(old_room)['messages']] == [SECOND]
    service.set_blocked(PEER, False, SELF)
    assert service.view(old_room)['messages'][0]['name'] == '단짝 🐾'
    service.set_nickname(PEER, '', service.context())
    assert [row['name'] for row in service.view(old_room)['messages']] == ['동일 이름', '동일 이름', '바뀐 이름']


def test_existing_database_restart_account_isolation_and_clear(tmp_path):
    path = tmp_path / 'fixture.sqlite3'
    store = Store(path)
    service = ChatService(store, clock=lambda: 100)
    service.update(profile_state())
    received(service, '기존 대화', sender=PEER)
    store.db.execute('DROP TABLE nicknames')  # An existing schema-1 database without nicknames.
    store.close()
    store = Store(path)
    service = ChatService(store, clock=lambda: 100)
    service.update(profile_state())
    service.set_nickname(PEER, '내 친구', service.context())
    assert service.view()['messages'][0]['name'] == '내 친구'
    service.forget(SELF)
    store.prune()
    store.close()
    store = Store(path)
    try:
        service = ChatService(store, clock=lambda: 100)
        service.update(profile_state(lobby='another-room'))
        assert service.view()['profiles'][PEER]['name'] == '내 친구'
        service.update(profile_state(account=SECOND))
        assert service.view()['profiles'][PEER]['name'] == '동일 이름'
        service.set_nickname(PEER, '다른 별명', service.context())
        service.update(profile_state())
        assert service.view()['profiles'][PEER]['name'] == '내 친구'
        service.set_nickname(PEER, ' ', service.context())
        assert store.nicknames(SELF) == {}
        assert store.nicknames(SECOND) == {PEER: '다른 별명'}
    finally:
        store.close()


@pytest.mark.parametrize('uid,value', [(SELF, 'x'), (int(PEER), 'x'), ('123', 'x'), (PEER, None),
                                      (PEER, '냥' * 33), (PEER, 'a\nb'), (PEER, '\ud800')])
def test_invalid_nickname_requests_leave_committed_name(profile_service, uid, value):
    service = profile_service
    service.set_nickname(PEER, '🐾' * 32, service.context())
    with pytest.raises(ValueError):
        service.set_nickname(uid, value, service.context())
    assert service.store.nicknames(SELF) == {PEER: '🐾' * 32}


def test_stale_target_and_failed_write_do_not_change_nickname(profile_service, monkeypatch):
    service = profile_service
    context = service.context()
    service.set_nickname(PEER, '친구', context)
    service.update(profile_state(generation='new'))
    with pytest.raises(ValueError, match='nickname_unavailable'):
        service.set_nickname(PEER, '다른 이름', context)
    def fail(*args):
        raise sqlite3.OperationalError('fixture')
    monkeypatch.setattr(service.store, 'set_nickname', fail)
    with pytest.raises(sqlite3.Error):
        service.set_nickname(PEER, '', service.context())
    assert service.view()['profiles'][PEER]['name'] == '친구'
    monkeypatch.setattr(service.store, 'nicknames', fail)
    service.update(profile_state(account=SECOND))
    assert not service.view()['nicknames_ready']
    assert service.view()['profiles'][PEER]['name'] == '동일 이름'


def test_participant_editor_changes_only_local_labels_and_restores_original(profile_ui):
    app, controller, page, calls, _ = profile_ui
    def run(code):
        return js(app, page, code)
    def open_editor():
        run(f"document.getElementById('participant-more-{PEER}').click();document.querySelector('.nickname-action').click()")
        assert run("document.activeElement.id") == 'nickname-input'
    def submit(value):
        run(f"document.getElementById('nickname-input').value={json.dumps(value)};document.getElementById('nickname-save').click()")

    run("document.getElementById('message-input').value='작성 중';document.getElementById('participants-button').click()")
    open_editor()
    submit('x' * 33)
    wait_until(app, lambda: run("document.getElementById('nickname-error').textContent.includes('32')"))
    submit('<별명>🐈')
    wait_until(app, lambda: not run("document.getElementById('nickname-dialog').open"))
    names = run("JSON.stringify([...document.querySelectorAll('.message-meta strong')].map(el=>el.textContent))")
    assert json.loads(names) == ['<별명>🐈', '동일 이름', '시험 계정']
    assert run("document.querySelector('.participant-name + .participant-more').previousElementSibling.textContent") == '<별명>🐈'
    service = controller.service
    service.receive_reaction(reaction(service, sender=PEER, observed=service.clock()))
    wait_until(app, lambda: run("document.querySelector('.reaction-name')?.textContent") == '<별명>🐈')
    open_editor()
    assert run("document.getElementById('nickname-input').value") == '<별명>🐈'
    assert '동일 이름' in run("document.getElementById('nickname-person').textContent")
    run("document.getElementById('nickname-input').value='취소할 이름';document.getElementById('nickname-cancel').click()")
    assert controller.store.nicknames(SELF) == {PEER: '<별명>🐈'}
    open_editor()
    submit('')
    wait_until(app, lambda: not run("document.getElementById('nickname-dialog').open"))
    assert run("document.querySelector('.profile-name strong').textContent") == '동일 이름'
    assert run("document.getElementById('message-input').value") == '작성 중'
    assert not calls and controller.worker is None


def test_editor_discards_unsubmitted_change_when_account_switches(profile_ui):
    app, controller, page, _, _ = profile_ui
    service = controller.service
    service.set_nickname(PEER, '첫 별명', service.context())
    service.set_nickname(PEER, '수정한 별명', service.context())
    wait_until(app, lambda: js(app, page, "document.querySelector('.profile-name strong').textContent") == '수정한 별명')
    js(app, page, f"document.getElementById('participants-button').click();document.getElementById('participant-more-{PEER}').click();"
                  "document.querySelector('.nickname-action').click();document.getElementById('nickname-input').value='저장 전'")
    previous = service.context()
    service.update(profile_state(account=SECOND))
    result = controller.request(json.dumps(dict(action='set_nickname', steam_id=PEER, nickname='저장 전', context=previous)))
    assert json.loads(result) == {'error': 'nickname_unavailable'}
    wait_until(app, lambda: not js(app, page, "document.getElementById('nickname-dialog').open"))
    assert controller.store.nicknames(SELF) == {PEER: '수정한 별명'}
    assert controller.store.nicknames(SECOND) == {}


def test_update_countdown_starts_again_after_nickname_editor_closes(profile_ui):
    app, controller, page, _, _ = profile_ui
    arm_automatic_restart(app, controller, page)
    js(app, page, f"document.getElementById('participants-button').click();document.getElementById('participant-more-{PEER}').click();"
                  "document.querySelector('.nickname-action').click();window.timeOffset+=31000")
    wait_until(app, lambda: js(app, page, "document.getElementById('update-notice').textContent.includes('별명 편집')"))
    assert not controller.restarting
    js(app, page, "document.getElementById('nickname-cancel').click()")
    wait_until(app, lambda: js(app, page, "document.getElementById('update-notice').textContent.includes('초 후')"))
    assert not controller.restarting
    js(app, page, "window.timeOffset+=31000")
    wait_until(app, lambda: controller.restarting)
