"""Allow-listed x64 Steam ABI. Only explicit send() can transmit text."""
import ctypes as C
from contextlib import contextmanager
import os
import time
from uuid import uuid4

from .protocol import MAX_PACKET, InvalidMessage, decode_event, encode

APP_ID = 3419430


@contextmanager
def quiet_native_startup():
    """Steam's startup diagnostics can contain the account ID. Discard them."""
    saved = []
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        for fd in (1, 2):
            try:
                copy = os.dup(fd)
            except OSError:
                continue  # Windowed builds may not have console file descriptors.
            saved.append((fd, copy))
            os.dup2(null, fd)
        yield
    finally:
        for fd, copy in saved:
            os.dup2(copy, fd)
            os.close(copy)
        os.close(null)


class Callback(C.Structure):
    _fields_ = [("user", C.c_int32), ("kind", C.c_int32), ("data", C.c_void_p), ("size", C.c_int32)]


class ChatHeader(C.Structure):
    _fields_ = [("lobby", C.c_uint64), ("sender", C.c_uint64), ("entry_type", C.c_uint8), ("chat_id", C.c_uint32)]


class GameInfo(C.Structure):
    _fields_ = [("game", C.c_uint64), ("ip", C.c_uint32), ("port", C.c_uint16), ("query_port", C.c_uint16), ("lobby", C.c_uint64)]


class Steam:
    def __init__(self, root):
        if C.sizeof(C.c_void_p) != 8 or C.sizeof(ChatHeader) != 24 or C.sizeof(Callback) != 24:
            raise RuntimeError("unsupported_abi")
        self.initialized = False
        directory = root / "BongoCat_Data/Plugins/x86_64"
        self.directory = os.add_dll_directory(str(directory))
        os.environ["SteamAppId"] = os.environ["SteamGameId"] = str(APP_ID)
        self.dll = C.CDLL(str(directory / "steam_api64.dll"), winmode=0x1100)
        self.rejected = 0

    def bind(self, name, result, *arguments):
        fn = getattr(self.dll, "SteamAPI_"+name)
        fn.restype, fn.argtypes = result, list(arguments)
        return fn

    def start(self):
        with quiet_native_startup():
            self._start()

    def _start(self):
        error = C.create_string_buffer(1024)
        if self.bind("InitFlat", C.c_int, C.c_void_p)(error) != 0:
            raise RuntimeError("steam_initialization_failed")
        self.initialized = True
        # Exact versions observed and pinned by DLL hash, no highest-version guessing.
        for key, name in {"user": "SteamUser_v023", "friends": "SteamFriends_v018", "utils": "SteamUtils_v010", "matchmaking": "SteamMatchmaking_v009", "inventory": "SteamInventory_v003"}.items():
            ptr = self.bind(name, C.c_void_p)()
            if not ptr:
                raise RuntimeError("unsupported_interface")
            setattr(self, key, ptr)
        self.bind("ManualDispatch_Init", None)()
        self.pipe = self.bind("GetHSteamPipe", C.c_int32)()
        self.run_frame = self.bind("ManualDispatch_RunFrame", None, C.c_int32)
        self.next_callback = self.bind("ManualDispatch_GetNextCallback", C.c_bool, C.c_int32, C.POINTER(Callback))
        self.free_callback = self.bind("ManualDispatch_FreeLastCallback", None, C.c_int32)
        self.uid = self.bind("ISteamUser_GetSteamID", C.c_uint64, C.c_void_p)
        self.logged_on = self.bind("ISteamUser_BLoggedOn", C.c_bool, C.c_void_p)
        self.app_id = self.bind("ISteamUtils_GetAppID", C.c_uint32, C.c_void_p)
        self.member_count = self.bind("ISteamMatchmaking_GetNumLobbyMembers", C.c_int, C.c_void_p, C.c_uint64)
        self.member_at = self.bind("ISteamMatchmaking_GetLobbyMemberByIndex", C.c_uint64, C.c_void_p, C.c_uint64, C.c_int)
        self.read_entry = self.bind("ISteamMatchmaking_GetLobbyChatEntry", C.c_int, C.c_void_p, C.c_uint64, C.c_int,
                                    C.POINTER(C.c_uint64), C.c_void_p, C.c_int, C.POINTER(C.c_int))
        self.send_entry = self.bind("ISteamMatchmaking_SendLobbyChatMsg", C.c_bool, C.c_void_p, C.c_uint64, C.c_void_p, C.c_int)
        self.bind("ISteamInventory_LoadItemDefinitions", C.c_bool, C.c_void_p)(self.inventory)

    def account(self):
        if self.app_id(self.utils) != APP_ID or not self.logged_on(self.user):
            raise RuntimeError("steam_unavailable")
        uid = str(self.uid(self.user))
        if len(uid) != 17:
            raise RuntimeError("account_unavailable")
        return uid

    def members(self, lobby):
        count = self.member_count(self.matchmaking, int(lobby))
        if not 0 <= count <= 1000:
            raise RuntimeError("invalid_member_count")
        return {str(self.member_at(self.matchmaking, int(lobby), i)) for i in range(count)}

    def reported_game(self, account):
        """Friends presence hint, not an inventory of all running Steam games."""
        info = GameInfo()
        ok = self.bind("ISteamFriends_GetFriendGamePlayed", C.c_bool, C.c_void_p, C.c_uint64, C.POINTER(GameInfo))(
            self.friends, int(account), C.byref(info))
        return (int(info.game), str(info.lobby)) if ok else (0, "0")

    def text(self, value):
        return (value or b"").decode("utf-8", "replace")[:256]

    def room_name(self, lobby):
        value = self.bind("ISteamMatchmaking_GetLobbyData", C.c_char_p, C.c_void_p, C.c_uint64, C.c_char_p)(
            self.matchmaking, int(lobby), b"LOBBY_NAME")
        return self.text(value)

    def profile(self, lobby, uid):
        nickname = self.bind("ISteamFriends_GetPlayerNickname", C.c_char_p, C.c_void_p, C.c_uint64)(self.friends, int(uid))
        persona = self.bind("ISteamFriends_GetFriendPersonaName", C.c_char_p, C.c_void_p, C.c_uint64)(self.friends, int(uid))
        row = {"name": self.text(nickname or persona)}
        for slot in ("hat", "skin"):
            value = self.bind("ISteamMatchmaking_GetLobbyMemberData", C.c_char_p, C.c_void_p, C.c_uint64, C.c_uint64, C.c_char_p)(
                self.matchmaking, int(lobby), int(uid), slot.encode())
            try:
                row[slot] = int(value)
            except (ValueError, TypeError):
                row[slot] = None
        return row

    def definition(self, item, prop):
        if not isinstance(item, int) or not 0 <= item <= 2**31-1:
            return None
        fn = self.bind("ISteamInventory_GetItemDefinitionProperty", C.c_bool, C.c_void_p, C.c_int32, C.c_char_p, C.c_void_p, C.POINTER(C.c_uint32))
        size = C.c_uint32()
        if not fn(self.inventory, item, prop.encode(), None, C.byref(size)) or not 0 < size.value <= 65536:
            return None
        buffer = C.create_string_buffer(size.value)
        if not fn(self.inventory, item, prop.encode(), buffer, C.byref(size)):
            return None
        return buffer.value.decode("utf-8", "strict")

    def pump(self, context, members, accept=True):
        self.run_frame(self.pipe)
        callback = Callback()
        result = []
        for _ in range(2048):
            if not self.next_callback(self.pipe, C.byref(callback)):
                break
            try:
                if not accept or callback.kind != 507 or callback.size != C.sizeof(ChatHeader) or not callback.data:
                    continue
                header = C.cast(callback.data, C.POINTER(ChatHeader)).contents
                if str(header.lobby) != context.get("lobby") or str(header.sender) not in members or header.entry_type != 1:
                    continue
                buffer, sender, entry_type = C.create_string_buffer(MAX_PACKET), C.c_uint64(), C.c_int()
                length = self.read_entry(self.matchmaking, header.lobby, header.chat_id, C.byref(sender), buffer, len(buffer), C.byref(entry_type))
                if not 0 < length <= MAX_PACKET or sender.value != header.sender or entry_type.value != 1:
                    self.rejected += 1
                    continue
                # No pointer/header/chat_id leaves this callback scope.
                raw = bytes(buffer.raw[:length])
                try:
                    event = decode_event(raw)
                except InvalidMessage:
                    self.rejected += 1
                    continue
                if event is not None:
                    result.append(dict(event, id=str(uuid4()), context=dict(context),
                                       sender=str(sender.value), received=time.time(), observed=time.monotonic()))
            finally:
                self.free_callback(self.pipe)
        return result

    def send(self, lobby, text):
        raw = encode(text)
        buffer = C.create_string_buffer(raw)
        return bool(self.send_entry(self.matchmaking, int(lobby), buffer, len(raw)))

    def close(self):
        if self.initialized:
            self.bind("Shutdown", None)()
            self.initialized = False
        self.directory.close()
