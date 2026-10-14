"""Separate native process. Its IPC has no network listener or auto-send source."""
import queue
import time
from uuid import uuid4

from .environment import UnsupportedGameBuild, running_game, verify_compatibility
from .memory import MemoryDiscovery, MemoryUnavailable
from .steam import APP_ID, Steam


def unavailable(notice):
    return {"type": "state", "state": "unavailable", "notice": notice, "account": "", "lobby": "",
            "generation": "", "connected": False, "lobby_verified": False,
            "privacy_ready": False, "hidden_ok": False, "hidden": {}, "profiles": {}, "send_enabled": False}


class LiveConnection:
    def __init__(self, game, memory, steam, read_only=False, avatars=None, compatibility=None):
        self.game, self.memory, self.steam = game, memory, steam
        self.read_only, self.avatars = read_only, avatars
        self.compatibility = compatibility
        self.identity = None
        self.generation = ""
        self.state = unavailable("checking")
        self.profiles = {}
        self.profile_time = 0
        self.last_send = 0
        self.discovery_failed = False

    def destination(self):
        """Verify the destination independently of hidden-list availability."""
        if self.compatibility:
            self.compatibility.check()
        if not self.game.alive():
            raise RuntimeError("process_changed")
        account = self.steam.account()
        reported = self.steam.reported_game(account)
        app, lobby = reported
        members = self.steam.members(lobby) if app == APP_ID and lobby != "0" else set()
        source = self.memory.lobby() if self.memory else None
        if (self.steam.account() != account or self.steam.reported_game(account) != reported
                or self.memory and self.memory.lobby() != source):
            raise RuntimeError("connection_changed")
        valid = lobby != "0" and account in members and app == APP_ID and (source is None or source == lobby)
        return account, lobby, members, valid, valid and source is not None

    def snapshot(self):
        account, lobby, members, valid, verified = self.destination()
        identity = (self.game.pid, self.game.created, account, lobby, valid)
        changed = identity != self.identity
        if changed:
            self.identity, self.generation = identity, str(uuid4())
            self.profiles = {}
            self.profile_time = 0
        hidden, privacy_ready = {}, False
        if verified:
            try:
                hidden = self.memory.hidden()
                privacy_ready = True
            except (MemoryUnavailable, UnicodeError):
                pass  # Keep the verified lobby and retry privacy on the next tick.
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
        if (self.steam.account() != account or valid and self.steam.reported_game(account) != (APP_ID, lobby)
                or verified and self.memory.lobby() != lobby):
            raise RuntimeError("connection_changed")
        if verified:
            try:
                hidden = self.memory.hidden()
                privacy_ready = True
            except (MemoryUnavailable, UnicodeError):
                hidden, privacy_ready = {}, False
        complete = privacy_ready and (members-{account}) <= hidden.keys()
        if not valid:
            notice = "no_lobby"
        elif not verified:
            notice = "discovery_failed" if self.discovery_failed else "discovering"
        elif not privacy_ready:
            notice = "hidden_unavailable"
        elif not complete:
            notice = "hidden_syncing"
        else:
            notice = "read_only" if self.read_only else ""
        state = {"type": "state", "account": account, "lobby": lobby if valid else "",
                 "generation": self.generation, "connected": valid, "lobby_verified": verified,
                 "privacy_ready": privacy_ready, "hidden_ok": complete, "hidden": hidden,
                 "profiles": self.profiles, "send_enabled": verified and not self.read_only,
                 "avatar_stage": getattr(self.avatars, "stage", "disabled"),
                 "avatar_error": getattr(self.avatars, "error", ""),
                 "state": "ready" if complete else ("syncing" if valid else "no_lobby"),
                 "name": self.steam.room_name(lobby) if valid else "",
                 "notice": notice}
        self.state = state
        return state, members, changed

    def send(self, command):
        if self.read_only or time.monotonic()-self.last_send < 1.0:
            return "failed"
        if time.monotonic()-command.get("queued", 0) > 2.0:
            return "failed"
        account, lobby, members, valid, verified = self.destination()
        identity = (self.game.pid, self.game.created, account, lobby, valid)
        current = {"account": account, "lobby": lobby, "generation": self.generation}
        if (not verified or not self.state.get("send_enabled") or identity != self.identity
                or command.get("context") != current):
            return "failed"
        # Bind the original destination. A game move after this check is not atomic.
        if self.memory.lobby() != current["lobby"] or self.steam.account() != current["account"] or not self.game.alive():
            return "failed"
        if self.steam.reported_game(current["account"]) != (APP_ID, current["lobby"]):
            return "failed"
        if self.compatibility:
            self.compatibility.check()
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
        discovery = steam = avatars = None
        try:
            emit(unavailable("checking"))
            game = running_game()
            compatibility = verify_compatibility(game.root, stop)
            steam = Steam(game.root)
            steam.start()
            compatibility.check()
            live = LiveConnection(game, None, steam, read_only, compatibility=compatibility)
            last_state, last_emit, receive_context = None, 0, None
            receive_senders, retry_discovery_at = set(), 0
            while not stop.is_set():
                if discovery and discovery.done.is_set():
                    live.memory = discovery.memory
                    if discovery.failed:
                        live.discovery_failed = True
                        discovery.close()
                        discovery = None
                        retry_discovery_at = time.monotonic() + 15
                state, members, changed = live.snapshot()
                context = {k: state[k] for k in ("account", "lobby", "generation")}
                if state != last_state or time.monotonic()-last_emit >= 0.5:
                    emit(state)
                    last_state, last_emit = state, time.monotonic()
                # Drain callbacks after transitions without attributing old payloads to a new segment.
                allowed = {state["account"]} if state["lobby_verified"] else set()
                if state["privacy_ready"]:
                    allowed.update(uid for uid, hidden in state["hidden"].items() if hidden is False)
                # Drop unknown/hidden senders before copying a body. Also drain
                # the first batch after verification so pending-period callbacks
                # cannot be relabelled as messages received after synchronization.
                for message in steam.pump(context, members & allowed & receive_senders,
                                          accept=receive_context == context):
                    emit(message)
                receive_context, receive_senders = context, allowed
                if state["connected"] and not discovery and time.monotonic() >= retry_discovery_at:
                    live.discovery_failed = False
                    discovery = MemoryDiscovery(game, stop)
                # Asset decoding competes with discovery for the Python GIL.
                # Publish verified chat readiness before starting that work.
                if state["lobby_verified"] and render_avatars and not avatars:
                    from .avatars import Avatars
                    avatars = Avatars(game.root)
                    live.avatars = avatars
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
                state = unavailable(code)
                if isinstance(exc, UnsupportedGameBuild):
                    state.update(game_build=exc.build, build_fingerprint=exc.fingerprint)
                emit(state)
        finally:
            if avatars:
                avatars.close()
            if steam:
                steam.close()  # No LeaveLobby, joins or lobby setting mutations.
            if discovery:
                discovery.close()
        stop.wait(3)
