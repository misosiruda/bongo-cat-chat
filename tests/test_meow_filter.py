"""Offline regressions for localized click-meows; no game or Steam calls."""
import ctypes as C
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

import pytest

from bongo_chat.protocol import decode, encode
from bongo_chat.service import ChatService
from bongo_chat.steam import Callback, ChatHeader, Steam
from bongo_chat.store import Store


LOCALIZATIONS = json.loads(
    (Path(__file__).parent / "fixtures/meow-localizations.json").read_text(encoding="utf-8")
)["localizations"]
CONTEXT = {"account": "30", "lobby": "10", "generation": "fixture-segment"}


def connect(store):
    service = ChatService(store, clock=lambda: 1.0)
    service.update(dict(CONTEXT, state="ready", connected=True, lobby_verified=True,
                        privacy_ready=True, hidden_ok=True, hidden={"20": False},
                        profiles={}, send_enabled=True, name="테스트 로비"))
    return service


@pytest.fixture
def service(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    try:
        yield connect(store)
    finally:
        store.close()


def message(service, text, sender="20"):
    return dict(id=str(uuid4()), context=service.context(), sender=sender, text=text)


@pytest.mark.parametrize("locale,text", LOCALIZATIONS.items(), ids=LOCALIZATIONS)
def test_all_shipped_localized_meows_are_discarded(locale, text):
    assert decode(encode(text)) is None


@pytest.mark.parametrize("text", [
    "meow meow", "  Meow Meow\n", "\r\nMeow Meow\r\n", "miau miau", "Mn\u030cau Mn\u030cau",
])
def test_whole_message_matching_normalizes_case_outer_space_and_unicode(text):
    assert decode(encode(text)) is None


@pytest.mark.parametrize("text", [
    "야옹", "야옹야옹", "야옹 야옹 해주세요", "meow", "Meow Meow!",
    "I heard Meow Meow", "Meow Meow\n안녕하세요", "Meow Meow\r\n안녕하세요", "Miau Miau?",
    "にゃんにゃ～んって鳴いた", "喵~喵~ 你好", "Miyav Miyav :)",
])
def test_normal_conversation_is_preserved_verbatim(text):
    assert decode(encode(text)) == text


@pytest.mark.parametrize("sender", ["20", "30"], ids=["peer", "self"])
def test_callback_routes_meows_away_from_messages_and_frees_every_callback(service, sender):
    steam = Steam.__new__(Steam)
    steam.pipe = steam.matchmaking = 1
    steam.rejected = 0
    texts = [*LOCALIZATIONS.values(), "야옹 야옹 해주세요"]
    raw_packets = [encode(text) for text in texts]
    cursor = 0
    header = None
    active = False
    freed = []
    steam.run_frame = lambda pipe: None

    def next_callback(pipe, out):
        nonlocal header, active
        assert not active
        if cursor == len(raw_packets):
            return False
        header = ChatHeader(10, int(sender), 1, cursor)
        callback = C.cast(out, C.POINTER(Callback)).contents
        callback.kind = 507
        callback.size = C.sizeof(header)
        callback.data = C.addressof(header)
        active = True
        return True

    def read_entry(mm, lobby, chat_id, out_sender, buffer, size, entry_type):
        assert active and chat_id == cursor
        C.cast(out_sender, C.POINTER(C.c_uint64))[0] = int(sender)
        C.cast(entry_type, C.POINTER(C.c_int))[0] = 1
        raw = raw_packets[cursor]
        C.memmove(buffer, raw, len(raw))
        return len(raw)

    def free_callback(pipe):
        nonlocal cursor, active
        assert active
        freed.append(cursor)
        C.memset(C.addressof(header), 0, C.sizeof(header))
        cursor += 1
        active = False

    steam.next_callback = next_callback
    steam.read_entry = read_entry
    steam.free_callback = free_callback
    events = steam.pump(service.context(), {sender})
    assert freed == list(range(len(texts)))
    assert steam.rejected == 0
    reactions = [event for event in events if event['type'] == 'reaction']
    assert len(reactions) == len(LOCALIZATIONS)
    assert all(event['kind'] == 'meow' for event in reactions)
    messages = [event for event in events if event['type'] == 'message']
    assert [event["text"] for event in messages] == ["야옹 야옹 해주세요"]
    for event in messages:
        service.receive(event)
    assert [row["body"] for row in service.view()["messages"]] == ["야옹 야옹 해주세요"]
    assert service.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    assert service.store.db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


@pytest.mark.parametrize("sender", ["20", "30"], ids=["peer", "self"])
@pytest.mark.parametrize("broken_storage", [False, True])
def test_filtered_receive_never_stores_or_creates_unsaved_message(service, monkeypatch, sender, broken_storage):
    if broken_storage:
        def fail(*args):
            raise sqlite3.OperationalError("fixture storage failure")
        monkeypatch.setattr(service.store, "seen", fail)
        monkeypatch.setattr(service.store, "add", fail)
    revision = service.revision
    for text in LOCALIZATIONS.values():
        service.receive(message(service, text, sender))
    assert not service.volatile and not service.receipts and not service.storage_error
    assert service.revision == revision
    assert service.view()["messages"] == []
    assert service.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


def test_legacy_history_filter_precedes_pagination_and_search_and_survives_reopen(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with_legacy = ["일반 대화 %03d · 야옹 야옹 해주세요" % i for i in range(101)]
    with_legacy += list(LOCALIZATIONS.values()) * 4
    store = Store(path)
    try:
        service = connect(store)
        # Simulate rows already stored by the old version, including own messages.
        for i, text in enumerate(with_legacy):
            store.add(dict(id=str(uuid4()), session=service.session, account="30", lobby="10",
                           sender="30" if i % 2 else "20", name="가상 사용자", body=text,
                           received=time.time(), own=i % 2, status="received", echo=0))
    finally:
        store.close()
    store = Store(path)
    try:
        service = connect(store)
        current = service.view()
        assert [row["body"] for row in current["messages"]] == with_legacy[1:101]
        assert current["has_more"] is True
        older = service.view(before=current["messages"][0]["seq"])
        assert [row["body"] for row in older["messages"]] == with_legacy[:1]
        assert older["has_more"] is False
        assert service.view(query="Meow Meow")["messages"] == []
        assert len(service.view(query="야옹 야옹")["messages"]) == 100
        # Hiding history does not delete it or change the database schema.
        assert store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == len(with_legacy)
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        store.close()


def test_unsaved_meow_is_hidden_without_hiding_normal_unsaved_text(service, monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError("fixture storage failure")
    monkeypatch.setattr(service.store, "add", fail)
    with pytest.raises(ValueError, match="storage_failed_before_send"):
        service.prepare(service.context(), "Meow Meow")
    service.receive(message(service, "일반 메시지"))
    rows = service.view()["messages"]
    assert len(rows) == 1 and rows[0]["body"] == "일반 메시지" and rows[0]["unsaved"]
