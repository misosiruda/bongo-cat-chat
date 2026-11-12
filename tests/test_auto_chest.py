"""Chest integration uses synthetic IPC and the actual Qt renderer; never the game."""
import json
import time

import pytest

from bongo_chat.auto_chest import AutoChest, DEFAULTS, observation, settings
from bongo_chat.merge_bridge import BridgeChannel
from bongo_chat.merge_connection import InteractiveAdapter, MergeConnection
from bongo_chat.store import Store
from test_desktop import qt_chat, js, wait_until
from test_merge_bridge import FileServer, until


@pytest.mark.parametrize('change', [dict(own=1), dict(others='true'), dict(min_delay=True),
    dict(min_delay=float('nan')), dict(max_delay=float('inf')), dict(min_delay=9,max_delay=8),
    dict(min_delay=0), dict(max_delay=301), dict(max_delay=10**1000), dict(own=False,others=False), dict(extra=True)])
def test_invalid_settings_are_rejected_before_dispatch(change):
    with pytest.raises(ValueError):settings(dict(DEFAULTS,**change))


def test_preferences_persist_without_a_running_flag_and_failed_save_keeps_old_value(tmp_path,monkeypatch):
    store=Store(tmp_path/'history.sqlite3')
    try:
        runner=AutoChest(store)
        assert runner.save(dict(DEFAULTS,others=True,min_delay=2))
        new=AutoChest(store)
        assert new.preferences['others'] and not new.snapshot()['armed']
        assert not new.start()
        def denied(*args):raise OSError('synthetic disk failure')
        monkeypatch.setattr(store,'setting',denied)
        with pytest.raises(OSError):new.save(DEFAULTS)
        assert new.preferences['others']
    finally:store.close()


def test_corrupt_preferences_do_not_break_chat_or_allow_start(tmp_path):
    store=Store(tmp_path/'history.sqlite3')
    try:
        store.setting('auto_chest',dict(DEFAULTS,max_delay='bad'))
        runner=AutoChest(store)
        assert not runner.preferences_valid and runner.preferences==DEFAULTS
        assert runner.save(DEFAULTS) and runner.preferences_valid
    finally:store.close()


def attach(controller,path):
    server=FileServer(path,interactive=True,chest=True)
    manager=MergeConnection(lambda:InteractiveAdapter(channel=BridgeChannel(path,verify_target=lambda config:None)))
    controller.merge_connection=manager
    controller.chests.connection=manager
    return server,manager


@pytest.mark.parametrize('reason,restart', [('legacy_unverified', False), ('result_unverified', True)])
def test_chest_reason_distinguishes_developer_investigation_from_unverified_consumption(qt_chat, monkeypatch, reason, restart):
    app, controller, page = qt_chat
    original = controller.chests.snapshot
    monkeypatch.setattr(controller.chests, 'snapshot', lambda:dict(original(), reason=reason, fresh=True,
        supported=True, can_start=False, unknown=restart))
    js(app,page,"document.querySelector('#chest-open').click()")
    wait_until(app,lambda:reason in js(app,page,"document.querySelector('#chest-reason').textContent"))
    message = js(app,page,"document.querySelector('#chest-reason').textContent")
    assert ('한 번 완전히 종료' in message) == restart
    assert ('개발 확인이 필요' in message) == (not restart)
    assert '앱 버전과 오류 코드' in message
    assert js(app,page,"document.querySelector('#chest-start').disabled")


def test_real_renderer_save_connect_takeover_start_stop_and_language(qt_chat,tmp_path):
    app,controller,page=qt_chat
    server,manager=attach(controller,tmp_path)
    try:
        js(app,page,"document.querySelector('#chest-open').click()")
        wait_until(app,lambda:js(app,page,"document.querySelector('#chest-dialog').open"))
        assert js(app,page,"document.querySelector('#chest-start').disabled")
        assert not server.requests
        js(app,page,"document.querySelector('#chest-others').click()")
        assert js(app,page,"document.querySelector('#chest-start').disabled && !document.querySelector('#chest-save').disabled")
        js(app,page,"document.querySelector('#chest-save').click()")
        wait_until(app,lambda:controller.chests.preferences['others'])
        assert not server.requests
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-connect').disabled"))
        js(app,page,"document.querySelector('#chest-connect').click()")
        wait_until(app,lambda:controller.chests.snapshot()['fresh'])
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-takeover-row').hidden"))
        assert js(app,page,"document.querySelector('#chest-start').disabled")
        js(app,page,"document.querySelector('#chest-takeover').click()")
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-start').disabled"))
        js(app,page,"document.querySelector('#chest-start').click()")
        wait_until(app,lambda:server.state['chest']['armed'])
        wait_until(app,lambda:js(app,page,"document.querySelector('#chest-state').textContent")=='자동 개봉 실행 중')
        assert controller.chests.blocks_restart
        assert json.loads(controller.request('{"action":"merge_start","limit":1}'))=={'ok':False,'auto_merge':controller.merger.snapshot()}
        assert json.loads(controller.request('{"action":"restart_update"}'))=={'ok':False,'reason':'auto_chest'}
        server.state['chest'].update(pending=True, reason='result_delayed')
        wait_until(app,lambda:js(app,page,"document.querySelector('#chest-state').textContent")=='개봉 응답 지연')
        assert '다음 상자를 자동으로' in js(app,page,"document.querySelector('#chest-reason').textContent")
        assert js(app,page,"document.querySelector('#chest-start').disabled && !document.querySelector('#chest-stop').disabled")
        server.state['chest'].update(pending=False, failed=1, reason='running')
        wait_until(app,lambda:js(app,page,"document.querySelector('#chest-state').textContent")=='자동 개봉 실행 중')
        assert sum(request['op'] == 'chest_start' for request in server.requests) == 1
        # Closing the panel does not stop; the sidebar retains an accessible stop.
        js(app,page,"document.querySelector('#chest-dialog').close()")
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-sidebar-stop').hidden"))
        wait_until(app,lambda:any(r['op']=='chest_heartbeat' for r in server.requests))
        js(app,page,"document.querySelector('#chest-sidebar-stop').click()")
        try:
            wait_until(app,lambda:not controller.chests.blocks_restart)
        except AssertionError:
            pytest.fail(str(dict(operations=[r['op'] for r in server.requests],
                                 state=controller.chests.snapshot(),
                                 fault=manager.adapter.fault, busy=manager.adapter.busy)))
        assert not any(r['op'] in {'begin','select','merge'} for r in server.requests)
        assert server.state['chest']['attempted']==0
        # A real language switch translates the new panel and retains saved settings.
        controller.dispatch(dict(action='setting',key='language',value='en'))
        js(app,page,"document.querySelector('#chest-open').click()")
        wait_until(app,lambda:js(app,page,"document.querySelector('#chest-title').textContent")=='Automatic chest opening')
        assert js(app,page,"document.querySelector('#chest-others').checked")
    finally:manager.close();server.close()


def test_heartbeat_only_follows_this_clients_explicit_start_and_close_stops(tmp_path):
    server=FileServer(tmp_path,interactive=True,chest=True)
    server.state['chest'].update(armed=True,enabled=True,reason='running')
    adapter=InteractiveAdapter(channel=BridgeChannel(tmp_path,verify_target=lambda config:None))
    try:
        until(lambda:adapter.chest_snapshot() is not None and adapter.chest_snapshot()['armed'])
        time.sleep(.9)
        assert not server.requests  # No adoption of an earlier run.
        adapter.chest_stop()
        until(lambda:not adapter.chest_snapshot()['armed'] and not adapter.busy)
        adapter.chest_start(DEFAULTS,True)
        until(lambda:any(r['op']=='chest_heartbeat' for r in server.requests))
        adapter.close();adapter.thread.join(5)
        assert server.requests[-1]['op']=='chest_stop'
        assert not server.state['chest']['armed']
    finally:adapter.close();server.close()


def test_stale_and_unknown_results_block_restart_and_never_claim_completion(tmp_path):
    store=Store(tmp_path/'history.sqlite3')
    server=FileServer(tmp_path,interactive=True,chest=True)
    raw=server.state['chest']
    try:
        raw.update(pending=True,unknown=True,reason='result_unverified')
        safe=observation(dict(raw,account='private',path='private'),time.monotonic()-5)
        class Connection:
            def chest_snapshot(self):return safe
        runner=AutoChest(store,Connection())
        value=runner.snapshot()
        assert not value['can_start'] and not value['fresh'] and runner.blocks_restart
        assert value['own_confirmed']==0 and 'account' not in value and 'path' not in value
        assert not runner.start() and not runner.save(DEFAULTS)
    finally:server.close();store.close()


def test_lost_stop_ack_is_reconciled_from_fresh_snapshot_without_retry(tmp_path,monkeypatch):
    server=FileServer(tmp_path,interactive=True,chest=True)
    channel=BridgeChannel(tmp_path,verify_target=lambda config:None)
    adapter=InteractiveAdapter(channel=channel)
    try:
        until(lambda:adapter.chest_snapshot() is not None)
        adapter.chest_start(DEFAULTS,True)
        until(lambda:adapter.chest_snapshot()['armed'] and not adapter.busy)
        original=channel.request
        def lost_ack(op,**kwargs):
            reply=original(op,**kwargs)
            if op=='chest_stop':raise RuntimeError('result_unverified')
            return reply
        monkeypatch.setattr(channel,'request',lost_ack)
        adapter.chest_stop()
        until(lambda:not adapter.busy and not adapter.chest_snapshot()['armed'])
        assert not adapter.fault and adapter.chest_snapshot()['supported']
        assert [r['op'] for r in server.requests].count('chest_stop')==1
    finally:adapter.close();server.close()


def test_known_start_refusal_is_visible_without_automatic_retry_or_permanent_lock(tmp_path,monkeypatch):
    from bongo_chat.merge_bridge import CommandRefused
    server=FileServer(tmp_path,interactive=True,chest=True)
    channel=BridgeChannel(tmp_path,verify_target=lambda config:None)
    adapter=InteractiveAdapter(channel=channel)
    try:
        until(lambda:adapter.chest_snapshot() is not None)
        original=channel.request
        attempts=[]
        def refused(op,**kwargs):
            if op=='chest_start':
                attempts.append(op)
                raise CommandRefused('legacy_busy')
            return original(op,**kwargs)
        monkeypatch.setattr(channel,'request',refused)
        adapter.chest_start(DEFAULTS,True)
        until(lambda:adapter.chest_snapshot()['reason']=='legacy_busy' and not adapter.busy)
        assert not adapter.fault and not adapter.chest_snapshot()['armed'] and attempts==['chest_start']
        monkeypatch.setattr(channel,'request',original)
        adapter.chest_start(DEFAULTS,True)
        until(lambda:server.state['chest']['armed'] and not adapter.busy)
        assert [r['op'] for r in server.requests].count('chest_start')==1
    finally:adapter.close();server.close()


def test_takeover_consent_expires_on_shared_connection_reconnect(qt_chat,tmp_path):
    app,controller,page=qt_chat
    server,manager=attach(controller,tmp_path)
    try:
        js(app,page,"document.querySelector('#chest-open').click()")
        assert controller.dispatch({'action':'chest_connect'})['ok']
        wait_until(app,lambda:controller.chests.snapshot()['fresh'])
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-takeover-row').hidden"))
        js(app,page,"document.querySelector('#chest-takeover').click()")
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-start').disabled"))
        js(app,page,"document.querySelector('#chest-start').click()")
        wait_until(app,lambda:server.state['chest']['armed'] and not manager.adapter.busy)
        controller.dispatch({'action':'chest_stop'})
        wait_until(app,lambda:not controller.chests.blocks_restart and not manager.adapter.busy)
        assert js(app,page,"document.querySelector('#chest-takeover').checked")
        # Synthetic replacement game lifetime, without restarting the messenger.
        server.state['chest'].update(legacy_taken_over=False,reason='ready')
        # The background server is the only snapshot writer. A test-side publish
        # would race its shared .tmp path and Windows readers' delete-sharing window.
        wait_until(app,lambda:not manager.chest_snapshot()['legacy_taken_over'])
        previous=manager.connection_snapshot()['revision']
        # The other automation panel can also replace this shared connection.
        assert controller.dispatch({'action':'merge_connect'})['ok']
        wait_until(app,lambda:manager.connection_snapshot()['state']=='connected' and controller.chests.snapshot()['fresh'])
        assert manager.connection_snapshot()['revision']==previous+1
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-takeover').checked && !document.querySelector('#chest-takeover-row').hidden"))
        assert js(app,page,"document.querySelector('#chest-start').disabled")
        assert [r['op'] for r in server.requests].count('chest_start')==1
        assert not any(r['op'] in {'select','merge'} for r in server.requests)
    finally:manager.close();server.close()


class LaunchConnection:
    def __init__(self, now):
        self.now = now
        self.state, self.revision = 'disconnected', 0
        self.connects, self.starts = 0, []
        self.value = dict(supported=True, armed=False, enabled=False, pending=False,
                          unknown=False, legacy_detected=False, legacy_taken_over=False, reason='ready')

    def connection_snapshot(self):
        return dict(state=self.state, revision=self.revision)

    def connect(self):
        self.connects += 1
        self.revision += 1
        self.state = 'connecting'
        return True

    def chest_snapshot(self):
        return dict(self.value, captured_at=self.now[0]) if self.state == 'connected' else None

    def chest_start(self, preferences, replace_legacy=False):
        self.starts.append((preferences, replace_legacy))

    def chest_stop(self):
        self.value.update(armed=False, enabled=False)


@pytest.fixture
def launch_runner(tmp_path):
    store = Store(tmp_path/'launch.sqlite3')
    now = [10.0]
    connection = LaunchConnection(now)
    store.setting('auto_chest', dict(DEFAULTS, start_on_launch=True))
    runner = AutoChest(store, connection, clock=lambda: now[0])
    yield runner, connection, now
    store.close()


def test_saved_launch_waits_for_game_then_connects_and_starts_exactly_once(launch_runner):
    runner, connection, now = launch_runner
    runner.tick_startup(False)
    assert not connection.connects and not connection.starts
    runner.tick_startup(True)
    runner.tick_startup(True)
    assert connection.connects == 1 and not connection.starts
    connection.state = 'connected'
    runner.tick_startup(False)
    assert not connection.starts
    runner.tick_startup(True)
    assert connection.starts == [(DEFAULTS, False)]  # Startup flag never crosses native IPC.
    connection.value.update(armed=True, enabled=True)
    runner.stop()
    connection.state = 'disconnected'
    for _ in range(10):runner.tick_startup(True)
    assert connection.connects == 1 and len(connection.starts) == 1
    assert runner.start_on_launch and not runner.startup_pending


@pytest.mark.parametrize('interruption', ['stop', 'close', 'blocked', 'error', 'revision', 'pending', 'unknown', 'armed', 'unsupported'])
def test_launch_is_not_retried_after_stop_error_or_conflict(launch_runner, interruption):
    runner, connection, now = launch_runner
    runner.tick_startup(True)
    connection.state = 'connected'
    if interruption == 'stop':runner.stop()
    elif interruption == 'close':runner.close()
    elif interruption == 'error':connection.state = 'error'
    elif interruption == 'revision':connection.revision += 1
    elif interruption == 'unsupported':connection.value['supported'] = False
    elif interruption != 'blocked':connection.value[interruption] = True
    runner.tick_startup(True, blocked=interruption == 'blocked')
    connection.state = 'connected'
    connection.value.update(supported=True, pending=False, unknown=False, armed=False)
    for _ in range(5):runner.tick_startup(True)
    assert not connection.starts and connection.connects == 1 and not runner.startup_pending


def test_legacy_helper_still_requires_current_game_confirmation(launch_runner):
    runner, connection, now = launch_runner
    connection.state = 'connected'
    connection.value['legacy_detected'] = True
    for _ in range(5):runner.tick_startup(True)
    assert runner.startup_status == 'confirmation_required' and not connection.starts
    assert runner.start(True)
    assert connection.starts == [(DEFAULTS, True)] and not runner.startup_pending


def test_failed_launch_submission_and_stale_observation_are_not_retried(launch_runner):
    runner, connection, now = launch_runner
    connection.state = 'connected'
    calls = []
    def failed(*args):
        calls.append(args)
        raise RuntimeError('synthetic lost start')
    connection.chest_start = failed
    for _ in range(5):runner.tick_startup(True)
    assert len(calls) == 1 and runner.startup_status == 'failed'
    reopened = AutoChest(runner.store,connection,clock=lambda:now[0])
    connection.chest_snapshot = lambda: None
    reopened.tick_startup(True)
    now[0] += 10
    reopened.tick_startup(True)
    assert not reopened.startup_pending and reopened.startup_status == 'failed'
    assert len(calls) == 1


def test_launch_connection_exception_is_contained_without_retry(launch_runner):
    runner, connection, now = launch_runner
    calls = []
    def failed():
        calls.append(True)
        raise RuntimeError('synthetic thread startup failure')
    connection.connect = failed
    for _ in range(5):runner.tick_startup(True)
    assert calls == [True] and runner.startup_status == 'failed' and not runner.startup_pending


def test_enabling_launch_only_applies_after_reopening_and_invalid_consent_fails_closed(tmp_path):
    store = Store(tmp_path/'launch.sqlite3')
    try:
        connection = LaunchConnection([10.0])
        runner = AutoChest(store, connection)
        assert runner.save(dict(DEFAULTS, start_on_launch=True))
        runner.tick_startup(True)
        assert not connection.connects and not runner.startup_pending
        reopened = AutoChest(store, connection)
        assert reopened.startup_pending
        assert not AutoChest(store).startup_pending  # Offline/read-only: no connection.
        with pytest.raises(ValueError):reopened.save(dict(DEFAULTS, start_on_launch=1))
        store.setting('auto_chest', dict(DEFAULTS, start_on_launch='true'))
        invalid = AutoChest(store, connection)
        assert not invalid.preferences_valid and not invalid.startup_pending
    finally:store.close()


def test_real_renderer_saves_launch_opt_in_and_offers_stop_while_waiting(qt_chat,tmp_path):
    app,controller,page = qt_chat
    server,manager = attach(controller,tmp_path)
    try:
        js(app,page,"document.querySelector('#chest-open').click()")
        wait_until(app,lambda:js(app,page,"!document.querySelector('#chest-autostart').checked"))
        js(app,page,"document.querySelector('#chest-autostart').click();document.querySelector('#chest-save').click()")
        wait_until(app,lambda:controller.chests.start_on_launch)
        assert not server.requests and manager.state == 'disconnected'
        # Reconstruct only the app controller's chest component; all IPC remains synthetic.
        controller.chests = AutoChest(controller.store,manager)
        wait_until(app,lambda:controller.chests.startup_status=='confirmation_required')
        assert not any(r['op']=='chest_start' for r in server.requests)
        wait_until(app,lambda:js(app,page,"document.querySelector('#chest-state').textContent")=='전환 확인 필요')
        assert js(app,page,"document.querySelector('#chest-autostart').checked && !document.querySelector('#chest-stop').disabled")
        js(app,page,"document.querySelector('#chest-stop').click()")
        wait_until(app,lambda:not controller.chests.startup_pending)
        assert controller.store.setting('auto_chest')['start_on_launch'] is True
        assert not any(r['op']=='chest_start' for r in server.requests)
        controller.dispatch(dict(action='setting',key='language',value='en'))
        wait_until(app,lambda:js(app,page,"document.querySelector('label:has(#chest-autostart)').textContent.trim()")=='Start opening chests when the app launches')
        assert not page.console_errors
    finally:manager.close();server.close()


def test_saved_launch_reaches_native_ipc_once_without_a_legacy_helper(qt_chat,tmp_path):
    app,controller,page = qt_chat
    server,manager = attach(controller,tmp_path)
    try:
        server.state['chest']['legacy_detected'] = False
        controller.store.setting('auto_chest',dict(DEFAULTS,start_on_launch=True))
        controller.chests = AutoChest(controller.store,manager)
        wait_until(app,lambda:server.state['chest']['armed'])
        wait_until(app,lambda:any(r['op']=='chest_heartbeat' for r in server.requests))
        starts = [r for r in server.requests if r['op']=='chest_start']
        assert len(starts)==1 and starts[0]['chest_settings']==DEFAULTS and not starts[0]['replace_legacy']
        controller.dispatch(dict(action='chest_stop'))
        wait_until(app,lambda:not server.state['chest']['armed'] and not manager.adapter.busy)
        controller.dispatch(dict(action='chest_connect'))
        wait_until(app,lambda:manager.state=='connected' and controller.chests.snapshot()['fresh'])
        assert len([r for r in server.requests if r['op']=='chest_start'])==1
        assert not server.state['chest']['attempted']  # Fake IPC only, no real chest.
    finally:manager.close();server.close()
