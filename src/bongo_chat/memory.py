"""Experimental reader behind a feature contract and a known Mono ABI.

Only OpenProcess(QUERY_INFORMATION | VM_READ), ReadProcessMemory and query APIs.
No saved addresses, remote calls, process writes, injection or file mutations.
"""
import ctypes as C
from ctypes import wintypes as W
from array import array
import re
import struct
import time


class Region(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("PartitionId", W.WORD),
                ("RegionSize", C.c_size_t), ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


class MemoryUnavailable(RuntimeError):
    pass


class Reader:
    def __init__(self, game, stop=None):
        self.game, self.stop = game, stop
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.k.ReadProcessMemory.restype = W.BOOL
        self.k.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(Region), C.c_size_t]
        self.k.VirtualQueryEx.restype = C.c_size_t
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.handle = self.k.OpenProcess(0x0400 | 0x0010, False, game.pid)
        if not self.handle:
            raise MemoryUnavailable("process_read_denied")

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        if not 0x10000 <= address < 0x7fffffffffff or not 0 < size <= 8*1024*1024:
            return b""
        buffer, count = C.create_string_buffer(size), C.c_size_t()
        self.k.ReadProcessMemory(self.handle, address, buffer, size, C.byref(count))
        return buffer.raw[:count.value]

    def exact(self, address, size):
        data = self.read(address, size)
        if len(data) != size:
            raise MemoryUnavailable("memory_read_failed")
        return data

    def pointer(self, address):
        data = self.read(address, 8)
        return struct.unpack("<Q", data)[0] if len(data) == 8 else 0

    def i32(self, address):
        data = self.read(address, 4)
        return struct.unpack("<i", data)[0] if len(data) == 4 else None

    def cstring(self, address):
        data = self.read(address, 160)
        if b"\0" not in data:
            return None
        try:
            return data.split(b"\0", 1)[0].decode("utf-8", "strict")
        except UnicodeError:
            return None

    def scan(self, patterns, private_only=True, pointer_aligned=False):
        if not patterns or len(patterns) > 500:
            raise MemoryUnavailable("unsupported_metadata_candidates")
        hits = {name: set() for name in patterns}
        by_pattern = {}
        for name, pattern in patterns.items():
            by_pattern.setdefault(pattern, []).append(name)
        pointers = None
        if pointer_aligned:
            if any(len(pattern) != 8 for pattern in by_pattern):
                raise MemoryUnavailable("unsupported_pointer_pattern")
            pointers = {int.from_bytes(pattern, "little"): keys for pattern, keys in by_pattern.items()}
        address, started, read_total = 0, time.monotonic(), 0
        overlap = max(map(len, patterns.values()))
        while address < 0x7fffffffffff:
            region = Region()
            if not self.k.VirtualQueryEx(self.handle, address, C.byref(region), C.sizeof(region)):
                break
            next_address = (region.BaseAddress or 0) + region.RegionSize
            if next_address <= address:
                break
            if region.State == 0x1000 and (not private_only or region.Type == 0x20000) and not region.Protect & (0x100 | 1):
                for offset in range(0, region.RegionSize, 4*1024*1024):
                    if (self.stop and self.stop.is_set()) or time.monotonic()-started > 120 or read_total > 4*1024**3:
                        raise MemoryUnavailable("discovery_cancelled_or_budget")
                    start = region.BaseAddress + offset
                    chunk = self.read(start, min(region.RegionSize-offset, 4*1024*1024+overlap))
                    read_total += len(chunk)
                    if pointers is not None:
                        # Mono class-name fields and vtables are 8-byte aligned.
                        # Read each aligned word once instead of rescanning the
                        # entire heap for every candidate string address.
                        skip = (-start) % 8
                        words = array('Q', chunk[skip:skip + (len(chunk)-skip)//8*8])
                        for index, value in enumerate(words):
                            keys = pointers.get(value)
                            if keys:
                                for key in keys:
                                    hits[key].add(start+skip+index*8)
                                    if len(hits[key]) > 4096:
                                        raise MemoryUnavailable("ambiguous_metadata")
                        continue
                    for pattern, keys in by_pattern.items():
                        if (self.stop and self.stop.is_set()) or time.monotonic()-started > 120:
                            raise MemoryUnavailable("discovery_cancelled_or_budget")
                        pos = chunk.find(pattern)
                        while pos >= 0:
                            for key in keys:
                                hits[key].add(start+pos)
                                if len(hits[key]) > 4096:
                                    raise MemoryUnavailable("ambiguous_metadata")
                            pos = chunk.find(pattern, pos+1)
            address = next_address
        if not self.game.alive():
            raise MemoryUnavailable("process_changed")
        return hits


def class_name(r, cls):
    return r.cstring(r.pointer(cls+0x48))


def namespace(r, cls):
    return r.cstring(r.pointer(cls+0x50))


def fields(r, cls):
    # The hash-pinned Mono's field-count helper (RVA 0xcf750) follows an
    # inflated generic class through +0xf0 / +0 before reading +0x100.
    # Never walk past the declared field table based on adjacent pointer bytes.
    definition = cls
    for _ in range(4):
        kind = r.read(definition+0x1b, 1)
        if kind in (b"\x01", b"\x02"):
            break
        if kind != b"\x03":
            raise MemoryUnavailable("unsupported_class_kind")
        definition = r.pointer(r.pointer(definition+0xf0))
    else:
        raise MemoryUnavailable("generic_metadata_cycle")
    count = r.i32(definition+0x100)
    if count is None or not 0 <= count <= 64:
        raise MemoryUnavailable("unsupported_field_count")
    table = r.pointer(cls+0x98)
    result = {}
    for index in range(count):
        entry = table + 32*index
        if r.pointer(entry+16) != cls:
            raise MemoryUnavailable("field_owner_changed")
        name, offset = r.cstring(r.pointer(entry+8)), r.i32(entry+24)
        if not name or offset is None or not 0 <= offset <= 65536 or name in result:
            raise MemoryUnavailable("invalid_field_metadata")
        result[name] = offset
    return result


class GameMemory:
    def __init__(self, game, stop=None):
        self.reader = Reader(game, stop)
        self.roots = {}
        self.diagnostics = {}

    def discover(self):
        r = self.reader
        specifications = {"cache": ("PlayerDataCache", "", "_playerDataCache"),
                          "lobby": ("LobbyData", "Heathen.SteamworksIntegration", "Current")}
        names = r.scan({key: (s[0]+"\0").encode() for key, s in specifications.items()}, private_only=False)
        references = r.scan({f"{key}:{addr}": struct.pack("<Q", addr) for key, values in names.items() for addr in values}, pointer_aligned=True)
        classes = {key: set() for key in specifications}
        for ref, addresses in references.items():
            key = ref.split(":")[0]
            name, ns, field = specifications[key]
            for address in addresses:
                cls = address-0x48
                if class_name(r, cls) == name and namespace(r, cls) == ns:
                    try:
                        meta = fields(r, cls)
                        if field in meta:
                            classes[key].add(cls)
                    except MemoryUnavailable:
                        continue
        if any(len(values) != 1 for values in classes.values()):
            raise MemoryUnavailable("metadata_not_unique")
        pointers = {key: next(iter(values)) for key, values in classes.items()}
        vtables = r.scan({key: struct.pack("<Q", cls) for key, cls in pointers.items()}, pointer_aligned=True)
        for key, cls in pointers.items():
            slots = r.i32(cls+0x5c)
            if slots is None or not 0 < slots < 128:
                raise MemoryUnavailable("unsupported_vtable")
            offset = fields(r, cls)[specifications[key][2]]
            candidates = set()
            diagnostic = {"references": len(vtables[key]), "slots": slots, "static_offset": offset,
                          "instance_size": r.i32(cls+0x1c), "id_offset": fields(r, cls).get("_id"),
                          "initialized_vtables": 0, "readable_statics": 0}
            self.diagnostics[key] = diagnostic
            for address in vtables[key]:
                flags = r.read(address+0x30, 1)
                if not flags or not flags[0] & 4:
                    continue
                diagnostic["initialized_vtables"] += 1
                statics = r.pointer(address+slots*8+0x48)
                if not statics or len(r.read(statics+offset, 8)) != 8:
                    continue
                diagnostic["readable_statics"] += 1
                # Installed mono_vtable_domain is `mov rax,[rcx+0x10]; ret`.
                # Resolve the lobby in the same managed domain as the actual cache.
                if key == "lobby" and r.pointer(address+0x10) != r.pointer(self.roots["cache"][1]+0x10):
                    continue
                if key == "cache" and class_name(r, r.pointer(r.pointer(r.pointer(statics+offset)))) != "Dictionary`2":
                    continue
                # LobbyData is an 8-byte value type with a single UInt64 instance field.
                if key == "lobby" and (fields(r, cls).get("_id") != 16 or r.i32(cls+0x1c) != 24):
                    continue
                candidates.add((address, statics+offset))
            diagnostic["candidates"] = len(candidates)
            if len(candidates) != 1:
                raise MemoryUnavailable("static_root_not_unique")
            self.roots[key] = (cls, *next(iter(candidates)))
        self.lobby()
        self.hidden()

    def root(self, key):
        r = self.reader
        if not r.game.alive():
            raise MemoryUnavailable("process_changed")
        cls, vtable, address = self.roots[key]
        slots = r.i32(cls+0x5c)
        if r.pointer(vtable) != cls or slots is None or not 0 < slots < 128:
            raise MemoryUnavailable("stale_root")
        expected = "PlayerDataCache" if key == "cache" else "LobbyData"
        if class_name(r, cls) != expected:
            raise MemoryUnavailable("stale_class")
        if key == "lobby" and r.pointer(vtable+0x10) != r.pointer(self.roots["cache"][1]+0x10):
            raise MemoryUnavailable("stale_domain")
        field = "_playerDataCache" if key == "cache" else "Current"
        if r.pointer(vtable+slots*8+0x48) + fields(r, cls)[field] != address:
            raise MemoryUnavailable("stale_statics")
        return address

    def lobby(self):
        return str(struct.unpack("<Q", self.reader.exact(self.root("lobby"), 8))[0])

    def hidden(self):
        r = self.reader
        for _ in range(3):
            root = self.root("cache")
            dictionary = r.pointer(root)
            cls = r.pointer(r.pointer(dictionary))
            if class_name(r, cls) != "Dictionary`2":
                raise MemoryUnavailable("dictionary_type")
            df = fields(r, cls)
            if not {"_count", "_entries", "_version"} <= df.keys():
                raise MemoryUnavailable("dictionary_fields")
            count, version, entries = r.i32(dictionary+df["_count"]), r.i32(dictionary+df["_version"]), r.pointer(dictionary+df["_entries"])
            if count is None or not 0 <= count <= 10000 or version is None:
                raise MemoryUnavailable("dictionary_count")
            if count == 0 and not entries:
                return {}  # Structurally confirmed empty cache; missing users stay unknown.
            ac = r.pointer(r.pointer(entries))
            ec = r.pointer(ac)
            ef = {name: offset-16 for name, offset in fields(r, ec).items()}
            size = r.i32(ec+0x1c)
            stride = size-16 if size is not None else 0
            capacity = r.pointer(entries+24)
            if class_name(r, ac) != "Entry[]" or class_name(r, ec) != "Entry" or not {"hashCode", "key", "value", "next"} <= ef.keys() or not 8 <= stride <= 128 or not count <= capacity <= 20000:
                raise MemoryUnavailable("entry_layout")
            if any(offset < 0 or offset+8 > stride for name, offset in ef.items() if name in ("key", "value")):
                raise MemoryUnavailable("entry_offsets")
            rows = {}
            for index in range(count):
                item = entries+32+stride*index
                hashcode = r.i32(item+ef["hashCode"])
                if hashcode is None:
                    raise MemoryUnavailable("entry_read")
                if hashcode < 0:
                    continue
                key, value = r.pointer(item+ef["key"]), r.pointer(item+ef["value"])
                if class_name(r, r.pointer(r.pointer(key))) != "String" or r.i32(key+16) != 17:
                    raise MemoryUnavailable("identity_type")
                uid = r.exact(key+20, 34).decode("utf-16-le", "strict")
                vc = r.pointer(r.pointer(value))
                if not re.fullmatch(r"[0-9]{17}", uid) or uid in rows or class_name(r, vc) != "PlayerData":
                    raise MemoryUnavailable("cache_identity")
                vf = fields(r, vc)
                if "IsHidden" not in vf:
                    raise MemoryUnavailable("hidden_field")
                hidden = r.exact(value+vf["IsHidden"], 1)
                if hidden not in (b"\x00", b"\x01"):
                    raise MemoryUnavailable("hidden_boolean")
                rows[uid] = bool(hidden[0])
            if (count, version, entries, dictionary) == (r.i32(dictionary+df["_count"]), r.i32(dictionary+df["_version"]), r.pointer(dictionary+df["_entries"]), r.pointer(root)):
                return rows
        raise MemoryUnavailable("cache_changed_during_read")

    def close(self):
        self.roots.clear()
        self.reader.close()
