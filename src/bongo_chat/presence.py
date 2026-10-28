"""Membership differences within one continuously verified lobby connection."""

JOIN_WAIT_SECONDS = 5.0


class PresenceTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.members = None
        self.names = {}
        self.pending = {}

    def update(self, state, now, blocked):
        members = state.get('members')
        observed = state.get('observed', now)
        if (not state.get('connected') or not state.get('lobby_verified')
                or blocked is None or members is None
                or not 0 <= now - observed < 2.5
                or not all(state.get(key) for key in ('account', 'lobby', 'generation'))
                or state['account'] not in members):
            self.reset()
            return []
        current = set(members) - {state['account']}
        profiles = state.get('profiles', {})
        names = {uid: profiles[uid]['name'] for uid in current
                 if uid not in blocked and profiles.get(uid, {}).get('name')}
        events = []
        if self.members is not None:
            for uid in sorted(self.members - current):
                # A departure is no longer a current member, but the account's
                # persisted block list still applies to it.
                if uid not in blocked and uid in self.names:
                    events.append(('member_left', uid, self.names[uid], observed))
            for uid in sorted(current - self.members):
                self.pending[uid] = observed
            for uid, started in list(self.pending.items()):
                if uid not in current or uid in blocked or now - started >= JOIN_WAIT_SECONDS:
                    del self.pending[uid]
                elif uid in names:
                    # Keep the first membership observation even when the name
                    # arrives later, so an intervening block cannot be replayed.
                    events.append(('member_joined', uid, names[uid], started))
                    del self.pending[uid]
        self.members, self.names = current, names
        return events
