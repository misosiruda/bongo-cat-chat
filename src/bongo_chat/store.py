"""Account-scoped SQLite history. All callers use one owning thread."""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import time

from .protocol import is_meow_message

RETENTION_SECONDS = 30 * 24 * 60 * 60
SCHEMA_VERSION = 2
MESSAGE_COLUMNS = "id,session,account,lobby,sender,name,body,received,own,status,echo,kind"


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=0.25)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("is_meow_message", 1, is_meow_message, deterministic=True)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            self.db.close()
            raise RuntimeError("unsupported_database_version")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY, account TEXT NOT NULL, lobby TEXT NOT NULL,
                name TEXT NOT NULL, started REAL NOT NULL, ended REAL, reason TEXT);
            CREATE TABLE IF NOT EXISTS messages(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                session TEXT NOT NULL REFERENCES sessions(id), account TEXT NOT NULL,
                lobby TEXT NOT NULL, sender TEXT NOT NULL, name TEXT NOT NULL,
                body TEXT NOT NULL, received REAL NOT NULL, own INTEGER NOT NULL,
                status TEXT NOT NULL, echo INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS message_room ON messages(account,lobby,seq);
            CREATE INDEX IF NOT EXISTS message_age ON messages(received);
            CREATE TABLE IF NOT EXISTS receipts(
                id TEXT PRIMARY KEY, message TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS drafts(
                account TEXT NOT NULL, lobby TEXT NOT NULL, body TEXT NOT NULL,
                changed REAL NOT NULL, PRIMARY KEY(account,lobby));
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        with self.db:
            self.db.execute('BEGIN')
            # Additive migration: keep existing rows, IDs, receipts and sequence.
            # Older apps reject version 2 instead of displaying notices as chat.
            if 'kind' not in {row['name'] for row in self.db.execute('PRAGMA table_info(messages)')}:
                self.db.execute("ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat' "
                                "CHECK(kind IN ('chat','member_joined','member_left'))")
            self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            self.db.execute("UPDATE messages SET status='unknown' WHERE status='pending'")
            self.db.execute("UPDATE sessions SET ended=?,reason='app_interrupted' WHERE ended IS NULL", (time.time(),))
        self.prune()

    def session(self, session, account, lobby, name):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?,?,?,NULL,NULL)",
                            (session, account, lobby, name, time.time()))

    def end(self, session, reason):
        with self.db:
            self.db.execute("UPDATE sessions SET ended=?,reason=? WHERE id=? AND ended IS NULL",
                            (time.time(), reason, session))

    def _insert(self, row):
        cursor = self.db.execute(f"INSERT OR IGNORE INTO messages({MESSAGE_COLUMNS}) VALUES({','.join('?' for _ in MESSAGE_COLUMNS.split(','))})",
                                 tuple(row.get('kind', 'chat') if k == 'kind' else row[k] for k in MESSAGE_COLUMNS.split(',')))
        if cursor.rowcount:
            return cursor.lastrowid
        return self.db.execute("SELECT seq FROM messages WHERE id=?", (row['id'],)).fetchone()[0]

    def add(self, row, receipt=None):
        with self.db:
            sequence = self._insert(row)
            if receipt:
                self.db.execute("INSERT OR IGNORE INTO receipts VALUES(?,?)", (receipt, row['id']))
        return sequence

    def seen(self, receipt):
        return self.db.execute("SELECT 1 FROM receipts WHERE id=?", (receipt,)).fetchone() is not None

    def status(self, id, status):
        with self.db:
            self.db.execute("UPDATE messages SET status=? WHERE id=?", (status, id))

    def echo(self, id, receipt):
        with self.db:
            self.db.execute("UPDATE messages SET echo=1 WHERE id=?", (id,))
            self.db.execute("INSERT OR IGNORE INTO receipts VALUES(?,?)", (receipt, id))

    def reject_echo(self, intent, received):
        # A failed native send cannot own the earlier same-text game utterance.
        with self.db:
            self.db.execute("UPDATE messages SET status='failed',echo=0 WHERE id=?", (intent,))
            self._insert(received)
            self.db.execute("UPDATE receipts SET message=? WHERE id=? AND message=?",
                            (received["id"], received["id"], intent))

    @contextmanager
    def visible(self, account, allowed):
        # A verified allow-list, not NOT IN(hidden): unknown users are also excluded.
        with self.db:
            self.db.execute("CREATE TEMP TABLE IF NOT EXISTS visible_users(id TEXT PRIMARY KEY)")
            self.db.execute("DELETE FROM visible_users")
            self.db.executemany("INSERT OR IGNORE INTO visible_users VALUES(?)", ((uid,) for uid in allowed | {account}))
            try:
                yield
            finally:
                self.db.execute("DELETE FROM visible_users")

    def message_page(self, account, lobby, allowed, query="", before=None, limit=100, start=None, seen=None):
        """A bounded, freshly filtered window plus navigation and unread metadata."""
        limit = max(1, min(1000, int(limit)))
        cutoff = time.time() - RETENTION_SECONDS
        scope = "account=? AND lobby=? AND sender IN (SELECT id FROM visible_users) AND received>=? AND is_meow_message(body)=0"
        matching = scope + " AND (?='' OR (kind='chat' AND instr(lower(body),lower(?))>0))"
        params = (account, lobby, cutoff, query, query)
        with self.visible(account, allowed):
            bounds = " AND (? IS NULL OR seq<?) AND (? IS NULL OR seq>=?)"
            order = "ASC" if start is not None else "DESC"
            fetched = self.db.execute(f"SELECT * FROM messages WHERE {matching}{bounds} ORDER BY seq {order} LIMIT ?",
                                     (*params, before, before, start, start, limit + 1)).fetchall()
            rows = fetched[:limit] if start is not None else list(reversed(fetched[:limit]))
            first = rows[0]['seq'] if rows else start
            last = rows[-1]['seq'] if rows else before
            has_more = first is not None and self.db.execute(
                f"SELECT EXISTS(SELECT 1 FROM messages WHERE {matching} AND seq<?)", (*params, first)).fetchone()[0]
            has_newer = last is not None and self.db.execute(
                f"SELECT EXISTS(SELECT 1 FROM messages WHERE {matching} AND seq>?)", (*params, last)).fetchone()[0]
            latest_seq = self.db.execute(f"SELECT coalesce(max(seq),0) FROM messages WHERE {scope}",
                                         (account, lobby, cutoff)).fetchone()[0]
            unseen_seq = 0 if seen is None else self.db.execute(
                f"SELECT coalesce(max(seq),0) FROM messages WHERE {scope} AND kind='chat' AND sender<>? AND seq>?",
                (account, lobby, cutoff, account, seen)).fetchone()[0]
        return dict(messages=[dict(r) for r in rows], has_more=bool(has_more), has_newer=bool(has_newer),
                    latest_seq=latest_seq, unseen=bool(unseen_seq), unseen_seq=unseen_seq)

    def messages(self, account, lobby, allowed, query="", before=None, limit=100):
        return self.message_page(account, lobby, allowed, query, before, limit)['messages']

    def rooms(self, account):
        return [dict(r) for r in self.db.execute("""SELECT lobby,max(started) started,
            (SELECT name FROM sessions s2 WHERE s2.account=s.account AND s2.lobby=s.lobby
                ORDER BY started DESC LIMIT 1) name, count(*) segments
            FROM sessions s WHERE account=? GROUP BY lobby ORDER BY started DESC""", (account,))]

    def draft(self, account, lobby, text=None):
        if text is not None:
            if not isinstance(text, str) or len(text) > 4000:
                raise ValueError("invalid_draft")
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO drafts VALUES(?,?,?,?)", (account, lobby, text, time.time()))
        row = self.db.execute("SELECT body FROM drafts WHERE account=? AND lobby=? AND changed>=?",
                              (account, lobby, time.time()-RETENTION_SECONDS)).fetchone()
        return row[0] if row else ""

    def setting(self, key, value=None, default=None):
        if value is not None:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def delete(self, account, lobby=None):
        with self.db:
            for table in ("messages", "drafts"):
                self.db.execute(f"DELETE FROM {table} WHERE account=? AND (? IS NULL OR lobby=?)", (account, lobby, lobby))
            self.db.execute("DELETE FROM sessions WHERE account=? AND ended IS NOT NULL AND (? IS NULL OR lobby=?)", (account,lobby,lobby))
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def prune(self):
        cutoff = time.time() - RETENTION_SECONDS
        with self.db:
            self.db.execute("DELETE FROM messages WHERE received<?", (cutoff,))
            self.db.execute("DELETE FROM drafts WHERE changed<?", (cutoff,))
            self.db.execute("DELETE FROM sessions WHERE ended<? AND id NOT IN (SELECT session FROM messages)", (cutoff,))
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self):
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
