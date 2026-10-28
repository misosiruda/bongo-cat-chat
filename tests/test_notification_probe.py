"""Offline probe policy and persistence tests; not OS display acceptance."""
import importlib.util
from pathlib import Path

import pytest

from bongo_chat.store import Store

spec = importlib.util.spec_from_file_location('notification_probe', Path(__file__).parents[1] / 'tools/probe_notifications.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.fixture
def policy(tmp_path):
    store = Store(tmp_path / 'probe.sqlite3')
    yield probe.ProbePolicy(store)
    store.close()


@pytest.mark.parametrize('foreground', [True, False])
@pytest.mark.parametrize('flash,toast', [(True, True), (True, False), (False, True), (False, False)])
def test_focus_and_independent_switches(policy, foreground, flash, toast):
    policy.set_enabled(probe.FLASH, flash)
    policy.set_enabled(probe.TOAST, toast)
    result = policy.receive(foreground)
    assert result == dict(accepted=True, foreground=foreground,
                         flash=flash and not foreground, toast=toast and not foreground)


@pytest.mark.parametrize('case', ['self', 'blocked', 'unknown', 'privacy_pending', 'duplicate', 'meow', 'old_lobby', 'stale'])
def test_filtered_messages_do_not_notify(policy, case):
    changes = {}
    if case == 'self':
        changes['sender'] = 'fixture-self'
    elif case == 'blocked':
        policy.service.blocked['fixture-peer'] = '합성 차단 대상'
    elif case == 'unknown':
        changes['sender'] = 'fixture-unknown'
    elif case == 'privacy_pending':
        policy.service.blocked = None
    elif case == 'duplicate':
        changes['id'] = 'fixture-repeat'
        assert policy.receive(False, **changes)['toast']
    elif case == 'meow':
        changes['text'] = 'Meow Meow'
    elif case == 'old_lobby':
        changes['context'] = dict(policy.service.context(), lobby='fixture-old')
    elif case == 'stale':
        policy.service.clock = lambda: 103.0
    result = policy.receive(False, **changes)
    assert not result['flash'] and not result['toast']


@pytest.mark.parametrize('flash,toast', [(True, True), (True, False), (False, True), (False, False)])
def test_settings_survive_reopen(tmp_path, flash, toast):
    path = tmp_path / 'probe.sqlite3'
    store = Store(path)
    policy = probe.ProbePolicy(store)
    policy.set_enabled(probe.FLASH, flash)
    policy.set_enabled(probe.TOAST, toast)
    store.close()
    reopened = Store(path)
    try:
        policy = probe.ProbePolicy(reopened)
        assert policy.enabled(probe.FLASH) is flash
        assert policy.enabled(probe.TOAST) is toast
    finally:
        reopened.close()


@pytest.mark.parametrize('key,value', [(probe.FLASH, 'false'), (probe.TOAST, 0), ('theme', True)])
def test_settings_reject_wrong_types_or_keys(policy, key, value):
    with pytest.raises(ValueError, match='invalid_notification_setting'):
        policy.set_enabled(key, value)
