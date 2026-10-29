from dataclasses import replace

import pytest

from bongo_chat.auto_merge import AutoMerge, InputRefused, Observation, Receipt, UnavailableGameUI
from merge_fixture import FakeGameUI


@pytest.fixture
def session():
    now = [100.0]
    game = FakeGameUI(lambda: now[0])
    runner = AutoMerge(game, clock=lambda: now[0])
    return runner, game, now


def request_merge(runner, game, count=1, limit=10):
    assert runner.start(limit)
    runner.tick()
    game.selected(count)
    runner.tick()
    assert runner.state == 'merging'
    runner.tick()
    assert runner.state == 'waiting'


def test_default_adapter_cannot_click_or_start():
    runner = AutoMerge()
    runner.tick()
    assert runner.snapshot()['reason'] == 'adapter_unverified'
    assert not runner.snapshot()['can_start']
    assert not runner.start(1)
    assert not runner.active and runner.completed == 0
    with pytest.raises(InputRefused):
        runner.adapter.merge(Observation(0), 'synthetic')


@pytest.mark.parametrize('limit', [True, 0, 2**53, -1, '10', 1.0, None])
def test_invalid_limit_never_sends_input(session, limit):
    runner, game, _ = session
    with pytest.raises(ValueError):
        runner.start(limit)
    assert game.calls == []


@pytest.mark.parametrize('fields,reason', [
    ({'selected_units': 1}, 'existing_selection'),
    ({'selection': 'manual'}, 'existing_selection'),
    ({'exchanging': True}, 'existing_selection'),
    ({'ready': False}, 'screen_unavailable'),
    ({'category': 'consumables'}, 'screen_unavailable'),
    ({'can_select': None}, 'selection_unverified'),
])
def test_preflight_requires_empty_recognized_screen(session, fields, reason):
    runner, game, _ = session
    game.value = replace(game.value, **fields)
    assert not runner.start(10)
    assert runner.reason == reason and not game.calls


def test_no_duplicates_finishes_without_any_input(session):
    runner, game, _ = session
    game.value = replace(game.value, can_select=False)
    assert runner.start(10)
    runner.tick()
    assert runner.state == 'completed' and runner.reason == 'no_duplicates'
    assert not game.calls and runner.completed == 0


def test_repeats_only_after_confirmed_batch_and_counts_exchanges_not_clicks(session):
    runner, game, _ = session
    request_merge(runner, game, count=3, limit=4)
    assert runner.completed == 0 and runner.snapshot()['pending'] == 3
    game.result(2, finished=False)
    runner.tick(); runner.tick()
    assert runner.completed == 2 and runner.snapshot()['pending'] == 1
    assert len(game.calls) == 2
    game.result(3)
    runner.tick()
    assert runner.completed == 3 and runner.state == 'preparing'
    runner.tick()
    game.selected()
    runner.tick(); runner.tick()
    game.result(1)
    runner.tick(); runner.tick()
    assert runner.completed == 4 and runner.reason == 'limit_reached'
    assert [call[0] for call in game.calls] == ['select', 'merge', 'select', 'merge']


def test_batch_over_limit_never_merges_or_clears_selection(session):
    runner, game, _ = session
    runner.start(1); runner.tick(); game.selected(2); runner.tick()
    assert runner.state == 'completed' and runner.reason == 'limit_reached'
    assert [call[0] for call in game.calls] == ['select']
    assert game.value.selected_units == 20
    assert not runner.snapshot()['can_start']


@pytest.mark.parametrize('stage', ['preparing', 'selecting', 'merging'])
def test_stop_before_merge_prevents_consumption(session, stage):
    runner, game, _ = session
    runner.start(10)
    if stage != 'preparing': runner.tick()
    if stage == 'merging': game.selected(); runner.tick()
    runner.stop(); runner.tick()
    assert runner.state == 'stopped' and not runner.blocks_restart
    assert all(call[0] != 'merge' for call in game.calls)


def test_stop_waits_for_existing_request_and_does_not_repeat(session):
    runner, game, _ = session
    request_merge(runner, game)
    runner.stop(); runner.stop(); runner.tick()
    assert runner.state == 'stopping' and runner.blocks_restart
    assert not runner.start(10)
    assert not runner.snapshot()['can_stop']
    game.result()
    runner.tick(); runner.tick()
    assert runner.state == 'stopped' and runner.completed == 1
    assert len(game.calls) == 2 and not runner.blocks_restart


def test_timeout_latches_unknown_until_explicit_ack_without_inventing_success(session):
    runner, game, now = session
    request_merge(runner, game)
    runner.stop()
    now[0] += 31
    runner.tick()
    assert runner.state == 'unknown' and runner.reason == 'result_timeout'
    assert runner.blocks_restart and not runner.start(1)
    game.result()
    runner.tick()  # Late results do not silently unlock or replay the session.
    assert runner.completed == 0 and len(game.calls) == 2
    runner.acknowledge()
    assert runner.completed == 0 and not runner.blocks_restart
    assert runner.start(1)
    assert len(game.calls) == 2  # Explicit start still needs fresh preparation.


def test_idle_animation_and_empty_slots_are_not_a_success_receipt(session):
    runner, game, now = session
    request_merge(runner, game)
    game.value = replace(game.value, exchanging=False, selected_units=0, exchanges=0, selection='')
    runner.tick()
    assert runner.state == 'waiting' and runner.completed == 0
    now[0] += 31; runner.tick()
    assert runner.state == 'unknown' and len(game.calls) == 2


@pytest.mark.parametrize('fields,reason', [
    ({'target': 'different-target'}, 'target_changed'),
    ({'category': 'skins'}, 'target_changed'),
    ({'favorites_allowed': True}, 'settings_changed'),
    ({'events_excluded': False}, 'settings_changed'),
    ({'ready': False}, 'screen_unavailable'),
])
@pytest.mark.parametrize('pending', [False, True])
def test_identity_screen_or_option_change_stops_further_actions(session, fields, reason, pending):
    runner, game, _ = session
    if pending: request_merge(runner, game)
    else: runner.start(10); runner.tick(); game.selected(); runner.tick()
    game.value = replace(game.value, **fields)
    runner.tick(); runner.tick()
    assert runner.state == ('unknown' if pending else 'failed')
    assert runner.reason == reason
    assert len(game.calls) == (2 if pending else 1)


def test_changed_selection_before_dispatch_is_rejected(session):
    runner, game, _ = session
    runner.start(10); runner.tick(); game.selected(); runner.tick()
    game.value = replace(game.value, selection='manual-changed')
    runner.tick()
    assert runner.reason == 'selection_unverified' and len(game.calls) == 1


@pytest.mark.parametrize('error,expected', [(InputRefused(), 'failed'), (OSError('private detail'), 'unknown')])
def test_input_refused_vs_potentially_delivered_merge(session, error, expected):
    runner, game, _ = session
    game.merge_error = error
    runner.start(10); runner.tick(); game.selected(); runner.tick(); runner.tick()
    assert runner.state == expected and runner.completed == 0
    assert 'private detail' not in str(runner.snapshot())
    runner.tick()
    assert len(game.calls) == 2


def test_partial_batch_failure_counts_only_positive_confirmations(session):
    runner, game, _ = session
    request_merge(runner, game, count=3)
    game.result(1, failed=True)
    runner.tick(); runner.tick()
    assert runner.completed == 1 and runner.reason == 'game_failed'
    assert len(game.calls) == 2 and not runner.blocks_restart


@pytest.mark.parametrize('receipt', [Receipt('wrong-attempt', 1, True),
    Receipt('CURRENT', 2, True), Receipt('CURRENT', 0, True), Receipt('CURRENT', True, True)])
def test_bad_receipt_never_authorizes_more_input(session, receipt):
    runner, game, _ = session
    request_merge(runner, game)
    if receipt.attempt == 'CURRENT': receipt = replace(receipt, attempt=runner.pending_attempt)
    game.value = replace(game.value, receipt=receipt, exchanging=False)
    runner.tick(); runner.tick()
    assert runner.state == 'unknown' and len(game.calls) == 2


def test_selection_timeout_and_stale_preflight(session):
    runner, game, now = session
    runner.start(10); runner.tick()
    now[0] += 6; runner.tick()
    assert runner.reason == 'selection_timeout' and len(game.calls) == 1
    game.fresh = False
    assert not runner.start(10) and runner.reason == 'observation_stale'


def test_opaque_identity_and_selection_never_leave_orchestrator(session):
    runner, game, _ = session
    runner.tick()
    assert 'synthetic-target' not in str(runner.snapshot())
    assert 'selection' not in runner.snapshot()
    assert runner.snapshot()['favorites_allowed'] is False
    game.value = replace(game.value, ready=False)
    runner.tick()
    assert runner.snapshot()['favorites_allowed'] is None


def test_shutdown_never_sends_input_or_resumes(session):
    runner, game, _ = session
    request_merge(runner, game)
    runner.close(); runner.close(); runner.tick()
    assert game.closed and runner.state == 'unknown' and len(game.calls) == 2
    assert not runner.start(1)
    assert not AutoMerge().active


def test_maximum_uses_current_inventory_count_without_starting_or_clicking(session):
    runner, game, _ = session
    game.value = replace(game.value, available_exchanges=23)
    runner.tick()
    assert runner.snapshot()['available_exchanges'] == 23
    game.value = replace(game.value, available_exchanges=137)
    assert runner.maximum() == 137  # Refresh instead of using the old view or a 100 cap.
    assert runner.limit == 0 and not runner.active and not game.calls
    assert runner.start(137) and runner.limit == 137
    assert runner.maximum() is None and not game.calls


@pytest.mark.parametrize('count', [None, 0, -1, True, 1.5, '23', 2**53])
def test_unknown_zero_or_invalid_availability_does_not_set_maximum(session, count):
    runner, game, _ = session
    game.value = replace(game.value, available_exchanges=count)
    assert runner.maximum() is None
    assert runner.snapshot()['available_exchanges'] == (0 if type(count) is int and count == 0 else None)
    assert not game.calls


def test_stale_or_inflight_inventory_count_is_not_published(session):
    runner, game, now = session
    game.value = replace(game.value, available_exchanges=23)
    runner.tick(); now[0] += 2
    assert runner.snapshot()['available_exchanges'] is None
    game.fresh = False
    assert runner.maximum() is None
    game.fresh = True
    request_merge(runner, game)
    assert runner.snapshot()['available_exchanges'] is None
    assert runner.maximum() is None
    now[0] += 31; runner.tick()
    assert runner.unresolved and runner.maximum() is None


@pytest.mark.parametrize('category,group', [('hats','cosmetics'),('skins','cosmetics'),
    ('bongos','cosmetics'),('emotes','emotes'),('ui_themes','emotes')])
def test_inventory_count_is_scoped_to_game_exchange_group(session, category, group):
    runner, game, _ = session
    game.value = replace(game.value, category=category, available_group=group, available_exchanges=23)
    assert runner.maximum() == 23
    assert runner.snapshot()['exchange_group'] == group
    for wrong_group in ('', 'all', 'emotes' if group == 'cosmetics' else 'cosmetics'):
        game.value = replace(game.value, available_group=wrong_group)
        assert runner.maximum() is None
        assert runner.snapshot()['available_exchanges'] is None
    assert not game.calls


def test_group_change_during_request_stops_without_using_other_group(session):
    runner, game, _ = session
    request_merge(runner, game)
    game.value = replace(game.value, category='emotes', available_group='emotes', available_exchanges=9)
    runner.tick()
    assert runner.state == 'unknown' and runner.reason == 'target_changed'
    assert runner.maximum() is None and len(game.calls) == 2
