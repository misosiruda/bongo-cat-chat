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
    server.publish()
    adapter=InteractiveAdapter(channel=BridgeChannel(tmp_path,verify_target=lambda config:None))
    try:
        until(lambda:adapter.chest_snapshot() is not None)
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
            if op=='chest_stop':raise RuntimeError('synthetic lost acknowledgement')
            return reply
        monkeypatch.setattr(channel,'request',lost_ack)
        adapter.chest_stop()
        until(lambda:adapter.fault and not adapter.chest_snapshot()['armed'])
        assert not adapter.chest_snapshot()['supported']  # Explicit reconnect is required before starting.
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
        server.publish()
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
