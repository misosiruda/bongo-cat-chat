"""App preferences and presentation for the explicitly armed chest runtime.

The bridge owns dispatch, result correlation, hotkeys and the heartbeat lease.
Saved preferences never contain an enabled/running flag.
"""
import math
import sqlite3
import time


DEFAULTS = dict(own=True, others=False, min_delay=3.0, max_delay=8.0)
BOOL_FIELDS = ('supported', 'armed', 'enabled', 'pending', 'unknown', 'legacy_detected', 'legacy_taken_over', 'own', 'others')
COUNT_FIELDS = ('attempted', 'own_confirmed', 'failed', 'remote_requested')
REASONS = frozenset({'ready', 'running', 'paused', 'waiting_result', 'starting', 'user_stopped',
                     'app_disconnected', 'result_unverified', 'chest_fault', 'unsupported_chest',
                     'disconnected', 'game_unavailable', 'input_failed'})


def observation(raw, captured_at):
    """Aggregate values only; paths, account IDs and arbitrary bridge keys never reach UI."""
    if (not isinstance(raw, dict) or any(type(raw.get(key)) is not bool for key in BOOL_FIELDS)
            or any(type(raw.get(key)) is not int or not 0 <= raw[key] <= 2**53 - 1 for key in COUNT_FIELDS)
            or raw.get('reason') not in REASONS):
        raise ValueError('invalid_chest_observation')
    value = {key: raw[key] for key in (*BOOL_FIELDS, *COUNT_FIELDS, 'reason')}
    prefs = settings({key: raw[key] for key in DEFAULTS})
    return dict(value, **{k:v for k,v in prefs.items() if k not in value}, captured_at=captured_at)


def settings(value):
    if not isinstance(value, dict) or value.keys() != DEFAULTS.keys():
        raise ValueError('invalid_chest_settings')
    if any(type(value[key]) is not bool for key in ('own', 'others')):
        raise ValueError('invalid_chest_settings')
    for key in ('min_delay', 'max_delay'):
        number = value[key]
        if type(number) not in (int, float) or not 1 <= number <= 300 or not math.isfinite(number):
            raise ValueError('invalid_chest_settings')
    if value['min_delay'] > value['max_delay'] or not (value['own'] or value['others']):
        raise ValueError('invalid_chest_settings')
    return dict(value)


class AutoChest:
    def __init__(self, store, connection=None, reason='offline', clock=time.monotonic):
        self.store, self.connection, self.clock = store, connection, clock
        self.reason = reason
        self.preferences_valid = True
        try:
            self.preferences = settings(store.setting('auto_chest', default=DEFAULTS))
        except (ValueError, TypeError, sqlite3.Error, OSError):
            self.preferences = dict(DEFAULTS)
            self.preferences_valid = False
        self.closed = False

    def snapshot(self):
        value = self.connection.chest_snapshot() if self.connection else None
        fresh = value and 0 <= self.clock() - value.get('captured_at', -10) <= 1.5
        # A stale active/pending state still blocks restart until a fresh stop is observed.
        result = dict(value or {})
        result.pop('captured_at', None)
        result.update(preferences=dict(self.preferences), fresh=bool(fresh))
        result.setdefault('armed', False)
        result.setdefault('enabled', False)
        result.setdefault('pending', False)
        result.setdefault('unknown', False)
        result['can_start'] = bool(fresh and result.get('supported') and not self.closed
                                   and self.preferences_valid
                                   and not any(result[k] for k in ('armed', 'pending', 'unknown')))
        if not fresh:
            result['reason'] = 'observation_stale' if value else self.reason
        return result

    @property
    def blocks_restart(self):
        value = self.snapshot()
        return any(value[key] for key in ('armed', 'pending', 'unknown'))

    def save(self, value):
        value = settings(value)
        # Running settings belong to a single explicit start, never a delayed UI edit.
        if self.closed or self.blocks_restart:
            return False
        self.store.setting('auto_chest', value)
        self.preferences = value
        self.preferences_valid = True
        return True

    def start(self, replace_legacy=False):
        if type(replace_legacy) is not bool:
            raise ValueError('invalid_chest_settings')
        if not self.snapshot()['can_start']:
            return False
        try:
            self.connection.chest_start(dict(self.preferences), replace_legacy)
        except Exception:
            return False
        return True

    def stop(self):
        if self.connection:
            self.connection.chest_stop()

    def close(self):
        self.closed = True
        self.stop()
