"""Ephemeral, directional pat streaks. No history, names or outbound traffic."""
from collections import OrderedDict

STREAK_SECONDS = 1.0
FADE_SECONDS = 1.0
PAT_TTL = STREAK_SECONDS + FADE_SECONDS
VISIBLE_PATS = 3


class PatTracker:
    def __init__(self):
        self.pairs = {}
        self.visible = []
        self.receipts = OrderedDict()

    def clear(self):
        self.pairs.clear()
        self.visible.clear()
        self.receipts.clear()

    def prune(self, now, allowed):
        self.pairs = {key: row for key, row in self.pairs.items()
                      if set(key) <= allowed and now - row['observed'] < PAT_TTL}
        self.visible = [key for key in self.visible if key in self.pairs]
        self.receipts = OrderedDict((uid, at) for uid, at in self.receipts.items() if now - at < PAT_TTL)

    def fill(self, now):
        candidates = sorted((key for key, row in self.pairs.items()
                             if key not in self.visible and now - row['observed'] < STREAK_SECONDS),
                            key=lambda key: self.pairs[key]['observed'], reverse=True)
        self.visible.extend(candidates[:VISIBLE_PATS - len(self.visible)])

    def add(self, event, now, allowed):
        self.prune(now, allowed)
        if event['id'] in self.receipts:
            return
        self.receipts[event['id']] = now
        key = event['sender'], event['target']
        previous = self.pairs.get(key)
        # A delayed/out-of-order delivery must not rewind a pair's clock.
        if previous and event['observed'] < previous['observed']:
            return
        count = previous['count'] + 1 if previous and event['observed'] - previous['observed'] < STREAK_SECONDS else 1
        self.pairs[key] = dict(id=event['id'], sender=key[0], target=key[1],
                               count=count, observed=event['observed'])
        if key not in self.visible and now - event['observed'] < STREAK_SECONDS:
            if len(self.visible) == VISIBLE_PATS:
                # The oldest last input is also the oldest fading row, if any.
                victim = min(self.visible, key=lambda k: self.pairs[k]['observed'])
                self.visible[self.visible.index(victim)] = key
            else:
                self.visible.append(key)
        self.fill(now)

    def snapshot(self, now, allowed):
        self.prune(now, allowed)
        self.fill(now)
        rows = []
        for key in self.visible:
            row = self.pairs[key]
            age = now - row['observed']
            rows.append(dict((k, v) for k, v in row.items() if k != 'observed') |
                        dict(expires_in_ms=(PAT_TTL - age) * 1000))
        hidden = [(STREAK_SECONDS - (now - row['observed'])) * 1000
                  for key, row in self.pairs.items()
                  if key not in self.visible and now - row['observed'] < STREAK_SECONDS]
        return dict(rows=rows, hidden_active_ms=hidden)
