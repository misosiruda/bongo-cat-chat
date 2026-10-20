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

    def _lobby_candidate(self, account):
        if self.memory is not None:
            # Bongo Cat's verified process is authoritative, including no lobby
            # or a failed read. Friends presence may describe another game.
            return self.memory.lobby()
        app, lobby = self.steam.reported_game(account)
        # A provisional hint for early room/draft display, never send authority.
        return lobby if app == APP_ID else "0"

    def destination(self):
        """Verify the destination independently of hidden-list availability."""
        if self.compatibility:
            self.compatibility.check()
        if not self.game.alive():
            raise RuntimeError("process_changed")
        account = self.steam.account()
        lobby = self._lobby_candidate(account)
        members = self.steam.members(lobby) if lobby != "0" else set()
        if (self.steam.account() != account or self._lobby_candidate(account) != lobby
                or not self.game.alive()):
            raise RuntimeError("connection_changed")
        valid = lobby != "0" and account in members
        return account, lobby, members, valid, valid and self.memory is not None

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
                # The game publishes -1 for an explicitly unequipped slot.
                # Its default body/paw sprites are CatLeft/CatRight. Unknown
                # slots and failed item lookups must not become default outfits.
                skin = "Cat" if row["skin"] == -1 else self.steam.definition(row["skin"], "name")
                hat = None if row["hat"] == -1 else self.steam.definition(row["hat"], "name")
                if self.avatars and skin and (hat or row["hat"] == -1):
                    row["avatar"] = self.avatars.get(skin.replace(" ", ""), hat.replace(" ", "") if hat else None)
                profiles[uid] = row
            self.profiles, self.profile_time = profiles, time.monotonic()
        if verified:
            try:
                hidden = self.memory.hidden()
                privacy_ready = True
            except (MemoryUnavailable, UnicodeError):
                hidden, privacy_ready = {}, False
        if (self.steam.account() != account or self._lobby_candidate(account) != lobby
                or not self.game.alive()):
            raise RuntimeError("connection_changed")
        complete = privacy_ready and (members-{account}) <= hidden.keys()
        discovering = self.memory is None
        if discovering:
            notice = "discovery_failed" if self.discovery_failed else ("discovering" if valid else "searching_lobby")
        elif not valid:
            notice = "no_lobby"
        elif not privacy_ready:
            notice = "hidden_unavailable"
        elif not complete:
            notice = "hidden_syncing"
        else:
            notice = "read_only" if self.read_only else ""
        state = {"type": "state", "account": account, "lobby": lobby if valid else "",
                 "generation": self.generation, "connected": valid, "lobby_verified": verified,
                 "privacy_ready": privacy_ready, "hidden_ok": complete, "hidden": hidden,
                 # Profiles refresh once a second, membership/privacy every tick.
                 # Never offer a departed or newly hidden peer from that cache.
                 "profiles": {uid: row for uid, row in self.profiles.items()
                              if uid in members and (uid == account or hidden.get(uid) is False)},
                 "send_enabled": verified and not self.read_only,
                 "avatar_stage": getattr(self.avatars, "stage", "disabled"),
                 "avatar_error": getattr(self.avatars, "error", ""),
                 "state": "ready" if complete else ("syncing" if valid or discovering else "no_lobby"),
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
                # Discovery must run even when friends presence reports another
                # Steam game or no game. It supplies the actual Bongo Cat lobby.
                if not discovery and time.monotonic() >= retry_discovery_at:
                    live.discovery_failed = False
                    discovery = MemoryDiscovery(game, stop)
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
