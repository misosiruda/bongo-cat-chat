"""Message state and privacy boundary, independent of Qt and Steam."""
from collections import OrderedDict, deque
from dataclasses import dataclass
import sqlite3
import time
from uuid import uuid4

from .protocol import encode, is_meow_message
from .profiles import steam_profile_uri
from .presence import PresenceTracker
from .reactions import MAX_REACTIONS, REACTION_TTL, png


NOTIFICATION_KEYS = frozenset({'notification_flash', 'notification_toast'})


@dataclass(frozen=True)
class AcceptedIncoming:
    """One new peer receipt, without message content or display names."""
    receipt: str
    sender: str
    account: str
    lobby: str
    generation: str

    def current(self, service):
        return (service.context() == dict(account=self.account, lobby=self.lobby, generation=self.generation)
                and self.sender != self.account and self.sender in service.allowed())


class ChatService:
    def __init__(self, store, clock=time.monotonic):
        self.store, self.clock = store, clock
        self.state = {"state": "checking", "account": "", "lobby": "", "generation": "",
                      "members": [], "profiles": {}}
        self.blocked = None  # None means the account's list could not be loaded.
        self.block_account = ""
        self.block_changed_at = {}
        self.updated = 0.0
        self.session = ""
        self.storage_error = False
        self.volatile = OrderedDict()
        self.pending = deque(maxlen=200)
        self.receipts = OrderedDict()
        self.revision = 0
        self.presence = PresenceTracker()
        self.reactions = deque(maxlen=MAX_REACTIONS)
        self.reaction_receipts = deque(maxlen=256)
        self.reactions_enabled = False
        self.reactions_enabled_since = self.clock()
        # Keep the last committed values available even if a later DB read fails.
        # An unreadable setting is not a missing key: never turn a saved OFF
        # into ON while the DB is unavailable. Load both values atomically.
        self.notifications = {key: False for key in NOTIFICATION_KEYS}
        try:
            self.load_notifications()
        except (sqlite3.Error, OSError):
            self.storage_error = True
        try:
            self.load_reaction_setting()
        except (sqlite3.Error, OSError):
            self.storage_error = True

    def apply_reaction_setting(self, value):
        if self.reactions_enabled != value:
            self.reactions.clear()
            # Worker assets/IPC may still contain events observed while OFF.
            self.reactions_enabled_since = self.clock()
        self.reactions_enabled = value

    def load_reaction_setting(self):
        value = self.store.setting('reactions_enabled', default=True)
        self.apply_reaction_setting(value if type(value) is bool else False)

    def set_reactions_enabled(self, value):
        if type(value) is not bool:
            raise ValueError('invalid_setting')
        self.store.setting('reactions_enabled', value)
        self.apply_reaction_setting(value)
        self.revision += 1

    def load_notifications(self):
        values = {}
        for key in NOTIFICATION_KEYS:
            value = self.store.setting(key, default=True)
            values[key] = value if type(value) is bool else True
        self.notifications = values

    def set_notification(self, key, value):
        if key not in NOTIFICATION_KEYS or type(value) is not bool:
            raise ValueError('invalid_setting')
        self.store.setting(key, value)
        self.notifications[key] = value
        self.revision += 1

    def write(self, fn, *args):
        try:
            fn(*args)
            return True
        except (sqlite3.Error, OSError):
            self.storage_error = True
            return False

    def recover_storage(self):
        self.store.prune()
        if self.session:
            self.store.session(self.session, self.state['account'], self.state['lobby'], self.state.get('name') or '')
            if self.state.get('name'):
                self.store.rename_session(self.session, self.state['account'], self.state['lobby'], self.state['name'])
        self.load_notifications()
        self.load_reaction_setting()
        self.load_blocks()
        self.storage_error = False

    def load_blocks(self):
        account = self.state.get('account', '')
        self.blocked = None
        self.block_account = account
        self.blocked = self.store.blocked_users(account) if account else {}

    def set_blocked(self, steam_id, blocked, account):
        steam_profile_uri(steam_id)  # Canonical uint64 string; never a JS number.
        if (type(blocked) is not bool or not account or account != self.state.get('account')
                or account != self.block_account or self.blocked is None or steam_id == account):
            raise ValueError('block_unavailable')
        name = self.state.get('profiles', {}).get(steam_id, {}).get('name', '')
        self.store.set_blocked(account, steam_id, blocked, name)
        # Commit before publishing. A failed write keeps the previous policy.
        if blocked:
            self.blocked.setdefault(steam_id, name)
            self.presence.pending.pop(steam_id, None)
            self.presence.names.pop(steam_id, None)
        else:
            self.blocked.pop(steam_id, None)
        self.block_changed_at[(account, steam_id)] = self.clock()
        self.reactions = deque((e for e in self.reactions if e['sender'] != steam_id), maxlen=MAX_REACTIONS)
        self.revision += 1

    def after_block_change(self, event):
        return event.get('observed', self.clock()) >= self.block_changed_at.get(
            (self.state.get('account'), event['sender']), float('-inf'))

    def save_message(self, row, receipt=None):
        try:
            sequence = self.store.add(row, receipt)
        except (sqlite3.Error, OSError):
            self.storage_error = True
            return False
        # Bound each unsaved run to the first later committed message. This
        # preserves arrival order without trusting wall-clock timestamps or
        # keeping an unbounded map of every received message.
        for unsaved in self.volatile.values():
            unsaved.setdefault('_before_seq', sequence)
        return True

    def forget(self, account, lobby=None):
        self.store.delete(account, lobby)
        def selected(row):
            return row['account'] == account and (lobby is None or row['lobby'] == lobby)
        self.volatile = OrderedDict((key, row) for key, row in self.volatile.items() if not selected(row))
        self.pending = deque((p for p in self.pending if not selected(p['context'])), maxlen=200)
        self.revision += 1

    def update(self, state):
        state = dict(state)
        old = self.state
        boundary = (old.get("account"), old.get("lobby"), old.get("generation")) != (
            state.get("account"), state.get("lobby"), state.get("generation"))
        name = state.get("name")
        # Steam's empty metadata does not distinguish a missing value from a
        # failed lookup. Retain the last known name only within this context.
        if not (state.get("connected") and isinstance(name, str) and name.strip()):
            state["name"] = "" if boundary else old.get("name", "")
        if boundary or not self.fresh():
            self.presence.reset()
        if boundary:
            self.reactions.clear()
            self.end("connection_changed")
            self.pending.clear()
            self.volatile.clear()
            self.session = ""
        self.state = dict(state)
        if self.block_account != state.get('account', '') or self.blocked is None:
            try:
                self.load_blocks()
            except (sqlite3.Error, OSError):
                self.storage_error = True
        self.updated = self.clock()
        if state.get("account") and state.get("lobby") and state.get("generation") and not self.session:
            self.session = str(uuid4())
            self.write(self.store.session, self.session, state["account"], state["lobby"], state.get("name") or "")
        elif (self.session and state.get("connected") and state.get("name")
                and state["name"] != old.get("name") and not self.storage_error):
            # Do not retry writes on every worker heartbeat after a disk error.
            # Explicit storage recovery saves the latest observed title.
            self.write(self.store.rename_session, self.session, state["account"], state["lobby"], state["name"])
        for kind, sender, name, observed in self.presence.update(state, self.updated, self.blocked):
            if not self.after_block_change(dict(sender=sender, observed=observed)):
                continue
            row = dict(id=str(uuid4()), session=self.session, account=state['account'], lobby=state['lobby'],
                       sender=sender, name=name, body='', received=time.time(), own=0,
                       status='received', echo=0, kind=kind)
            if not self.save_message(row):
                self.volatile[row['id']] = row
                while len(self.volatile) > 200:
                    self.volatile.popitem(last=False)
        self.revision += 1

    def end(self, reason):
        for pending in self.pending:
            if pending.get("status", "pending") == "pending":
                self.result(pending["id"], "unknown")
        if self.session:
            self.write(self.store.end, self.session, reason)

    def fresh(self):
        return self.clock() - self.updated < 2.5

    def connected(self):
        return self.fresh() and self.state.get("connected", False)

    def verified(self):
        return self.connected() and self.state.get("lobby_verified", False)

    def allowed(self):
        if not self.verified() or self.blocked is None:
            return set()
        return set(self.state.get('members') or []) - self.blocked.keys()

    def can_send(self):
        return bool(self.session and self.verified()
                    and self.state.get("send_enabled") and not self.storage_error)

    def context(self):
        return {k: self.state.get(k, "") for k in ("account", "lobby", "generation")}

    def profile_targets(self, lobby=None):
        context = self.context()
        if not self.verified() or not all(context.values()) or lobby not in (None, context['lobby']):
            return set()
        return (self.allowed() & self.state.get('profiles', {}).keys()) - {context['account']}

    def profile_uri(self, steam_id, context):
        uri = steam_profile_uri(steam_id)
        if context != self.context() or steam_id not in self.profile_targets():
            raise ValueError('steam_profile_unavailable')
        return uri

    def prepare(self, context, text):
        encode(text)
        if context != self.context() or not self.can_send():
            raise ValueError("connection_changed")
        account = context["account"]
        row = dict(id=str(uuid4()), session=self.session, account=account, lobby=context["lobby"],
                   sender=account, name=self.state.get("profiles", {}).get(account, {}).get("name", ""),
                   body=text, received=time.time(), own=1, status="pending", echo=0)
        self.save_message(row)
        if self.storage_error:
            row["status"] = "failed"
            self.volatile[row["id"]] = row
            raise ValueError("storage_failed_before_send")
        self.pending.append({"id": row["id"], "text": text, "context": context,
                             "started": self.clock(), "matched": False})
        self.revision += 1
        return {"type": "send", "id": row["id"], "text": text, "context": context}

    def result(self, id, status):
        if status not in {"accepted", "failed", "unknown"}:
            status = "unknown"
        pending = next((p for p in self.pending if p["id"] == id), None)
        if status == "failed" and pending and pending.get("echo_row"):
            self.write(self.store.reject_echo, id, pending["echo_row"])
        else:
            self.write(self.store.status, id, status)
        for pending in self.pending:
            if pending["id"] == id:
                pending["status"] = status
        if status == "failed":
            self.pending = deque((p for p in self.pending if p["id"] != id), maxlen=200)
        self.revision += 1

    def receive(self, event):
        # The adapter already copied the payload and assigned this app UUID.
        if event["context"] != self.context() or not self.session or not self.verified():
            return
        if is_meow_message(event["text"]):
            return
        receipt = event["id"]
        if receipt in self.receipts:
            return
        try:
            if self.store.seen(receipt):
                return
        except (sqlite3.Error, OSError):
            self.storage_error = True
        self.receipts[receipt] = True
        while len(self.receipts) > 4096:
            self.receipts.popitem(last=False)
        sender = event["sender"]
        account = self.state["account"]
        if sender != account and (sender not in self.allowed() or not self.after_block_change(event)):
            return
        now = self.clock()
        row = dict(id=receipt, session=self.session, account=account, lobby=self.state["lobby"],
                   sender=sender, name=self.state.get("profiles", {}).get(sender, {}).get("name", ""),
                   body=event["text"], received=event.get("received", time.time()), own=int(sender == account),
                   status="received", echo=0)
        # FIFO is a correspondence candidate, never a globally unique Steam ID.
        # Separate callbacks with identical text remain separate utterances.
        candidates = [p for p in self.pending if not p["matched"] and p["text"] == event["text"]
                      and p["context"] == event["context"] and 0 <= now-p["started"] <= 5]
        if sender == account and candidates:
            candidates[0]["matched"] = True
            candidates[0]["echo_row"] = row
            self.write(self.store.echo, candidates[0]["id"], receipt)
        else:
            saved = self.save_message(row, receipt)
            if not saved:
                self.volatile[receipt] = row
                while len(self.volatile) > 200:
                    self.volatile.popitem(last=False)
        self.revision += 1
        if sender != account:
            return AcceptedIncoming(receipt, sender, **self.context())

    def reaction_allowed(self, event):
        sender = event["sender"]
        return (self.reactions_enabled and event["observed"] >= self.reactions_enabled_since
                and self.verified() and event["context"] == self.context()
                and self.after_block_change(event)
                and sender in self.state.get("profiles", {})
                and (sender == self.state.get("account") or sender in self.allowed())
                and 0 <= self.clock() - event["observed"] < REACTION_TTL)

    def receive_reaction(self, event):
        if (not self.reaction_allowed(event) or event["id"] in self.reaction_receipts
                or not png(event.get("avatar")) or event.get("kind") not in {"meow", "emote"}
                or event["kind"] == "emote" and not png(event.get("image"))
                or event["kind"] == "meow" and not is_meow_message(event.get("text", ""))):
            return
        self.reaction_receipts.append(event["id"])
        self.reactions.append(event)  # Keep the newest bounded batch for the UI.

    def take_reactions(self, lobby, enabled):
        events = list(self.reactions)
        self.reactions.clear()
        if not enabled or lobby != self.state.get("lobby"):
            return []
        return [dict({k: event[k] for k in ("id", "sender", "kind", "avatar", "text", "image") if k in event},
                     expires_in_ms=max(0, int((REACTION_TTL - (self.clock() - event['observed'])) * 1000)))
                for event in events if self.reaction_allowed(event)]

    def view(self, lobby=None, query="", before=None, start=None, seen=None, limit=100):
        account = self.state.get("account", "")
        lobby = lobby or self.state.get("lobby", "")
        allowed = self.allowed()
        history_blocks = set(self.blocked) if self.verified() and self.blocked is not None else None
        theme, collapsed = 'system', False
        page = dict(messages=[], has_more=False, has_newer=False, latest_seq=0, unseen=False, unseen_seq=0)
        try:
            if account and lobby:
                page = self.store.message_page(account, lobby, allowed, query, before, limit, start, seen,
                                               blocked=history_blocks)
            rows = page['messages']
            rooms = self.store.rooms(account) if account else []
            draft = self.store.draft(account, lobby) if account and lobby else ""
            theme = self.store.setting('theme', default='system')
            collapsed = self.store.setting('collapsed', default=False)
        except (sqlite3.Error, OSError):
            self.storage_error = True
            rows, rooms, draft = [], [], ""
            page = dict(has_more=False, has_newer=False, latest_seq=0, unseen=False, unseen_seq=0)
        if self.connected() and self.state.get("name"):
            # Live display is independent of persistence; storage_error still
            # reports a failed write and keeps sending disabled.
            rooms = [dict(room, name=self.state["name"]) if room["lobby"] == self.state.get("lobby") else room
                     for room in rooms]
        def visible_sender(sender):
            return sender == account or history_blocks is not None and sender not in history_blocks
        visible_volatile = [r for r in self.volatile.values() if r["account"] == account
                            and r["lobby"] == lobby and visible_sender(r["sender"]) and not is_meow_message(r["body"])]
        volatile = [dict(r, unsaved=True) for r in self.volatile.values() if r["account"] == account
                    and r["lobby"] == lobby and visible_sender(r["sender"])
                    and not is_meow_message(r["body"])
                    and (not query or r.get('kind', 'chat') == 'chat' and query.lower() in r["body"].lower()) and before is None
                    and (start is None or r.get('_before_seq', float('inf')) >= start)
                    and (not page['has_newer'] or rows and r.get('_before_seq', float('inf')) <= rows[-1]['seq'])]
        messages = sorted(rows + volatile, key=lambda r: (
            r.get('seq', r.get('_before_seq', float('inf'))), not r.get('unsaved', False)))
        for message in messages:
            message.pop('_before_seq', None)
        profiles = {uid: p for uid, p in self.state.get("profiles", {}).items() if uid in allowed | {account}}
        return {"context": self.context(), "state": self.state.get("state"), "notice": self.state.get("notice", ""),
                "game_build": self.state.get("game_build", ""),
                "connected": self.connected(), "lobby_verified": self.verified(),
                "blocks_ready": self.blocked is not None,
                "blocked_users": [dict(steam_id=uid, name=name) for uid, name in sorted((self.blocked or {}).items())],
                "participants": {uid: dict(p, blocked=uid in (self.blocked or {}))
                                 for uid, p in self.state.get('profiles', {}).items()
                                 if self.verified() and self.blocked is not None and uid in (self.state.get('members') or [])},
                "can_send": self.can_send() and lobby == self.state.get("lobby"),
                "profile_targets": sorted(self.profile_targets(lobby)),
                "rooms": rooms, "messages": messages, "profiles": profiles, "draft": draft,
                "storage_error": self.storage_error, "revision": self.revision,
                "theme": theme, "collapsed": collapsed,
                "notifications": dict(self.notifications),
                "reactions_enabled": self.reactions_enabled,
                "lobby": lobby, "has_more": page['has_more'], "has_newer": page['has_newer'],
                "latest_seq": page['latest_seq'], "unseen": page['unseen'], "unseen_seq": page['unseen_seq'],
                "volatile_peer_ids": [r['id'] for r in visible_volatile if not r['own'] and r.get('kind', 'chat') == 'chat']}
