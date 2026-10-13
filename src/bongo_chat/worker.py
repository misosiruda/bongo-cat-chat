"""Separate native process. Its IPC has no network listener or auto-send source."""
import queue
import time
from uuid import uuid4

from .environment import running_game, verify_build
from .memory import GameMemory
from .steam import APP_ID, Steam


def unavailable(notice):
    return {"type": "state", "state": "unavailable", "notice": notice, "account": "", "lobby": "",
            "generation": "", "hidden_ok": False, "hidden": {}, "profiles": {}, "send_enabled": False}


class LiveConnection:
    def __init__(self, game, memory, steam, read_only=False, avatars=None):
        self.game, self.memory, self.steam = game, memory, steam
        self.read_only, self.avatars = read_only, avatars
        self.identity = None
        self.generation = ""
        self.state = unavailable("checking")
        self.profiles = {}
        self.profile_time = 0
        self.last_send = 0

    def snapshot(self):
        if not self.game.alive():
            raise RuntimeError("process_changed")
        account = self.steam.account()
        lobby = self.memory.lobby()
        reported_app, reported_lobby = self.steam.reported_game(account)
        members = self.steam.members(lobby) if lobby != "0" else set()
        hidden = self.memory.hidden()
        # Double-read the game source around metadata/Steam calls.
        if self.memory.lobby() != lobby or self.steam.account() != account:
            raise RuntimeError("connection_changed")
        valid = lobby != "0" and account in members and reported_app == APP_ID and reported_lobby == lobby
        identity = (self.game.pid, self.game.created, account, lobby, valid)
        changed = identity != self.identity
        if changed:
            self.identity, self.generation = identity, str(uuid4())
            self.profiles = {}
            self.profile_time = 0
        complete = valid and (members-{account}) <= hidden.keys()
        if valid and time.monotonic()-self.profile_time >= 1:
            profiles = {}
            for uid in members:
                if uid != account and hidden.get(uid) is not False:
                    continue
                row = self.steam.profile(lobby, uid)
                skin = self.steam.definition(row["skin"], "name")
                hat = self.steam.definition(row["hat"], "name")
                if self.avatars and skin and (hat or row["hat"] == -1):
                    row["avatar"] = self.avatars.get(skin.replace(" ", ""), hat.replace(" ", "") if hat else None)
                profiles[uid] = row
            self.profiles, self.profile_time = profiles, time.monotonic()
        if self.memory.lobby() != lobby or self.steam.account() != account:
            raise RuntimeError("connection_changed")
        hidden = self.memory.hidden()
        complete = valid and (members-{account}) <= hidden.keys()
        state = {"type": "state", "account": account, "lobby": lobby if valid else "",
                 "generation": self.generation, "hidden_ok": complete, "hidden": hidden,
                 "profiles": self.profiles, "send_enabled": complete and not self.read_only,
                 "avatar_stage": getattr(self.avatars, "stage", "disabled"),
                 "avatar_error": getattr(self.avatars, "error", ""),
                 "state": "ready" if complete else ("privacy_unavailable" if valid else "no_lobby"),
                 "name": self.steam.room_name(lobby) if valid else "",
                 "notice": "read_only" if complete and self.read_only else ("" if complete else "hidden_unavailable" if valid else "no_lobby")}
        self.state = state
        return state, members, changed

    def send(self, command):
        if self.read_only or time.monotonic()-self.last_send < 1.0:
            return "failed"
        if time.monotonic()-command.get("queued", 0) > 2.0:
            return "failed"
        state, members, changed = self.snapshot()
        current = {k: state[k] for k in ("account", "lobby", "generation")}
        if changed or command.get("context") != current or not state["send_enabled"]:
            return "failed"
        # Bind the original destination. A game move after this check is not atomic.
        if self.memory.lobby() != current["lobby"] or self.steam.account() != current["account"] or not self.game.alive():
            return "failed"
        if self.steam.reported_game(current["account"]) != (APP_ID, current["lobby"]):
            return "failed"
        self.last_send = time.monotonic()
        try:
            return "accepted" if self.steam.send(current["lobby"], command["text"]) else "failed"
        except Exception:
            return "unknown"  # Never retry this command.


def run_worker(commands, events, stop, read_only=False, render_avatars=True):
    def emit(event):
        try:
            events.put(event, timeout=0.2)
        except queue.Full:
            # Stop rather than silently drop history or preserve a stale ready state.
            stop.set()
            raise RuntimeError("event_queue_overflow")

    while not stop.is_set():
        memory = steam = avatars = None
        try:
            emit(unavailable("checking"))
            game = running_game()
            verify_build(game.root)
            memory = GameMemory(game, stop)
            emit(unavailable("discovering"))
            memory.discover()
            steam = Steam(game.root)
            steam.start()
            if render_avatars:
                from .avatars import Avatars
                avatars = Avatars(game.root)
            live = LiveConnection(game, memory, steam, read_only, avatars)
            last_state, last_emit, receive_context = None, 0, None
            while not stop.is_set():
                state, members, changed = live.snapshot()
                context = {k: state[k] for k in ("account", "lobby", "generation")}
                if state != last_state or time.monotonic()-last_emit >= 0.5:
                    emit(state)
                    last_state, last_emit = state, time.monotonic()
                # Drain callbacks after transitions without attributing old payloads to a new segment.
                for message in steam.pump(context, members, accept=receive_context == context and state["hidden_ok"]):
                    if message["sender"] == state["account"] or state["hidden"].get(message["sender"]) is False:
                        emit(message)
                receive_context = context
                for _ in range(32):
                    try:
                        command = commands.get_nowait()
                    except queue.Empty:
                        break
                    if command.get("type") == "send":
                        status = live.send(command)
                        emit({"type": "result", "id": command["id"], "status": status})
                    elif command.get("type") == "refresh":
                        live.profile_time = 0
                stop.wait(0.15)
        except Exception as exc:
            if not stop.is_set():
                # Only fixed diagnostic codes; never addresses, account IDs or text.
                code = str(exc)
                if not code.isascii() or not code.replace("_", "").isalnum() or len(code) > 80:
                    code = "connection_unavailable"
                emit(unavailable(code))
        finally:
            if avatars:
                avatars.close()
            if steam:
                steam.close()  # No LeaveLobby, joins or lobby setting mutations.
            if memory:
                memory.close()
        stop.wait(3)
