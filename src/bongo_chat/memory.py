"""Experimental reader behind a feature contract and a known Mono ABI.

Only OpenProcess(QUERY_INFORMATION | VM_READ), ReadProcessMemory and query APIs.
No saved addresses, remote calls, process writes, injection or file mutations.
"""
import ctypes as C
from ctypes import wintypes as W
import base64
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
import time


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
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.handle = self.k.OpenProcess(0x0400 | 0x0010, False, game.pid)
        if not self.handle:
            raise MemoryUnavailable("process_read_denied")
        self.scan_helper = ((Path(__file__).with_name("compatibility") if getattr(sys, "frozen", False)
                             else Path(__file__).resolve().parents[2] / "artifacts/compatibility") / "MemoryScan.exe")

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

    def module(self, relative):
        """Locate the loaded image in this process, never load or invoke it."""
        api = C.WinDLL("psapi", use_last_error=True)
        api.EnumProcessModulesEx.argtypes = [W.HANDLE, C.POINTER(W.HMODULE), W.DWORD, C.POINTER(W.DWORD), W.DWORD]
        api.EnumProcessModulesEx.restype = W.BOOL
        api.GetModuleFileNameExW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]
        api.GetModuleFileNameExW.restype = W.DWORD
        modules, needed = (W.HMODULE * 2048)(), W.DWORD()
        if (not api.EnumProcessModulesEx(self.handle, modules, C.sizeof(modules), C.byref(needed), 3)
                or not 0 < needed.value <= C.sizeof(modules) or needed.value % C.sizeof(W.HMODULE)):
            raise MemoryUnavailable("module_list_unavailable")
        expected, matches = self.game.root / relative, []
        for module in modules[:needed.value // C.sizeof(W.HMODULE)]:
            path = C.create_unicode_buffer(32768)
            size = api.GetModuleFileNameExW(self.handle, module, path, len(path))
            if 0 < size < len(path) and Path(path.value) == expected:
                matches.append(module)
        if len(matches) != 1:
            raise MemoryUnavailable("module_not_unique")
        return matches[0]

    def scan(self, patterns, private_only=True, pointer_aligned=False):
        if not patterns or len(patterns) > 500:
            raise MemoryUnavailable("unsupported_metadata_candidates")
        if not self.scan_helper.is_file():
            raise MemoryUnavailable("memory_scan_tool_missing")
        if not self.game.alive():
            raise MemoryUnavailable("process_changed")
        if self.stop and self.stop.is_set():
            raise MemoryUnavailable("discovery_cancelled_or_budget")
        payload = json.dumps(dict(pid=self.game.pid, private_only=private_only, pointer_aligned=pointer_aligned,
                                  patterns={key: base64.b64encode(value).decode("ascii") for key, value in patterns.items()})).encode("ascii")
        if len(payload) > 65536:
            raise MemoryUnavailable("unsupported_metadata_candidates")
        process = subprocess.Popen([str(self.scan_helper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        started = time.monotonic()
        try:
            while True:
                if (self.stop and self.stop.is_set()) or time.monotonic()-started > 120:
                    raise MemoryUnavailable("discovery_cancelled_or_budget")
                try:
                    output, _ = process.communicate(input=payload, timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
                finally:
                    payload = None
            if len(output) > 16*1024*1024:
                raise MemoryUnavailable("memory_scan_failed")
            try:
                result = json.loads(output)
            except (ValueError, UnicodeError):
                raise MemoryUnavailable("memory_scan_failed") from None
            if process.returncode != 0:
                code = result.get("error") if isinstance(result, dict) else None
                known = {"unsupported_metadata_candidates", "unsupported_pointer_pattern", "ambiguous_metadata",
                         "discovery_cancelled_or_budget", "process_read_denied", "memory_read_failed"}
                raise MemoryUnavailable(code if code in known else "memory_scan_failed")
            if not isinstance(result, dict) or result.keys() != patterns.keys():
                raise MemoryUnavailable("memory_scan_failed")
            for values in result.values():
                if (not isinstance(values, list) or len(values) > 4096
                        or any(type(value) is not int or not 0x10000 <= value < 0x7fffffffffff
                               or pointer_aligned and value % 8 for value in values)):
                    raise MemoryUnavailable("memory_scan_failed")
            if not self.game.alive():
                raise MemoryUnavailable("process_changed")
            return {key: set(values) for key, values in result.items()}
        finally:
            if process.poll() is None:
                process.kill()  # Our scan helper only; never the game or Steam.
            process.communicate()


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


class MonoCatalog:
    """Read the already-loaded class catalog of the hash-pinned Mono ABI.

    The RVAs/layouts are derived from that binary's assembly enumeration,
    class-cache lookup and class-vtable lookup code. No remote functions run.
    All pointers are resolved anew; malformed/changing lists fail closed.
    """

    def __init__(self, reader):
        self.r = reader
        self.started = time.monotonic()

    def check(self):
        if self.r.stop and self.r.stop.is_set():
            raise MemoryUnavailable("discovery_cancelled_or_budget")
        if time.monotonic() - self.started > 5:
            raise MemoryUnavailable("catalog_unavailable")

    def images(self):
        r = self.r
        self.check()
        if not r.game.alive():
            raise MemoryUnavailable("process_changed")
        base = r.module("MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll")
        # Verify the loaded accessors as well as the caller's native file hash.
        signatures = {0xb4ef8: "488b0d91c06800", 0xb51d0: "488b4160c3",
                      0x14d420: "488b4130c3", 0xc4f93: "498d8dd0040000",
                      0x147340: "488d8108010000c3", 0x1c5f97: "488b9fd0000000"}
        for offset, value in signatures.items():
            expected = bytes.fromhex(value)
            if r.exact(base + offset, len(expected)) != expected:
                raise MemoryUnavailable("unsupported_catalog_layout")
        head = r.pointer(base + 0x740f90)
        node, links, images = head, {}, {}
        while node:
            self.check()
            if node in links or len(links) >= 512:
                raise MemoryUnavailable("assembly_list_invalid")
            link = r.exact(node, 16)
            assembly, next_node = struct.unpack("<QQ", link)
            links[node] = link
            image = r.pointer(assembly + 0x60)
            name = r.cstring(r.pointer(image + 0x30))
            if name in ("Assembly-CSharp", "Heathen.Steamworks"):
                if name in images or r.pointer(image + 0x4c0) != assembly:
                    raise MemoryUnavailable("assembly_not_unique")
                images[name] = image
            node = next_node
        if (head != r.pointer(base + 0x740f90)
                or any(r.exact(node, 16) != link for node, link in links.items())):
            raise MemoryUnavailable("assembly_list_changed")
        if set(images) != {"Assembly-CSharp", "Heathen.Steamworks"}:
            raise MemoryUnavailable("assembly_missing")
        self.base = base
        return images

    def klass(self, image, name, ns):
        r = self.r
        table = image + 0x4d0
        header = r.exact(table, 40)
        count, entries, buckets = struct.unpack_from("<iiQ", header, 24)
        if (not 0 < count <= 16384 or not 0 < entries <= 16384
                or struct.unpack_from("<Q", header, 16)[0] != self.base + 0x147340):
            raise MemoryUnavailable("class_catalog_invalid")
        bucket_data = r.exact(buckets, count * 8)
        links, matches = {}, set()
        for (cls,) in struct.iter_unpack("<Q", bucket_data):
            while cls:
                self.check()
                if cls in links or len(links) >= entries:
                    raise MemoryUnavailable("class_catalog_invalid")
                data = r.exact(cls, 0x110)
                next_cls = struct.unpack_from("<Q", data, 0x108)[0]
                if struct.unpack_from("<Q", data, 0x40)[0] != image:
                    raise MemoryUnavailable("class_image_mismatch")
                links[cls] = next_cls
                if (r.cstring(struct.unpack_from("<Q", data, 0x48)[0]) == name
                        and r.cstring(struct.unpack_from("<Q", data, 0x50)[0]) == ns):
                    matches.add(cls)
                cls = next_cls
        if (len(links) != entries or r.exact(table, 40) != header
                or r.exact(buckets, count * 8) != bucket_data
                or any(r.pointer(cls + 0x108) != link for cls, link in links.items())):
            raise MemoryUnavailable("class_catalog_changed")
        if len(matches) != 1:
            raise MemoryUnavailable("metadata_not_unique")
        return next(iter(matches))

    def vtables(self, cls):
        r = self.r
        self.check()
        info = r.pointer(cls + 0xd0)
        maximum = struct.unpack("<H", r.exact(info, 2))[0]
        if maximum >= 64:
            raise MemoryUnavailable("unsupported_domains")
        data = r.exact(info + 8, (maximum + 1) * 8)
        result = set()
        for index, (vtable,) in enumerate(struct.iter_unpack("<Q", data)):
            if not vtable:
                continue
            if (vtable in result or r.pointer(vtable) != cls
                    or r.i32(r.pointer(vtable + 0x10) + 0x94) != index):
                raise MemoryUnavailable("invalid_catalog_vtable")
            result.add(vtable)
        if (r.pointer(cls + 0xd0) != info or r.exact(info, 2) != struct.pack("<H", maximum)
                or r.exact(info + 8, len(data)) != data):
            raise MemoryUnavailable("catalog_vtable_changed")
        return result

    def locate(self, specifications):
        images = self.images()
        classes = {key: self.klass(images["Assembly-CSharp" if key == "cache" else "Heathen.Steamworks"], name, ns)
                   for key, (name, ns, _) in specifications.items()}
        vtables = {key: self.vtables(cls) for key, cls in classes.items()}
        self.check()
        if not self.r.game.alive():
            raise MemoryUnavailable("process_changed")
        return classes, vtables


class GameMemory:
    def __init__(self, game, stop=None):
        self.reader = Reader(game, stop)
        self.roots = {}
        self.diagnostics = {}

    def discover(self):
        specifications = {"cache": ("PlayerDataCache", "", "_playerDataCache"),
                          "lobby": ("LobbyData", "Heathen.SteamworksIntegration", "Current")}
        try:
            pointers, vtables = MonoCatalog(self.reader).locate(specifications)
            self.resolve_roots(specifications, pointers, vtables)
            self.diagnostics["discovery_method"] = "catalog"
            return
        except MemoryUnavailable as error:
            self.roots.clear()
            # Catalog initialization/races may prevent the fast lookup. The
            # existing bounded scan still has to pass the same root validation.
            if (str(error) in {"unsupported_catalog_layout", "process_changed"}
                    or self.reader.stop and self.reader.stop.is_set()):
                raise
        self.discover_scan(specifications)
        self.diagnostics["discovery_method"] = "scan"

    def discover_scan(self, specifications):
        r = self.reader
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
        self.resolve_roots(specifications, pointers, vtables)

    def resolve_roots(self, specifications, pointers, vtables):
        r = self.reader
        for key, cls in pointers.items():
            if (class_name(r, cls), namespace(r, cls)) != specifications[key][:2]:
                raise MemoryUnavailable("stale_class")
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
        # The shared Mono domain/root validation above is still required for
        # lobby identity. Reading the hidden list is a separate, retryable step.

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


class MemoryDiscovery:
    """Find roots without blocking Steam callbacks; hand off one owned reader."""

    def __init__(self, game, stop):
        self.game, self.stop = game, stop
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.memory = None
        self.failed = False
        self.thread = threading.Thread(target=self.run, daemon=True, name="game-memory-discovery")
        self.thread.start()

    def is_set(self):
        return self.cancelled.is_set() or self.stop.is_set()

    def run(self):
        memory = None
        try:
            memory = GameMemory(self.game, self)
            memory.discover()
            with self.lock:
                if not self.is_set():
                    self.memory, memory = memory, None
        except Exception:
            self.failed = True  # Never publish addresses, identifiers or raw errors.
        finally:
            if memory:
                memory.close()
            self.done.set()

    def close(self):
        self.cancelled.set()
        with self.lock:
            memory, self.memory = self.memory, None
        if memory:
            memory.close()
        # A cancelled in-flight scan closes its own reader before finishing.
        self.thread.join(1)
