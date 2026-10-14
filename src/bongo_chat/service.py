"""Message state and privacy boundary, independent of Qt and Steam."""
from collections import OrderedDict, deque
import sqlite3
import time
from uuid import uuid4

from .protocol import encode


class ChatService:
    def __init__(self, store, clock=time.monotonic):
        self.store, self.clock = store, clock
        self.state = {"state": "checking", "account": "", "lobby": "", "generation": "",
                      "hidden_ok": False, "profiles": {}, "hidden": {}}
        self.updated = 0.0
        self.session = ""
        self.storage_error = False
        self.volatile = OrderedDict()
        self.pending = deque(maxlen=200)
        self.receipts = OrderedDict()
        self.revision = 0

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
            self.store.session(self.session, self.state['account'], self.state['lobby'], self.state.get('name') or '게임 로비')
        self.storage_error = False

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
        old = self.state
        boundary = (old.get("account"), old.get("lobby"), old.get("generation")) != (
            state.get("account"), state.get("lobby"), state.get("generation"))
        if boundary:
            self.end("connection_changed")
            self.pending.clear()
            self.volatile.clear()
            self.session = ""
        self.state = dict(state)
        self.updated = self.clock()
        if state.get("account") and state.get("lobby") and state.get("generation") and not self.session:
            self.session = str(uuid4())
            self.write(self.store.session, self.session, state["account"], state["lobby"], state.get("name") or "게임 로비")
        self.revision += 1

    def end(self, reason):
        for pending in self.pending:
            if pending.get("status", "pending") == "pending":
                self.result(pending["id"], "unknown")
        if self.session:
            self.write(self.store.end, self.session, reason)

    def fresh(self):
        return self.clock() - self.updated < 2.5 and self.state.get("hidden_ok", False)

    def allowed(self):
        if not self.fresh():
            return set()
        return {uid for uid, hidden in self.state.get("hidden", {}).items() if hidden is False}

    def can_send(self):
        return bool(self.session and self.fresh() and self.state.get("state") == "ready"
                    and self.state.get("send_enabled") and not self.storage_error)

    def context(self):
        return {k: self.state.get(k, "") for k in ("account", "lobby", "generation")}

    def prepare(self, context, text):
        encode(text)
        if context != self.context() or not self.can_send():
            raise ValueError("connection_changed")
        account = context["account"]
        row = dict(id=str(uuid4()), session=self.session, account=account, lobby=context["lobby"],
                   sender=account, name=self.state.get("profiles", {}).get(account, {}).get("name", "나"),
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
        if event["context"] != self.context() or not self.session:
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
        if sender != account and sender not in self.allowed():
            return
        now = self.clock()
        row = dict(id=receipt, session=self.session, account=account, lobby=self.state["lobby"],
                   sender=sender, name=self.state.get("profiles", {}).get(sender, {}).get("name", "이름 확인 중"),
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

    def view(self, lobby=None, query="", before=None):
        account = self.state.get("account", "")
        lobby = lobby or self.state.get("lobby", "")
        allowed = self.allowed()
        theme, collapsed = 'system', False
        try:
            rows = self.store.messages(account, lobby, allowed, query, before) if account and lobby else []
            rooms = self.store.rooms(account) if account else []
            draft = self.store.draft(account, lobby) if account and lobby else ""
            theme = self.store.setting('theme', default='system')
            collapsed = self.store.setting('collapsed', default=False)
        except (sqlite3.Error, OSError):
            self.storage_error = True
            rows, rooms, draft = [], [], ""
        volatile = [dict(r, unsaved=True) for r in self.volatile.values() if r["account"] == account
                    and r["lobby"] == lobby and r["sender"] in allowed | {account}
                    and query.lower() in r["body"].lower() and before is None]
        messages = sorted(rows + volatile, key=lambda r: (
            r.get('seq', r.get('_before_seq', float('inf'))), not r.get('unsaved', False)))
        for message in messages:
            message.pop('_before_seq', None)
        profiles = {uid: p for uid, p in self.state.get("profiles", {}).items() if uid in allowed | {account}}
        return {"context": self.context(), "state": self.state.get("state"), "notice": self.state.get("notice", ""),
                "game_build": self.state.get("game_build", ""),
                "hidden_ok": self.fresh(), "can_send": self.can_send() and lobby == self.state.get("lobby"),
                "rooms": rooms, "messages": messages, "profiles": profiles, "draft": draft,
                "storage_error": self.storage_error, "revision": self.revision,
                "theme": theme, "collapsed": collapsed,
                "lobby": lobby, "has_more": len(rows) == 100}
