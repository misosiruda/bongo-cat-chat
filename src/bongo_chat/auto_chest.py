"""App preferences and presentation for the explicitly armed chest runtime.

The bridge owns dispatch, result correlation, hotkeys and the heartbeat lease.
Saved startup consent is separate from the native enabled/armed state.
"""
import math
import sqlite3
import time


DEFAULTS = dict(own=True, others=False, min_delay=3.0, max_delay=8.0)
BOOL_FIELDS = ('supported', 'armed', 'enabled', 'pending', 'unknown', 'legacy_detected', 'legacy_taken_over', 'own', 'others')
COUNT_FIELDS = ('attempted', 'own_confirmed', 'failed', 'remote_requested')
REASONS = frozenset({'ready', 'running', 'paused', 'waiting_result', 'result_delayed', 'starting', 'user_stopped',
                     'app_disconnected', 'result_unverified', 'chest_fault', 'unsupported_chest',
                     'disconnected', 'game_unavailable', 'input_failed', 'connection_recovering', 'inventory_refreshing'})


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
        self.start_on_launch = False
        try:
            saved = store.setting('auto_chest', default=DEFAULTS)
            if not isinstance(saved, dict):
                raise ValueError('invalid_chest_settings')
            saved = dict(saved)
            self.start_on_launch = saved.pop('start_on_launch', False)
            if type(self.start_on_launch) is not bool:
                raise ValueError('invalid_chest_settings')
            self.preferences = settings(saved)
        except (ValueError, TypeError, sqlite3.Error, OSError):
            self.preferences = dict(DEFAULTS)
            self.preferences_valid = False
            self.start_on_launch = False
        self.closed = False
        self.startup_pending = bool(self.start_on_launch and connection)
        self.startup_status = 'waiting_game' if self.startup_pending else 'disabled'
        self.startup_attempted = False
        self.startup_revision = None
        self.startup_wait = None

    def snapshot(self):
        value = self.connection.chest_snapshot() if self.connection else None
        fresh = value and 0 <= self.clock() - value.get('captured_at', -10) <= 1.5
        # A stale active/pending state still blocks restart until a fresh stop is observed.
        result = dict(value or {})
        result.pop('captured_at', None)
        result.update(preferences=dict(self.preferences, start_on_launch=self.start_on_launch),
                      fresh=bool(fresh), startup_pending=self.startup_pending,
                      startup_status=self.startup_status)
        result.setdefault('armed', False)
        result.setdefault('enabled', False)
        result.setdefault('pending', False)
        result.setdefault('unknown', False)
        result['can_start'] = bool(fresh and result.get('supported') and not self.closed
                                   and self.preferences_valid
                                   and not any(result[k] for k in ('armed', 'pending', 'unknown')))
        if not fresh:
            result['reason'] = ('connection_recovering' if result['armed'] and not result['unknown']
                                else 'observation_stale' if value else self.reason)
        return result

    @property
    def blocks_restart(self):
        value = self.snapshot()
        return any(value[key] for key in ('armed', 'pending', 'unknown'))

    def save(self, value):
        if not isinstance(value, dict):
            raise ValueError('invalid_chest_settings')
        value = dict(value)
        launch = value.pop('start_on_launch', self.start_on_launch)
        if type(launch) is not bool:
            raise ValueError('invalid_chest_settings')
        value = settings(value)
        # Running settings belong to a single explicit start, never a delayed UI edit.
        if self.closed or self.blocks_restart:
            return False
        # One SQLite setting write commits startup consent and its exact options together.
        self.store.setting('auto_chest', dict(value, start_on_launch=launch))
        self.preferences = value
        self.start_on_launch = launch
        self.preferences_valid = True
        self.cancel_startup()
        return True

    def cancel_startup(self, status='cancelled'):
        if self.startup_pending:
            self.startup_pending = False
            self.startup_status = status

    def tick_startup(self, game_ready=False, blocked=False):
        """One saved launch request; never retries an attach or resumes a stopped run."""
        if not self.startup_pending or self.closed:
            return
        if blocked:
            self.cancel_startup('blocked')
            return
        state = self.connection.connection_snapshot()
        if self.startup_revision is not None and state['revision'] != self.startup_revision:
            self.cancel_startup('failed')
            return
        if state['state'] == 'disconnected' and not self.startup_attempted:
            if not game_ready:
                self.startup_status = 'waiting_game'
                return
            self.startup_attempted = True
            try:
                connected = self.connection.connect()
            except Exception:
                connected = False
            if not connected:
                self.cancel_startup('failed')
                return
            self.startup_revision = self.connection.connection_snapshot()['revision']
            self.startup_status = 'connecting'
            return
        if state['state'] == 'connecting':
            self.startup_status = 'connecting'
            return
        if state['state'] != 'connected':
            self.cancel_startup('failed')
            return
        if self.startup_revision is None:
            self.startup_revision = state['revision']
        value = self.snapshot()
        if not value['fresh']:
            if self.startup_wait is None:
                self.startup_wait = self.clock()
            if self.clock() - self.startup_wait >= 10:
                self.cancel_startup('failed')
            else:
                self.startup_status = 'waiting_state'
            return
        if not value['can_start']:
            self.cancel_startup('blocked')
            return
        if not game_ready:
            self.startup_status = 'waiting_game'
            return
        if value.get('legacy_detected') and not value.get('legacy_taken_over'):
            self.startup_status = 'confirmation_required'
            return
        # Consume before submitting: lost/refused starts cannot be automatically retried.
        self.cancel_startup('started')
        if not self.start():
            self.startup_status = 'failed'

    def start(self, replace_legacy=False):
        self.cancel_startup()
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
        self.cancel_startup()
        if self.connection:
            self.connection.chest_stop()

    def close(self):
        self.closed = True
        self.stop()
