"""Session-only orchestration of the game's own duplicate selection and Merge.

No inventory selection algorithm, Steam exchange call or game input lives here.
An adapter must supply fresh observations and revalidate the exact target before
each input. The internal-function adapter is an explicitly connected development session.
"""
from dataclasses import dataclass
import time
from typing import Protocol
from uuid import uuid4


ACTIVE = frozenset({'arming', 'preparing', 'selecting', 'merging', 'waiting', 'stopping'})
TERMINAL = frozenset({'completed', 'stopped', 'failed', 'unknown'})
REASONS = frozenset({'adapter_unverified', 'offline', 'read_only', 'closed',
    'game_unavailable', 'screen_unavailable', 'target_changed', 'settings_changed',
    'existing_selection', 'observation_stale', 'selection_unverified',
    'selection_timeout', 'result_timeout', 'result_unverified', 'input_failed',
    'game_failed', 'no_duplicates', 'limit_reached', 'user_stopped', 'app_closed',
    'checked_in_game', 'ready', 'manual_exchange_screen_open', 'group_changing',
    'test_budget_exhausted', 'bridge_observation_failed'})
# ItemExchange.MatchesCurrentTab / SteamItemRuntime.IsCosmetic: UI tabs are
# narrower than exchange groups. A hats tab can auto-select skins and bongos.
GROUP_BY_CATEGORY = {'cosmetics': 'cosmetics', 'hats': 'cosmetics', 'skins': 'cosmetics', 'bongos': 'cosmetics',
                     'emotes': 'emotes', 'ui_themes': 'emotes'}
CATEGORIES = frozenset(GROUP_BY_CATEGORY)
MAX_SAFE_COUNT = 2**53 - 1  # Exact integer transport through QWebChannel/JavaScript.


class InputRefused(Exception):
    """Adapter guarantees no input was delivered (e.g. target changed)."""


@dataclass(frozen=True)
class Receipt:
    attempt: str
    completed: int  # Cumulative confirmed successes for this one Merge click.
    finished: bool = False
    failed: bool = False


@dataclass(frozen=True)
class Observation:
    captured_at: float
    target: str = ''  # Opaque process/window/account epoch; never sent to the UI.
    category: str = ''
    ready: bool = False
    reason: str = 'screen_unavailable'
    favorites_allowed: bool | None = None
    events_excluded: bool | None = None
    selected_units: int = 0
    exchanges: int = 0
    selection: str = ''  # Opaque fingerprint, not item IDs in the renderer.
    selection_attempt: str = ''
    can_select: bool | None = None
    exchanging: bool = False
    receipt: Receipt | None = None
    # Verified count for the named exchange group and protection policy.
    # Excludes rewards not yet received; not the selected batch's `exchanges`.
    # None means unavailable, never zero. Read-only aggregation belongs to the adapter.
    available_exchanges: int | None = None
    available_group: str = ''  # Must match the current tab's group; no combined total.
    execution_budget_remaining: int | None = None  # Separate local test limit, not inventory quantity.
    run_attempt: str = ''


class GameUI(Protocol):
    """Nonblocking adapter contract; use a separate worker for slow discovery.

    observe returns a coherent, timestamped snapshot. ready requires supported
    game code, exact process/account, explicit exchange group and no manual
    selection conflict. The internal bridge requires the manual menu closed.
    Inputs must recheck freshness, target, group, protections and selection at
    dispatch. No window focus or screen coordinates are needed. A selection
    fingerprint/receipt is correlated to an attempt only with positive evidence;
    a cleared slot, idle animation or a completed click alone is not success.
    """
    def observe(self) -> Observation: ...
    def select_duplicates(self, expected: Observation, attempt: str) -> None: ...
    def merge(self, expected: Observation, attempt: str) -> None: ...
    def close(self) -> None: ...


class UnavailableGameUI:
    """Explicit production gate, not simulated progress or a fallback clicker."""
    def __init__(self, reason='adapter_unverified', clock=time.monotonic):
        self.reason, self.clock = reason, clock

    def observe(self):
        return Observation(self.clock(), reason=self.reason)

    def select_duplicates(self, expected, attempt):
        raise InputRefused

    def merge(self, expected, attempt):
        raise InputRefused

    def close(self):
        pass


class AutoMerge:
    FRESH_SECONDS = 1.5
    SELECTION_TIMEOUT = 5.0
    RESULT_TIMEOUT = 30.0

    def __init__(self, adapter=None, clock=time.monotonic):
        self.clock = clock
        self.adapter = adapter if adapter is not None else UnavailableGameUI(clock=clock)
        self.state, self.reason = 'idle', 'adapter_unverified'
        self.observation = None
        self.baseline = None
        self.completed = self.limit = self.pending_count = self.batch_confirmed = 0
        self.pending_attempt = self.selection_attempt = ''
        self.run_attempt = ''
        self.selected_fingerprint = ''
        self.deadline = 0.0
        self.stop_requested = self.closed = self.unresolved = False
        self.revision = 0

    @property
    def active(self):
        return self.state in ACTIVE

    @property
    def blocks_restart(self):
        return self.active or self.unresolved

    def finish(self, state, reason):
        self.state, self.reason = state, reason
        self.unresolved = state == 'unknown'
        if not self.unresolved:
            self.pending_attempt = ''
            self.pending_count = 0
        self.revision += 1

    def observe(self):
        try:
            value = self.adapter.observe()
            if not isinstance(value, Observation):
                raise ValueError
            if not 0 <= self.clock() - value.captured_at <= self.FRESH_SECONDS:
                return Observation(self.clock(), reason='observation_stale')
            if (type(value.selected_units) is not int or not 0 <= value.selected_units <= 100000
                    or type(value.exchanges) is not int or not 0 <= value.exchanges <= 10000
                    or type(value.ready) is not bool or type(value.exchanging) is not bool
                    or value.favorites_allowed is not None and type(value.favorites_allowed) is not bool
                    or value.events_excluded is not None and type(value.events_excluded) is not bool
                    or value.can_select is not None and type(value.can_select) is not bool
                    or value.execution_budget_remaining is not None and (type(value.execution_budget_remaining) is not int
                        or not 0 <= value.execution_budget_remaining <= MAX_SAFE_COUNT)):
                raise ValueError
            return value
        except Exception:
            return Observation(self.clock(), reason='screen_unavailable')

    def preparation_reason(self, value):
        if self.closed:
            return 'closed'
        if not value.ready or not value.target or value.category not in CATEGORIES:
            return value.reason if value.reason in REASONS - {'ready'} else 'screen_unavailable'
        if value.exchanging or value.selected_units or value.exchanges or value.selection:
            return 'existing_selection'
        if value.can_select is None:
            return 'selection_unverified'
        if value.execution_budget_remaining == 0:
            return 'test_budget_exhausted'
        return ''

    def set_group(self, group):
        if group not in {'cosmetics','emotes'} or self.blocks_restart or self.closed:
            return False
        try:
            self.adapter.set_group(group)
        except Exception:
            return False
        self.state, self.reason = 'idle', 'group_changing'
        self.tick()
        return True

    def start(self, limit):
        if type(limit) is not int or not 1 <= limit <= MAX_SAFE_COUNT:
            raise ValueError('invalid_merge_limit')
        if self.active or self.unresolved or self.closed:
            return False
        value = self.observation = self.observe()  # Never trust the last UI reply.
        reason = self.preparation_reason(value)
        if reason:
            self.finish('blocked', reason)
            return False
        self.baseline = value
        self.completed = self.pending_count = self.batch_confirmed = 0
        self.pending_attempt = self.selection_attempt = self.selected_fingerprint = ''
        self.limit, self.stop_requested = limit, False
        self.state, self.reason = 'preparing', 'ready'
        begin = getattr(self.adapter, 'begin_run', None)
        if begin:
            self.run_attempt = uuid4().hex
            self.state, self.deadline = 'arming', self.clock() + self.SELECTION_TIMEOUT
            try:
                begin(value, limit, self.run_attempt)
            except Exception:
                self.finish('failed', 'input_failed')
                return False
        self.revision += 1
        return True

    def stop(self):
        if not self.active:
            return
        self.stop_requested = True
        if self.pending_attempt:
            self.state, self.reason = 'stopping', 'user_stopped'
            self.revision += 1
        else:
            self.finish('stopped', 'user_stopped')
            stop_selection = getattr(self.adapter, 'stop_selection', None)
            if stop_selection:
                try: stop_selection()
                except Exception: pass

    def acknowledge(self):
        """User checked the game; this never retroactively counts a success."""
        if self.state == 'unknown':
            self.finish('stopped', 'checked_in_game')

    def maximum(self):
        """Read a fresh maximum for the editor; never starts or sends input."""
        if self.active or self.unresolved or self.closed:
            return None
        self.tick()
        view = self.snapshot()
        count = view['available_exchanges']
        return count if view['can_start'] and count is not None and count > 0 else None

    def context_reason(self, value):
        base = self.baseline
        if not value.ready:
            return value.reason if value.reason in REASONS else 'screen_unavailable'
        if (value.target, value.category) != (base.target, base.category):
            return 'target_changed'
        if (value.favorites_allowed, value.events_excluded) != (base.favorites_allowed, base.events_excluded):
            return 'settings_changed'
        return ''

    def tick(self):
        if self.closed:
            return
        self.revision += 1
        value = self.observation = self.observe()
        if not self.active:
            if self.state not in TERMINAL:
                self.reason = self.preparation_reason(value) or 'ready'
                self.state = 'blocked' if self.reason != 'ready' else 'idle'
            return
        reason = self.context_reason(value)
        if reason:
            self.finish('unknown' if self.pending_attempt else 'failed', reason)
            return
        if self.pending_attempt:
            self.accept_result(value)
            return
        if self.stop_requested:
            self.finish('stopped', 'user_stopped')
            return
        if value.exchanging:
            self.finish('failed', 'selection_unverified')
            return
        if self.state == 'arming':
            if value.run_attempt == self.run_attempt:
                self.state = 'preparing'
            elif self.clock() >= self.deadline:
                self.finish('failed', 'input_failed')
        elif self.state == 'preparing':
            if value.selected_units or value.exchanges or value.selection:
                self.finish('failed', 'existing_selection')
            elif self.completed >= self.limit:
                self.finish('completed', 'limit_reached')
            elif value.execution_budget_remaining == 0:
                self.finish('stopped', 'test_budget_exhausted')
            elif value.can_select is False:
                self.finish('completed', 'no_duplicates')
            elif value.can_select is not True:
                self.finish('failed', 'selection_unverified')
            else:
                self.selection_attempt = uuid4().hex
                self.state, self.deadline = 'selecting', self.clock() + self.SELECTION_TIMEOUT
                try:
                    self.adapter.select_duplicates(value, self.selection_attempt)
                except Exception:
                    self.finish('failed', 'input_failed')  # No Merge was requested.
        elif self.state == 'selecting':
            if self.clock() >= self.deadline:
                self.finish('failed', 'selection_timeout')
            elif value.selection_attempt == self.selection_attempt:
                if not value.selected_units and not value.exchanges and not value.selection and value.can_select is False:
                    self.finish('completed', 'no_duplicates')
                elif (value.selection and value.exchanges > 0
                      and value.selected_units == value.exchanges * 10):
                    if self.completed + value.exchanges > self.limit:
                        self.finish('completed', 'limit_reached')
                    else:
                        self.selected_fingerprint = (value.selection, value.selected_units, value.exchanges)
                        self.state = 'merging'  # One fresh tick before consuming.
            elif value.selected_units or value.exchanges or value.selection:
                self.finish('failed', 'selection_unverified')
        elif self.state == 'merging':
            if (value.selection_attempt != self.selection_attempt
                    or (value.selection, value.selected_units, value.exchanges) != self.selected_fingerprint):
                self.finish('failed', 'selection_unverified')
                return
            self.pending_attempt = uuid4().hex
            self.pending_count, self.batch_confirmed = value.exchanges, 0
            self.deadline = self.clock() + self.RESULT_TIMEOUT
            self.state = 'waiting'  # Set before dispatch: input exceptions can be ambiguous.
            try:
                self.adapter.merge(value, self.pending_attempt)
            except InputRefused:
                self.finish('failed', 'input_failed')
            except Exception:
                self.finish('unknown', 'input_failed')

    def accept_result(self, value):
        receipt = value.receipt
        if receipt is not None:
            if (not isinstance(receipt, Receipt) or receipt.attempt != self.pending_attempt
                    or type(receipt.completed) is not int
                    or not self.batch_confirmed <= receipt.completed <= self.pending_count
                    or type(receipt.finished) is not bool or type(receipt.failed) is not bool
                    or receipt.failed and not receipt.finished):
                self.finish('unknown', 'result_unverified')
                return
            self.completed += receipt.completed - self.batch_confirmed
            self.batch_confirmed = receipt.completed
            if receipt.finished:
                if value.exchanging or (not receipt.failed and receipt.completed != self.pending_count):
                    self.finish('unknown', 'result_unverified')
                elif receipt.failed:
                    self.finish('failed', 'game_failed')
                elif self.stop_requested:
                    self.finish('stopped', 'user_stopped')
                elif value.selected_units or value.exchanges or value.selection:
                    self.finish('failed', 'existing_selection')
                else:
                    self.pending_attempt = ''
                    self.pending_count = 0
                    self.state, self.reason = 'preparing', 'ready'
                return
        if self.clock() >= self.deadline:
            self.finish('unknown', 'result_timeout')

    def snapshot(self):
        value = self.observation
        fresh = bool(value and 0 <= self.clock() - value.captured_at <= self.FRESH_SECONDS)
        group = GROUP_BY_CATEGORY.get(value.category, '') if value and value.ready and fresh else ''
        can_start = bool(value and not self.active and not self.unresolved
                         and not self.preparation_reason(value)
                         and fresh)
        count = value.available_exchanges if (value and value.ready and value.target
            and group and value.available_group == group and fresh and not value.exchanging
            and not self.pending_attempt and not self.closed) else None
        if type(count) is not int or not 0 <= count <= MAX_SAFE_COUNT:
            count = None
        return dict(state=self.state, reason=self.reason, active=self.active,
                    can_change_group=not self.blocks_restart and not self.closed and hasattr(self.adapter,'set_group'),
                    available_exchanges=count,
                    exchange_group=group,
                    can_start=can_start, can_stop=self.active and not self.stop_requested,
                    unresolved=self.unresolved, completed=self.completed, limit=self.limit,
                    pending=self.pending_count - self.batch_confirmed if self.pending_attempt else 0,
                    category=value.category if value and value.category in CATEGORIES else '',
                    favorites_allowed=value.favorites_allowed if value and value.ready else None,
                    events_excluded=value.events_excluded if value and value.ready else None,
                    revision=self.revision)

    def close(self):
        if self.closed:
            return
        if self.active:
            self.finish('unknown' if self.pending_attempt else 'stopped', 'app_closed')
        self.closed = True
        try:
            self.adapter.close()
        except Exception:
            pass  # No final game input, retries, or raw adapter errors on exit.
