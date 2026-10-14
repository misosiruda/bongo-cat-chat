"""No real user registry, Steam connections or HTTP requests are used."""
import threading
from unittest.mock import MagicMock

import pytest

from bongo_chat import privacy, updates


@pytest.fixture
def registry(monkeypatch):
    registry = MagicMock()
    registry.REG_DWORD = 4
    monkeypatch.setattr(privacy, 'winreg', registry)
    return registry


@pytest.mark.parametrize('value,kind,expected', [(0, 4, False), (1, 4, True), (2, 4, False), ('1', 1, False)])
def test_permission_is_strict_dword(registry, value, kind, expected):
    registry.QueryValueEx.return_value = value, kind
    assert privacy.update_checks_allowed() is expected


def test_absent_permission_preserves_upgrade_default_but_access_error_disables(registry):
    registry.OpenKey.side_effect = FileNotFoundError
    assert privacy.update_checks_allowed()
    registry.OpenKey.side_effect = PermissionError
    assert not privacy.update_checks_allowed()


def test_permission_persists_and_rejects_non_boolean(registry):
    privacy.set_update_checks_allowed(False)
    assert registry.SetValueEx.call_args.args[-2:] == (4, 0)
    with pytest.raises(ValueError):
        privacy.set_update_checks_allowed('false')
    assert registry.SetValueEx.call_count == 1


def test_opt_out_blocks_manual_periodic_and_game_error_requests(monkeypatch, tmp_path):
    check = MagicMock()
    monkeypatch.setattr(updates, 'check_and_stage', check)
    manager = updates.UpdateManager(tmp_path, '0.1.0', allowed=False)
    manager.next_check = 0
    manager.poll()
    manager.request()  # All manual/game-compatibility triggers use this entry point.
    assert manager.snapshot()['state'] == 'disabled'
    assert manager.snapshot()['allowed'] is False
    check.assert_not_called()
    manager.set_allowed(True)
    manager.request()
    manager.thread.join(5)
    check.assert_called_once()
    manager.close()
    manager.set_allowed(True)
    manager.request()
    assert check.call_count == 1


def test_disabling_cancels_inflight_and_cannot_be_overwritten(monkeypatch, tmp_path):
    started, finish = threading.Event(), threading.Event()
    def check(root, current, settings, transport, report):
        started.set()
        assert finish.wait(5)
        assert transport.cancelled.is_set()
        report('ready', '0.2.0')
    monkeypatch.setattr(updates, 'check_and_stage', check)
    manager = updates.UpdateManager(tmp_path, '0.1.0')
    manager.request()
    assert started.wait(5)
    manager.set_allowed(False)
    finish.set()
    manager.thread.join(5)
    assert not manager.thread.is_alive()
    assert manager.snapshot()['state'] == 'disabled'


def test_offline_cannot_be_enabled_by_permission(tmp_path, monkeypatch):
    check = MagicMock()
    monkeypatch.setattr(updates, 'check_and_stage', check)
    manager = updates.UpdateManager(tmp_path, '0.1.0', offline=True, allowed=False)
    manager.set_allowed(True)
    manager.request()
    check.assert_not_called()
