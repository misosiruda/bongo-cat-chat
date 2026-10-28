"""Membership differences within one continuously verified lobby connection."""

JOIN_WAIT_SECONDS = 5.0


class PresenceTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.members = None
        self.names = {}
        self.pending = {}

    def update(self, state, now):
        members = state.get('members')
        observed = state.get('observed', now)
        if (not state.get('connected') or not state.get('lobby_verified')
                or not state.get('privacy_ready') or members is None
                or not 0 <= now - observed < 2.5
                or not all(state.get(key) for key in ('account', 'lobby', 'generation'))
                or state['account'] not in members):
            self.reset()
            return []
        current = set(members) - {state['account']}
        hidden, profiles = state.get('hidden', {}), state.get('profiles', {})
        names = {uid: profiles[uid]['name'] for uid in current
                 if hidden.get(uid) is False and profiles.get(uid, {}).get('name')}
        events = []
        if self.members is not None:
            for uid in sorted(self.members - current):
                # The current privacy sample must still allow the departed peer.
                # Never turn lost privacy information into a departure notice.
                if hidden.get(uid) is False and uid in self.names:
                    events.append(('member_left', uid, self.names[uid]))
            for uid in sorted(current - self.members):
                self.pending[uid] = observed
            for uid, started in list(self.pending.items()):
                if uid not in current or hidden.get(uid) is True or now - started >= JOIN_WAIT_SECONDS:
                    del self.pending[uid]
                elif uid in names:
                    events.append(('member_joined', uid, names[uid]))
                    del self.pending[uid]
        self.members, self.names = current, names
        return events
