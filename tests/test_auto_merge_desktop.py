"""Real Qt bridge/renderer, synthetic adapter; never sends game input."""
import json
import time
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from bongo_chat.auto_merge import AutoMerge
from bongo_chat.desktop import Controller
from merge_fixture import FakeGameUI
from test_desktop import js, qt_chat, wait_until


def request(controller, action, **args):
    return json.loads(controller.request(json.dumps(dict(action=action, **args))))


def test_offline_and_readonly_have_no_input_path(tmp_path):
    app = QApplication.instance() or QApplication([])
    for index, read_only in enumerate((False, True)):
        data = tmp_path / str(index); data.mkdir()
        game = FakeGameUI(time.monotonic)
        controller = Controller(data, offline=True, read_only=read_only,
            merge_adapter=game if read_only else None)
        try:
            controller.poll()
            view = request(controller, 'view')['auto_merge']
            assert view['reason'] == ('read_only' if read_only else 'offline')
            assert not request(controller, 'merge_start', limit=10)['ok']
            assert request(controller, 'merge_start', limit=True) == {'error': 'request_failed'}
            assert game.calls == []
        finally:
            controller.close(); app.processEvents()


def test_update_restart_is_blocked_until_pending_result_is_resolved(qt_chat):
    app, controller, page = qt_chat
    now = [100.0]
    game = FakeGameUI(lambda: now[0])
    controller.merger = runner = AutoMerge(game, clock=lambda: now[0])
    controller.restart_supported = True
    controller.updates.enabled = True
    controller.updates.snapshot = lambda: dict(state='ready', version='synthetic-next', allowed=True)
    assert controller.can_restart()
    assert request(controller, 'merge_start', limit=1)['ok']
    runner.tick(); game.selected(); runner.tick(); runner.tick()
    assert not controller.can_restart()
    assert request(controller, 'restart_update') == {'ok': False, 'reason': 'auto_merge'}
    view = request(controller, 'view')
    assert view['update']['merge_deferred'] and view['auto_merge']['pending'] == 1
    now[0] += 31; runner.tick()
    assert runner.unresolved
    assert request(controller, 'restart_update') == {'ok': False, 'reason': 'auto_merge'}
    request(controller, 'merge_acknowledge')
    assert controller.can_restart() and not controller.restarting
    assert len(game.calls) == 2
    # Avoid a real app restart during fixture teardown/refresh.
    controller.restart_supported = False


def test_panel_keeps_chat_draft_and_running_stop_accessible(qt_chat):
    app, controller, page = qt_chat
    game = FakeGameUI(time.monotonic)
    controller.merger = runner = AutoMerge(game)
    js(app, page, "document.querySelector('#message-input').value='보존할 초안';document.querySelector('#message-input').dispatchEvent(new Event('input'));document.querySelector('#merge-open').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#merge-start').disabled"))
    assert js(app, page, "document.querySelector('#merge-favorites').textContent") == '꺼짐'
    js(app, page, "document.querySelector('#merge-start').click()")
    wait_until(app, lambda: len(game.calls) == 1)
    assert runner.active
    js(app, page, "document.querySelector('#merge-dialog').close();document.querySelector('#sidebar-toggle').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#merge-run-bar').hidden"))
    assert js(app, page, "document.querySelector('#merge-sidebar-stop').getBoundingClientRect().width") > 0
    assert js(app, page, "document.querySelector('#message-input').value") == '보존할 초안'
    assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 1
    js(app, page, "document.querySelector('#merge-run-stop').click()")
    wait_until(app, lambda: runner.state == 'stopped')
    assert [call[0] for call in game.calls] == ['select']


def test_unknown_result_and_language_switch_preserve_truth(qt_chat):
    app, controller, page = qt_chat
    now = [100.0]
    game = FakeGameUI(lambda: now[0])
    controller.merger = runner = AutoMerge(game, clock=lambda: now[0])
    runner.start(1); runner.tick(); game.selected(); runner.tick(); runner.tick()
    now[0] += 31; runner.tick()
    js(app, page, "document.querySelector('#merge-open').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#merge-acknowledge').hidden"))
    assert js(app, page, "document.querySelector('#merge-start').disabled")
    assert js(app, page, "document.querySelector('#merge-completed').textContent") == '0'
    assert js(app, page, "document.querySelector('#merge-pending').textContent") == '1'
    request(controller, 'setting', key='language', value='en')
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-title').textContent") == 'Auto merge items')
    assert js(app, page, "document.querySelector('#merge-state').textContent") == 'Result unknown · session stopped'
    js(app, page, "document.querySelector('#merge-acknowledge').click()")
    wait_until(app, lambda: not runner.unresolved)
    assert runner.completed == 0 and len(game.calls) == 2


def test_maximum_button_populates_arbitrary_count_without_starting(qt_chat):
    app, controller, page = qt_chat
    game = FakeGameUI(time.monotonic)
    game.value = replace(game.value, available_exchanges=137)
    controller.merger = runner = AutoMerge(game)
    js(app, page, "document.querySelector('#merge-open').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#merge-maximum').disabled"))
    assert js(app, page, "document.querySelector('#merge-available').textContent") == '137회'
    js(app, page, "document.querySelector('#merge-maximum').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-limit').value") == '137')
    assert js(app, page, "document.querySelector('#merge-planned').textContent") == '이번 실행 예정: 최대 137회'
    assert not game.calls and not runner.active
    game.value = replace(game.value, available_exchanges=23)
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-planned').textContent") == '이번 실행 예정: 최대 23회')
    assert js(app, page, "document.querySelector('#merge-limit').value") == '137'
    js(app, page, "document.querySelector('#merge-maximum').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-limit').value") == '23')
    js(app, page, "document.querySelector('#merge-start').click()")
    wait_until(app, lambda: runner.active)
    assert runner.limit == 23
    assert js(app, page, "document.querySelector('#merge-maximum').disabled")


def test_maximum_unknown_zero_and_invalid_limit_ui(qt_chat):
    app, controller, page = qt_chat
    game = FakeGameUI(time.monotonic)
    controller.merger = runner = AutoMerge(game)
    js(app, page, "document.querySelector('#merge-open').click()")
    wait_until(app, lambda: runner.observation is not None)
    assert js(app, page, "document.querySelector('#merge-maximum').disabled")
    assert js(app, page, "document.querySelector('#merge-available').textContent") == '확인 필요'
    game.value = replace(game.value, available_exchanges=0, can_select=False)
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-available').textContent") == '0회')
    assert js(app, page, "document.querySelector('#merge-maximum').disabled && document.querySelector('#merge-start').disabled")
    game.value = replace(game.value, available_exchanges=23, can_select=True)
    wait_until(app, lambda: js(app, page, "!document.querySelector('#merge-maximum').disabled"))
    js(app, page, "document.querySelector('#merge-limit').value='1.5';document.querySelector('#merge-limit').dispatchEvent(new Event('input'))")
    assert js(app, page, "document.querySelector('#merge-start').disabled")
    assert '정수' in js(app, page, "document.querySelector('#merge-planned').textContent")
    assert not game.calls


def test_group_label_and_maximum_do_not_carry_across_groups(qt_chat):
    app, controller, page = qt_chat
    game = FakeGameUI(time.monotonic)
    game.value = replace(game.value, available_exchanges=23)
    controller.merger = AutoMerge(game)
    js(app, page, "document.querySelector('#merge-open').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-group').textContent") == '캐릭터·모자·봉고')
    assert js(app, page, "document.querySelector('#merge-target-group').value") == 'cosmetics'
    js(app, page, "document.querySelector('#merge-maximum').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-limit').value") == '23')
    # A changed game tab with an old cosmetics count must not expose that count.
    game.value = replace(game.value, category='emotes')
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-group').textContent") == '이모티콘·UI 테마')
    assert js(app, page, "document.querySelector('#merge-limit').value") == ''
    assert js(app, page, "document.querySelector('#merge-available').textContent") == '확인 필요'
    assert js(app, page, "document.querySelector('#merge-maximum').disabled && document.querySelector('#merge-start').disabled")
    game.value = replace(game.value, available_group='emotes', available_exchanges=5)
    wait_until(app, lambda: js(app, page, "!document.querySelector('#merge-maximum').disabled"))
    js(app, page, "document.querySelector('#merge-maximum').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#merge-limit').value") == '5')
    assert js(app, page, "document.querySelector('#merge-available-label').textContent") == '이모티콘·UI 테마 그룹에서 합성 가능'
    assert not game.calls


def test_group_selector_uses_app_command_and_clears_previous_maximum(qt_chat):
    app, controller, page = qt_chat
    game = FakeGameUI(time.monotonic)
    game.value = replace(game.value,available_exchanges=23)
    controller.merger = AutoMerge(game)
    js(app,page,"document.querySelector('#merge-open').click()")
    wait_until(app,lambda:js(app,page,"!document.querySelector('#merge-target-group').disabled"))
    js(app,page,"document.querySelector('#merge-maximum').click()")
    wait_until(app,lambda:js(app,page,"document.querySelector('#merge-limit').value")=='23')
    js(app,page,"document.querySelector('#merge-target-group').value='emotes';document.querySelector('#merge-target-group').dispatchEvent(new Event('change'))")
    wait_until(app,lambda:js(app,page,"document.querySelector('#merge-available').textContent")=='5회')
    assert js(app,page,"document.querySelector('#merge-limit').value") == ''
    assert game.calls == [('group','emotes')]
    assert not controller.merger.active
