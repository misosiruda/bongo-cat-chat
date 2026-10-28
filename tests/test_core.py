import hashlib
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import pytest

from bongo_chat.protocol import InvalidMessage, decode, encode
from bongo_chat.service import ChatService
from bongo_chat.store import RETENTION_SECONDS, Store
from bongo_chat.worker import LiveConnection


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "history.sqlite3")
    yield value
    value.close()


def state(**changes):
    return dict(dict(state="ready", account="fixture-self", lobby="fixture-room-a", generation="fixture-segment-a",
        connected=True, lobby_verified=True, privacy_ready=changes.get("hidden_ok", True),
        hidden_ok=True, hidden={"fixture-peer":False}, members=["fixture-self", "fixture-peer"], profiles={}, send_enabled=True, name="테스트 로비"), **changes)


@pytest.fixture
def service(store):
    # Unit fixtures do not have a live worker heartbeat. Keep elapsed time
    # explicit; stale-state tests below use their own advancing clock.
    result = ChatService(store, clock=lambda: 100.0)
    result.update(state())
    return result


def received(service, text="검증 문장", sender="fixture-peer", id=None, context=None):
    event = dict(id=id or str(uuid4()), text=text, sender=sender, context=context or service.context())
    service.receive(event)
    return event


def test_native_korean_reference():
    packet = encode("인코딩 확인 가나123")
    assert len(packet) == 52
    assert hashlib.sha256(packet).hexdigest() == "97c2802e18cdfb7581ad9ef1a160a892b65c9e24ca1999d2d63382129051d502"
    assert decode(packet) == "인코딩 확인 가나123"


@pytest.mark.parametrize("packet", [b"\xff", b"[]", b"null", b'{"Channel":3.0,"Message":"x"}',
    b'{"Channel":true,"Message":"x"}', b'{"Channel":3,"Message":1}', b'{"Channel":3,"Message":""}',
    b'{"Channel":3,"Channel":3,"Message":"x"}', b'{"Channel":3,"Message":"x"}\x00', b"x"*4097,
    b'{"Channel":3,"Message":"\\ud800"}', b'{"Channel":3,"Message":"a\\u0000b"}'])
def test_malformed_packets(packet):
    with pytest.raises(InvalidMessage):
        decode(packet)


def test_other_channels_discarded():
    assert decode(b'{"Channel":2,"Message":"ignore"}') is None


def test_utf16_guard_and_escaping():
    assert decode(encode('따옴표 " 역슬래시 \\ \n다음 줄')) == '따옴표 " 역슬래시 \\ \n다음 줄'
    encode("가"*50)
    with pytest.raises(InvalidMessage):
        encode("가"*51)
    with pytest.raises(InvalidMessage):
        encode("🙂"*26)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_multiline_protocol_preserves_text(newline):
    text = newline.join(['첫 줄 "따옴표"', '', '마지막 줄\t🙂'])
    # Construct the incoming packet independently of our outbound encoder.
    raw = json.dumps({"Channel": 3, "Message": text}, ensure_ascii=False).encode("utf-8")
    assert decode(raw) == text
    encoded = encode(text)
    assert json.loads(encoded)["Message"] == text
    assert b"\r" not in encoded and b"\n" not in encoded
    encode("가" * (50 - len(newline)) + newline)
    with pytest.raises(InvalidMessage, match="development_limit_50"):
        encode("가" * (51 - len(newline)) + newline)


@pytest.mark.parametrize("text", ["\r", "\r\n", " \r\n\t "])
def test_line_breaks_only_are_still_empty(text):
    with pytest.raises(InvalidMessage, match="empty_text"):
        decode(json.dumps({"Channel": 3, "Message": text}).encode("utf-8"))
    with pytest.raises(InvalidMessage, match="empty_text"):
        encode(text)


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"], ids=["lf", "crlf", "cr"])
def test_unescaped_line_breaks_inside_json_strings_are_still_rejected(newline):
    raw = b'{"Channel":3,"Message":"first' + newline + b'second"}'
    with pytest.raises(InvalidMessage, match="invalid_json"):
        decode(raw)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_multiline_sent_message_keeps_exact_echo_matching(service, newline):
    text = newline.join(["내 첫 줄", "내 둘째 줄"])
    command = service.prepare(service.context(), text)
    service.result(command["id"], "accepted")
    received(service, decode(encode(text)), sender="fixture-self")
    rows = service.view()["messages"]
    assert len(rows) == 1
    assert rows[0]["body"] == text and rows[0]["echo"] == 1


@pytest.mark.parametrize("control", ["\0", "\v", "\f", "\x1b", "\x7f", "\x85", "\ud800"])
def test_multiline_does_not_allow_other_controls(control):
    text = "첫 줄\r\n둘째 줄" + control
    raw = json.dumps({"Channel": 3, "Message": text}).encode("utf-8")
    with pytest.raises(InvalidMessage, match="control_character"):
        decode(raw)
    with pytest.raises(InvalidMessage, match="control_character"):
        encode(text)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_multiline_receive_survives_history_reopen_and_search(tmp_path, newline):
    text = newline.join(["첫 번째 합성 검증 문장입니다.", "", "두 번째 합성 검증 문장입니다.",
                         "마지막 검색용 검증 문장입니다."])
    assert len(text.encode("utf-16-le")) // 2 > 50  # Only sending has this limit.
    raw = json.dumps({"Channel": 3, "Message": text}, ensure_ascii=False).encode("utf-8")
    path = tmp_path / "multiline.sqlite3"
    for initial in (True, False):
        store = Store(path)
        try:
            service = ChatService(store, clock=lambda: 1.0)
            service.update(state())
            if initial:
                received(service, decode(raw))
            assert [row["body"] for row in service.view()["messages"]] == [text]
            assert [row["body"] for row in service.view(query="검색용")["messages"]] == [text]
        finally:
            store.close()


@pytest.mark.parametrize("echo_first", [True, False])
def test_echo_order_and_real_repeats(service, echo_first):
    commands = []
    for _ in range(2):
        command = service.prepare(service.context(), "반복 발언")
        commands.append(command)
        if not echo_first:
            service.result(command["id"], "accepted")
        received(service,"반복 발언","fixture-self")
        if echo_first:
            service.result(command["id"], "accepted")
    rows = service.view()["messages"]
    assert len(rows) == 2 and all(r["echo"] == 1 and r["status"] == "accepted" for r in rows)
    # Native game sending the same text is another utterance, not global text dedup.
    received(service,"반복 발언","fixture-self")
    assert len(service.view()["messages"]) == 3


def test_internal_receipt_idempotent_separate_callbacks_retained(service):
    event = received(service)
    service.receive(event)
    assert len(service.view()["messages"]) == 1
    received(service)
    assert len(service.view()["messages"]) == 2


def test_failed_send_restores_tentatively_merged_game_message(service):
    command = service.prepare(service.context(), "동시에 같은 문장")
    event = received(service, "동시에 같은 문장", "fixture-self")
    service.result(command["id"], "failed")
    service.receive(event)
    rows = service.view()["messages"]
    assert len(rows) == 2
    assert rows[0]["status"] == "failed" and rows[0]["echo"] == 0
    assert rows[1]["id"] == event["id"] and rows[1]["status"] == "received"
    assert service.store.seen(event["id"])


def test_read_queries_release_transaction_and_visible_users(service):
    received(service)
    assert service.view()["messages"]
    assert not service.store.db.in_transaction
    assert service.store.db.execute("SELECT count(*) FROM visible_users").fetchone()[0] == 0


def test_lobby_transition_old_send_and_late_event(service):
    old = service.context()
    service.store.draft(old["account"],old["lobby"],"이전 방 초안")
    service.update(state(lobby="fixture-room-b",generation="fixture-segment-b"))
    with pytest.raises(ValueError):
        service.prepare(old,"오발송 금지")
    received(service,context=old)
    assert not service.view()["messages"]
    assert service.view()["draft"] == ""
    assert service.store.draft(old["account"],old["lobby"]) == "이전 방 초안"


def test_rejoin_creates_separate_segment_and_does_not_merge(service):
    service.prepare(service.context(),"같은 문장")
    service.update(state(lobby="fixture-room-b",generation="fixture-segment-b"))
    service.update(state(generation="fixture-segment-c"))
    received(service,"같은 문장","fixture-self")
    rows=service.view()["messages"]
    assert len(rows)==2 and rows[0]["session"] != rows[1]["session"] and rows[0]["status"] == "unknown"


def test_block_filters_history_search_profile_and_new_storage(service):
    received(service)
    service.blocked['fixture-peer'] = '합성 차단 대상'
    assert service.view(query="검증")["messages"] == []
    assert not service.view()["profiles"]
    received(service,"숨김 중 저장하지 않음")
    assert service.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    service.blocked.clear()
    assert len(service.view()["messages"]) == 1


@pytest.mark.parametrize("changes", [{"hidden_ok":False},{"hidden":{}},{"hidden":{"fixture-peer":None}}])
def test_game_hidden_state_does_not_filter_chat(service,changes):
    received(service)
    service.update(state(**changes))
    received(service)
    assert len(service.view()["messages"]) == 2


def test_stale_snapshot_blocks_display_storage_and_send(store):
    clock=[100.0]
    service=ChatService(store,lambda:clock[0]); service.update(state())
    received(service)
    clock[0]+=3
    assert not service.can_send() and not service.view()["messages"]
    received(service)
    assert store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_account_isolation(service):
    received(service)
    service.update(state(account="fixture-second",generation="fixture-other"))
    assert not service.view()["messages"]
    assert service.view()["draft"] == ""


def test_restart_persists_and_pending_becomes_unknown(tmp_path):
    path=tmp_path / "history.sqlite3"
    s=Store(path); service=ChatService(s); service.update(state())
    command=service.prepare(service.context(),"재시작 저장")
    s.close()
    reopened=Store(path)
    assert reopened.db.execute("SELECT status FROM messages WHERE id=?",(command["id"],)).fetchone()[0]=="unknown"
    assert len(reopened.messages("fixture-self","fixture-room-a",set(),"재시작"))==1
    assert reopened.db.execute("SELECT reason FROM sessions").fetchone()[0]=="app_interrupted"
    reopened.close()


def test_storage_error_does_not_send_or_claim_saved(service,monkeypatch):
    def fail(*args): raise sqlite3.OperationalError("synthetic disk full")
    monkeypatch.setattr(service.store,"add",fail)
    with pytest.raises(ValueError,match="storage_failed"):
        service.prepare(service.context(),"저장 실패")
    received(service)
    view=service.view()
    assert view["storage_error"] and not view["can_send"] and any(r["unsaved"] for r in view["messages"])


@pytest.mark.parametrize('clock_step', [0, -1, 1])
def test_recovered_write_preserves_receive_order(service, monkeypatch, clock_step):
    timestamp = time.time()
    def incoming(text):
        nonlocal timestamp
        service.receive(dict(id=str(uuid4()), text=text, sender='fixture-peer',
                             context=service.context(), received=timestamp))
        timestamp += clock_step

    original = service.store.add
    incoming('저장 전')
    monkeypatch.setattr(service.store, 'add', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('disk full')))
    incoming('미저장 첫째')
    incoming('미저장 둘째')
    monkeypatch.setattr(service.store, 'add', original)
    incoming('저장 복구')
    monkeypatch.setattr(service.store, 'add', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('disk full')))
    incoming('미저장 셋째')
    monkeypatch.setattr(service.store, 'add', original)
    incoming('저장 마지막')
    rows = service.view()['messages']
    assert [r['body'] for r in rows] == [
        '저장 전', '미저장 첫째', '미저장 둘째', '저장 복구', '미저장 셋째', '저장 마지막']
    assert [r.get('unsaved', False) for r in rows] == [False, True, True, False, True, False]
    assert [r['body'] for r in service.view(query='저장')['messages']] == [r['body'] for r in rows]
    assert service.storage_error  # User refresh still checks recovery before sending.


def test_unsaved_order_survives_filtered_anchor_and_keeps_paging(service, monkeypatch):
    for i in range(105):
        received(service, f'이전 기록 {i}')
    original = service.store.add
    monkeypatch.setattr(service.store, 'add', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('disk full')))
    received(service, '검색 미저장')
    monkeypatch.setattr(service.store, 'add', original)
    received(service, '검색에 포함되지 않는 기준', sender='fixture-self')
    received(service, '검색 복구')
    assert [r['body'] for r in service.view(query='검색 ')['messages']] == ['검색 미저장', '검색 복구']
    page = service.view()
    assert page['has_more'] and len(page['messages']) == 101
    oldest_seq = next(r['seq'] for r in page['messages'] if 'seq' in r)
    older = service.view(before=oldest_seq)['messages']
    assert len(older) == 7 and all(not r.get('unsaved') and r['seq'] < oldest_seq for r in older)
    service.blocked['fixture-peer'] = '합성 차단 대상'
    assert [r['body'] for r in service.view()['messages']] == ['검색에 포함되지 않는 기준']


def test_storage_recovery_recreates_session_that_failed_to_save(store, monkeypatch):
    service = ChatService(store)
    original = store.session
    monkeypatch.setattr(store, 'session', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('disk full')))
    service.update(state())
    assert service.storage_error
    monkeypatch.setattr(store, 'session', original)
    service.recover_storage()
    command = service.prepare(service.context(), '복구 뒤 송신 준비')
    assert service.view()['messages'][0]['id'] == command['id']
    assert not service.storage_error


def test_deleting_other_room_keeps_current_pending_echo(service):
    first = service.context()
    service.update(state(lobby='fixture-room-b', generation='fixture-segment-b'))
    command = service.prepare(service.context(), '전송 중인 현재 방')
    service.forget(first['account'], first['lobby'])
    received(service, '전송 중인 현재 방', 'fixture-self')
    service.result(command['id'], 'accepted')
    rows = service.view()['messages']
    assert len(rows) == 1 and rows[0]['echo'] == 1


def test_retention_deletes_and_search_treats_sql_as_literal(service):
    received(service,"100% _ ' OR 1=1")
    assert len(service.view(query="% _")["messages"])==1
    assert not service.view(query="' OR 2=2")["messages"]
    service.store.db.execute("UPDATE messages SET received=?",(time.time()-RETENTION_SECONDS-1,))
    service.store.db.commit(); service.store.prune()
    assert service.store.db.execute("SELECT count(*) FROM messages").fetchone()[0]==0
    assert service.store.db.execute("SELECT count(*) FROM receipts").fetchone()[0]==0


def test_delete_is_account_and_room_scoped(service):
    received(service)
    service.update(state(lobby="fixture-room-b",generation="fixture-segment-b"));received(service)
    service.store.delete("fixture-self","fixture-room-a")
    assert len(service.view()["messages"])==1
    service.store.delete("fixture-self")
    assert not service.view()["messages"]


def test_keyset_paging_and_repeated_text(service):
    for _ in range(230): received(service,"한글 검색")
    page=service.view()["messages"]
    assert len(page)==100
    older=service.view(before=page[0]["seq"])["messages"]
    assert len(older)==100 and older[-1]["seq"] < page[0]["seq"]


def test_accepted_status_survives_normal_disconnect(service):
    command=service.prepare(service.context(),"접수된 발언");service.result(command["id"],"accepted")
    service.update(state(generation="next"))
    assert service.view()["messages"][0]["status"]=="accepted"


class FakeGame:
    pid=1;created=1
    def alive(self):return True


class FakeMemory:
    room="fixture-room-a"
    def lobby(self):return self.room
    def hidden(self):return {"fixture-peer":False}


class FakeSteam:
    def __init__(self):self.sent=[]
    def account(self):return "fixture-self"
    def reported_game(self, account):return 3419430, "fixture-room-a"
    def members(self,lobby):return {"fixture-self","fixture-peer"}
    def profile(self,lobby,uid):return {"name":"테스트","skin":None,"hat":None}
    def definition(self,*args):return None
    def room_name(self,lobby):return "테스트 로비"
    def send(self,lobby,text):self.sent.append((lobby,text));return True


def test_native_preflight_rechecks_game_before_send():
    memory,steam=FakeMemory(),FakeSteam();steam.sent=[]
    live=LiveConnection(FakeGame(),memory,steam)
    snap,_,_=live.snapshot(); context={k:snap[k] for k in ("account","lobby","generation")}
    memory.room="fixture-room-b"
    assert live.send(dict(context=context,text="보내지 않음",queued=time.monotonic()))=="failed"
    assert not steam.sent


def test_read_only_mode_cannot_send():
    live=LiveConnection(FakeGame(),FakeMemory(),FakeSteam(),read_only=True)
    assert live.send({})=="failed"


def test_game_update_blocks_send_before_any_native_transmission():
    class Verification:
        changed = False
        def check(self):
            if self.changed:
                raise RuntimeError('game_files_changed')
    verification = Verification()
    steam = FakeSteam()
    live = LiveConnection(FakeGame(), FakeMemory(), steam, compatibility=verification)
    state, _, _ = live.snapshot()
    context = {key: state[key] for key in ('account', 'lobby', 'generation')}
    verification.changed = True
    with pytest.raises(RuntimeError, match='game_files_changed'):
        live.send(dict(context=context, text='synthetic message', queued=time.monotonic()))
    assert not steam.sent


def test_process_restart_identity_changes_generation():
    game=FakeGame();live=LiveConnection(game,FakeMemory(),FakeSteam())
    first,_,_=live.snapshot();game.created=2
    second,_,changed=live.snapshot()
    assert changed and first["generation"]!=second["generation"]


def test_membership_alone_does_not_confirm_current_game():
    steam=FakeSteam()
    memory=FakeMemory()
    memory.room="0"
    live=LiveConnection(FakeGame(),memory,steam)
    snapshot,_,_=live.snapshot()
    assert not snapshot["send_enabled"] and snapshot["state"] == "no_lobby"


@pytest.mark.parametrize('reported', [(999, 'fixture-other-game-room'), (999, '0'),
                                      (0, '0'), (3419430, 'fixture-stale-room')])
def test_bongo_lobby_and_send_do_not_depend_on_friends_game_presence(reported):
    steam = FakeSteam()
    steam.reported_game = lambda account: reported
    queried = []
    def members(lobby):
        queried.append(lobby)
        return {'fixture-self', 'fixture-peer'}
    steam.members = members
    live = LiveConnection(FakeGame(), FakeMemory(), steam)
    snapshot, _, _ = live.snapshot()
    assert snapshot['lobby'] == 'fixture-room-a' and snapshot['lobby_verified']
    assert snapshot['lobby_verified'] and snapshot['send_enabled']
    context = {key: snapshot[key] for key in ('account', 'lobby', 'generation')}
    assert live.send(dict(context=context, text='합성 전송', queued=time.monotonic())) == 'accepted'
    assert steam.sent == [('fixture-room-a', '합성 전송')]
    assert set(queried) == {'fixture-room-a'}


def test_other_game_presence_changes_preserve_verified_context_and_draft(service):
    steam = FakeSteam()
    live = LiveConnection(FakeGame(), FakeMemory(), steam)
    first, _, _ = live.snapshot()
    service.update(first)
    context, session = service.context(), service.session
    service.store.draft(context['account'], context['lobby'], '작성 중인 초안')
    for reported in [(999, 'fixture-other-game-room'), (0, '0'), (3419430, 'fixture-room-a')]:
        steam.reported_game = lambda account: reported
        current, _, changed = live.snapshot()
        service.update(current)
        assert not changed and service.context() == context and service.session == session
        assert service.can_send() and service.view()['draft'] == '작성 중인 초안'


def test_unreadable_game_lobby_never_falls_back_to_friends_presence():
    from bongo_chat.memory import MemoryUnavailable
    memory, steam = FakeMemory(), FakeSteam()
    live = LiveConnection(FakeGame(), memory, steam)
    snapshot, _, _ = live.snapshot()
    context = {key: snapshot[key] for key in ('account', 'lobby', 'generation')}
    def fail():
        raise MemoryUnavailable('stale_domain')
    memory.lobby = fail
    with pytest.raises(MemoryUnavailable, match='stale_domain'):
        live.snapshot()
    with pytest.raises(MemoryUnavailable, match='stale_domain'):
        live.send(dict(context=context, text='차단할 전송', queued=time.monotonic()))
    assert not steam.sent


def test_lost_bongo_membership_blocks_send_even_with_other_game_running():
    steam = FakeSteam()
    steam.reported_game = lambda account: (999, 'fixture-other-game-room')
    live = LiveConnection(FakeGame(), FakeMemory(), steam)
    snapshot, _, _ = live.snapshot()
    assert snapshot['lobby_verified']
    context = {key: snapshot[key] for key in ('account', 'lobby', 'generation')}
    steam.members = lambda lobby: {'fixture-peer'}
    assert live.send(dict(context=context, text='차단할 전송', queued=time.monotonic())) == 'failed'
    current, _, changed = live.snapshot()
    assert changed and not current['connected'] and not current['send_enabled']
    assert not steam.sent


@pytest.mark.parametrize('change', ['lobby', 'account', 'process'])
def test_destination_changes_during_membership_read_are_rejected(change):
    game, memory, steam = FakeGame(), FakeMemory(), FakeSteam()
    live = LiveConnection(game, memory, steam)
    snapshot, _, _ = live.snapshot()
    context = {key: snapshot[key] for key in ('account', 'lobby', 'generation')}
    def members(lobby):
        if change == 'lobby':
            memory.room = 'fixture-room-b'
        elif change == 'account':
            steam.account = lambda: 'fixture-other-account'
        else:
            game.alive = lambda: False
        return {'fixture-self', 'fixture-peer'}
    steam.members = members
    with pytest.raises(RuntimeError, match='connection_changed'):
        live.send(dict(context=context, text='차단할 전송', queued=time.monotonic()))
    assert not steam.sent


def test_lobby_move_during_profile_read_does_not_publish_stale_state():
    memory, steam = FakeMemory(), FakeSteam()
    live = LiveConnection(FakeGame(), memory, steam)
    original = steam.profile
    def profile(lobby, uid):
        memory.room = 'fixture-room-b'
        return original(lobby, uid)
    steam.profile = profile
    with pytest.raises(RuntimeError, match='connection_changed'):
        live.snapshot()
    assert not live.state['send_enabled']


def test_discovery_pending_exposes_room_but_cannot_send_or_accept_chat(store):
    steam = FakeSteam()
    steam.sent = []
    live = LiveConnection(FakeGame(), None, steam)
    snapshot, _, _ = live.snapshot()
    assert snapshot['connected'] and snapshot['lobby'] == 'fixture-room-a'
    assert snapshot['state'] == 'syncing' and not snapshot['lobby_verified']
    assert not snapshot['send_enabled'] and not snapshot['members']
    service = ChatService(store)
    service.update(snapshot)
    session, context = service.session, service.context()
    store.draft(context['account'], context['lobby'], '먼저 작성한 초안')
    received(service, '확인 전 상대 메시지')
    received(service, '확인 전 내 메시지', 'fixture-self')
    assert store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    assert service.view()['rooms'] and service.view()['draft'] == '먼저 작성한 초안'
    assert not service.can_send()
    assert live.send(dict(context=context, text='전송 금지', queued=time.monotonic())) == 'failed'
    live.memory = FakeMemory()
    snapshot, _, changed = live.snapshot()
    service.update(snapshot)
    assert not changed and service.context() == context and service.session == session
    assert service.can_send() and service.view()['draft'] == '먼저 작성한 초안'
    assert not steam.sent


def test_game_hide_read_is_never_needed_for_chat(service):
    from bongo_chat.memory import MemoryUnavailable
    memory, steam = FakeMemory(), FakeSteam()
    steam.sent = []
    def fail():
        raise MemoryUnavailable('cache_changed_during_read')
    memory.hidden = fail
    live = LiveConnection(FakeGame(), memory, steam)
    snapshot, _, _ = live.snapshot()
    assert snapshot['lobby_verified'] and snapshot['send_enabled']
    assert snapshot['members'] and snapshot['notice'] == ''
    service.update(snapshot)
    received(service, '미확인 상대 메시지')
    assert len(service.view()['messages']) == 1
    command = service.prepare(service.context(), '내 메시지')
    command['queued'] = time.monotonic()
    assert live.send(command) == 'accepted'
    assert steam.sent == [('fixture-room-a', '내 메시지')]
    received(service, '내 메시지', 'fixture-self')
    assert len(service.view()['messages']) == 2 and service.view()['messages'][-1]['echo'] == 1


def test_game_hidden_and_unknown_members_are_received(service):
    memory, steam = FakeMemory(), FakeSteam()
    memory.hidden = lambda: {'fixture-peer': False, 'fixture-hidden': True}
    steam.members = lambda lobby: {'fixture-self', 'fixture-peer', 'fixture-hidden', 'fixture-unknown'}
    live = LiveConnection(FakeGame(), memory, steam)
    snapshot, _, _ = live.snapshot()
    assert snapshot['lobby_verified'] and snapshot['send_enabled']
    service.update(snapshot)
    received(service, '보이는 발언')
    received(service, '감춘 발언', 'fixture-hidden')
    received(service, '미확인 발언', 'fixture-unknown')
    assert [row['body'] for row in service.view()['messages']] == ['보이는 발언', '감춘 발언', '미확인 발언']
    assert service.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 3
    assert set(service.view()['profiles']) == steam.members('fixture-room-a')
    assert service.can_send()
    service.update(state(privacy_ready=False, hidden_ok=False))
    assert len(service.view()['messages']) == 3


@pytest.mark.parametrize('reported', [(0, '0'), (3419430, '0'), (999, 'fixture-room-a')])
def test_early_steam_connection_without_game_lobby_stays_unavailable(reported):
    steam = FakeSteam()
    steam.reported_game = lambda account: reported
    live = LiveConnection(FakeGame(), None, steam)
    snapshot, _, _ = live.snapshot()
    assert snapshot['state'] == 'syncing' and snapshot['notice'] == 'searching_lobby'
    assert not snapshot['connected'] and not snapshot['lobby_verified']
    assert not snapshot['lobby'] and not snapshot['send_enabled']


def test_lobby_move_during_discovery_invalidates_provisional_context(service):
    steam = FakeSteam()
    live = LiveConnection(FakeGame(), None, steam)
    first, _, _ = live.snapshot()
    service.update(first)
    old = service.context()
    # Presence may remain stale while Bongo Cat changes its actual lobby.
    memory = FakeMemory()
    memory.room = 'fixture-room-b'
    live.memory = memory
    current, _, changed = live.snapshot()
    service.update(current)
    assert changed and service.context()['generation'] != old['generation']
    assert live.send(dict(context=old, text='이전 로비 초안', queued=time.monotonic())) == 'failed'
    received(service, '늦은 이전 로비 메시지', context=old)
    assert not service.view()['messages']
