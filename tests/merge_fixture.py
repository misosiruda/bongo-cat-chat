"""Synthetic UI adapter. Never imports a game/Steam/input implementation."""
from dataclasses import replace

from bongo_chat.auto_merge import Observation, Receipt


class FakeGameUI:
    def __init__(self, clock):
        self.clock = clock
        self.value = Observation(clock(), target='synthetic-target', category='hats',
            ready=True, can_select=True, favorites_allowed=False, events_excluded=True,
            available_group='cosmetics')
        self.calls = []
        self.closed = False
        self.select_error = self.merge_error = None
        self.fresh = True

    def observe(self):
        return replace(self.value, captured_at=self.clock()) if self.fresh else self.value

    def select_duplicates(self, expected, attempt):
        assert not self.closed
        self.calls.append(('select', attempt))
        if self.select_error:
            raise self.select_error

    def selected(self, exchanges=1):
        self.value = replace(self.value, selection='synthetic-selection',
            selected_units=exchanges * 10, exchanges=exchanges,
            selection_attempt=self.calls[-1][1], receipt=None)

    def merge(self, expected, attempt):
        assert not self.closed
        self.calls.append(('merge', attempt))
        if self.merge_error:
            raise self.merge_error
        self.value = replace(self.value, exchanging=True)

    def set_group(self, group):
        self.calls.append(('group',group))
        self.value = replace(self.value,category=group,available_group=group,
                             available_exchanges=5 if group=='emotes' else 23)

    def result(self, completed=1, finished=True, failed=False):
        self.value = replace(self.value, receipt=Receipt(self.calls[-1][1], completed, finished, failed),
            exchanging=not finished, selection='' if finished else self.value.selection,
            selected_units=0 if finished else self.value.selected_units,
            exchanges=0 if finished else self.value.exchanges)

    def close(self):
        self.closed = True
