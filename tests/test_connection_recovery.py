"""Fault injection against the real file channel; synthetic game only."""
import time

import pytest

from bongo_chat.auto_merge import AutoMerge, InputRefused
from bongo_chat.auto_chest import DEFAULTS
from bongo_chat.merge_bridge import BridgeChannel, CommandDeferred
from bongo_chat.merge_connection import InteractiveAdapter
from test_merge_bridge import FileServer, until


@pytest.fixture
def bridge(tmp_path):
    server = FileServer(tmp_path, interactive=True, chest=True)
    channel = BridgeChannel(tmp_path, verify_target=lambda config: None)
    adapter = InteractiveAdapter(channel=channel)
    until(lambda: adapter.observe().ready and adapter.chest_snapshot() is not None)
    yield server, channel, adapter
    adapter.close()
    adapter.thread.join(5)
    server.close()


def test_inventory_refresh_keeps_heartbeats_and_recovers_without_another_start(bridge):
    server, channel, adapter = bridge
    adapter.chest_start(DEFAULTS, True)
    until(lambda: adapter.chest_owns_lease and not adapter.busy)
    before = len([r for r in server.requests if r['op'] == 'chest_heartbeat'])
    server.state.update(ready=False, reason='inventory_refreshing')
    server.state['chest']['reason'] = 'inventory_refreshing'
    until(lambda: len([r for r in server.requests if r['op'] == 'chest_heartbeat']) > before)
    assert not adapter.fault and adapter.chest_snapshot()['armed']
    server.state.update(ready=True, reason='ready')
    server.state['chest']['reason'] = 'running'
    until(lambda: adapter.observe().ready and adapter.chest_snapshot()['reason'] == 'running')
    assert [r['op'] for r in server.requests].count('chest_start') == 1
    heartbeats = [r for r in server.requests if r['op'] == 'chest_heartbeat']
    assert all(r['chest_run_attempt'] == server.state['chest']['run_attempt'] for r in heartbeats)


def test_snapshot_outage_then_recovery_keeps_owned_chest_run(bridge, monkeypatch):
    server, channel, adapter = bridge
    adapter.chest_start(DEFAULTS, True)
    until(lambda: adapter.chest_owns_lease and not adapter.busy)
    original = channel.snapshot
    def unavailable():raise PermissionError('synthetic sharing conflict')
    initial_heartbeats=len([r for r in server.requests if r['op']=='chest_heartbeat'])
    monkeypatch.setattr(channel, 'snapshot', unavailable)
    time.sleep(1.7)
    assert time.monotonic() - adapter.chest_snapshot()['captured_at'] > 1.5
    assert len([r for r in server.requests if r['op']=='chest_heartbeat'])>initial_heartbeats
    before = len(server.requests)
    monkeypatch.setattr(channel, 'snapshot', original)
    until(lambda: len(server.requests) > before and server.requests[-1]['op'] == 'chest_heartbeat')
    assert not adapter.fault and adapter.chest_snapshot()['armed']
    assert [r['op'] for r in server.requests].count('chest_start') == 1


def test_heartbeat_never_waits_for_rpc_ack_or_starves_observations(bridge, monkeypatch):
    server, channel, adapter = bridge
    original=channel.request
    calls=[]
    def request(op, **kwargs):
        calls.append(op)
        if op=='chest_heartbeat':raise AssertionError('heartbeat must not use RPC')
        return original(op, **kwargs)
    monkeypatch.setattr(channel,'request',request)
    server.drop_responses.add('chest_heartbeat')
    adapter.chest_start(DEFAULTS,True)
    until(lambda:len([r for r in server.requests if r['op']=='chest_heartbeat'])>=3)
    assert 'chest_heartbeat' not in calls and not adapter.fault
    assert time.monotonic()-adapter.observe().captured_at<1.5
    assert server.state['chest']['armed'] and adapter.chest_owns_lease
    assert (channel.session/'heartbeat.json').is_file()


def test_stop_during_outage_cancels_heartbeat_and_is_delivered_after_recovery(bridge, monkeypatch):
    server, channel, adapter = bridge
    adapter.chest_start(DEFAULTS, True)
    until(lambda: adapter.chest_owns_lease and not adapter.busy)
    original = channel.snapshot
    def unavailable():raise PermissionError('synthetic sharing conflict')
    monkeypatch.setattr(channel, 'snapshot', unavailable)
    adapter.chest_stop()
    until(lambda: not adapter.chest_owns_lease and adapter.busy)
    time.sleep(.6)
    before = len([r for r in server.requests if r['op'] == 'chest_heartbeat'])
    monkeypatch.setattr(channel, 'snapshot', original)
    until(lambda: not adapter.busy and not adapter.chest_snapshot()['armed'])
    time.sleep(.8)
    assert len([r for r in server.requests if r['op'] == 'chest_heartbeat']) == before
    assert server.requests[-1]['op'] == 'chest_stop' and not adapter.fault


def test_lost_chest_start_ack_is_confirmed_by_exact_run_without_restarting(bridge, monkeypatch):
    server, channel, adapter = bridge
    original = channel.request
    def lost_ack(op, **kwargs):
        result = original(op, **kwargs)
        if op == 'chest_start':raise RuntimeError('result_unverified')
        return result
    monkeypatch.setattr(channel, 'request', lost_ack)
    adapter.chest_start(DEFAULTS, True)
    until(lambda: any(r['op'] == 'chest_heartbeat' for r in server.requests))
    assert not adapter.fault and adapter.chest_owns_lease
    assert [r['op'] for r in server.requests].count('chest_start') == 1


def test_lost_merge_ack_is_reconciled_without_duplicate_consumption(bridge):
    server, channel, adapter = bridge
    server.drop_responses.add('merge')
    runner = AutoMerge(adapter)
    assert runner.start(2)
    def done():runner.tick(); return not runner.active
    until(done, timeout=12)
    assert runner.completed == 2 and runner.state == 'completed' and not adapter.fault
    merges = [r for r in server.requests if r['op'] == 'merge']
    assert len(merges) == 2 and len({r['operation_id'] for r in merges}) == 2
    assert server.state['spent'] == 2


def test_definitely_unsent_selection_retries_then_completes_once(bridge, monkeypatch):
    server, channel, adapter = bridge
    original = channel.request
    failures = []
    def deferred(op, **kwargs):
        if op == 'select' and len(failures) < 2:
            failures.append(kwargs['attempt'])
            raise CommandDeferred('inventory_refreshing')
        return original(op, **kwargs)
    monkeypatch.setattr(channel, 'request', deferred)
    runner = AutoMerge(adapter)
    assert runner.start(1)
    def done():runner.tick(); return not runner.active
    until(done)
    assert runner.completed == 1 and len(set(failures)) == 1
    assert [r['op'] for r in server.requests] == ['begin', 'select', 'merge']


def test_stop_cancels_deferred_selection_instead_of_delivering_it_later(bridge, monkeypatch):
    server, channel, adapter = bridge
    original = channel.request
    waiting = []
    def deferred(op, **kwargs):
        if op == 'select':
            waiting.append(True)
            raise CommandDeferred('inventory_refreshing')
        return original(op, **kwargs)
    monkeypatch.setattr(channel, 'request', deferred)
    runner = AutoMerge(adapter)
    assert runner.start(1)
    def submitted():runner.tick(); return bool(waiting)
    until(submitted)
    runner.stop()
    monkeypatch.setattr(channel, 'request', original)
    until(lambda: any(r['op'] == 'stop' for r in server.requests))
    runner.tick()
    assert runner.state == 'stopped' and server.state['spent'] == 0
    assert all(r['op'] not in {'select', 'merge'} for r in server.requests)


def test_close_releases_own_idle_selection_without_consuming(bridge):
    server, channel, adapter = bridge
    runner = AutoMerge(adapter)
    assert runner.start(1)
    def selected():
        runner.tick()
        return runner.state == 'merging'
    until(selected)
    runner.close()
    adapter.thread.join(5)
    assert server.state['spent'] == 0 and server.state['selected_units'] == 0
    assert server.state['run_attempt'] == ''
    assert [r['op'] for r in server.requests] == ['begin', 'select', 'stop']


def test_stop_cancels_definitely_unsent_merge_without_claiming_unknown_result(bridge, monkeypatch):
    server, channel, adapter = bridge
    original = channel.request
    waiting = []
    def deferred(op, **kwargs):
        if op == 'merge':
            waiting.append(True)
            raise CommandDeferred('inventory_refreshing')
        return original(op, **kwargs)
    monkeypatch.setattr(channel, 'request', deferred)
    runner = AutoMerge(adapter)
    assert runner.start(1)
    def submitted():runner.tick(); return bool(waiting)
    until(submitted)
    assert runner.pending_attempt
    runner.stop()
    monkeypatch.setattr(channel, 'request', original)
    def stopped():runner.tick(); return runner.state == 'stopped'
    until(stopped)
    until(lambda: server.state['selected_units'] == 0)
    assert not runner.unresolved and runner.completed == 0 and server.state['spent'] == 0
    assert [r['op'] for r in server.requests] == ['begin', 'select', 'stop']


@pytest.mark.parametrize('failure', ['protection_change', 'refused_before_dispatch'])
def test_terminal_failure_releases_selection_and_run_without_consuming(bridge, monkeypatch, failure):
    server, channel, adapter = bridge
    runner = AutoMerge(adapter)
    assert runner.start(1)
    def selected():
        runner.tick()
        return runner.state == 'merging'
    until(selected)
    if failure == 'protection_change':
        server.state['favorites_allowed'] = True
        until(lambda: adapter.observe().favorites_allowed is True)
    else:
        def refuse(*args):raise InputRefused
        monkeypatch.setattr(adapter, 'merge', refuse)
    runner.tick()
    assert runner.state == 'failed'
    assert runner.reason == ('settings_changed' if failure == 'protection_change' else 'input_failed')
    until(lambda: server.state['run_attempt'] == '' and server.state['selected_units'] == 0)
    assert server.state['spent'] == 0
    assert [r['op'] for r in server.requests] == ['begin', 'select', 'stop']
    until(lambda: not adapter.busy and adapter.observe().run_attempt == '')
    assert runner.start(1)
