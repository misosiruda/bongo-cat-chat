"""Pinned Windows runtime connection; no game files, restart or automation changes."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import pefile

from .environment import running_game
from .memory import Reader, MonoCatalog, fields
from .merge_bootstrap import EXPORTS, ERROR_EXPORT, execute, kernel, start_ticks
from .merge_bridge import BridgeChannel, read_json

HELPER = 'BongoCatChat.MergeBridge.Live.dll'


def asset_directory():
    return (Path(__file__).with_name('merge-assets') if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parents[2]/'artifacts/merge-bridge/shipped')


def no_links(path):
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or part.is_junction()):
            raise RuntimeError('bridge_session_unavailable')
    return path


def private_directory(path):
    """Create a directory atomically with current-user + SYSTEM ACL, no shell."""
    no_links(path)
    adv = C.WinDLL('advapi32', use_last_error=True)
    k = C.WinDLL('kernel32', use_last_error=True)
    adv.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    adv.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.c_void_p]
    k.GetCurrentProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]
    k.LocalFree.argtypes = [C.c_void_p]
    class Attributes(C.Structure):
        _fields_ = [('length',W.DWORD),('descriptor',C.c_void_p),('inherit',W.BOOL)]
    k.CreateDirectoryW.argtypes = [W.LPCWSTR,C.POINTER(Attributes)]
    token, size, sid, descriptor = W.HANDLE(), W.DWORD(), W.LPWSTR(), C.c_void_p()
    try:
        if not adv.OpenProcessToken(k.GetCurrentProcess(),8,C.byref(token)):
            raise OSError('token_unavailable')
        adv.GetTokenInformation(token,1,None,0,C.byref(size))
        buffer = C.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token,1,buffer,size,C.byref(size)):
            raise OSError('token_unavailable')
        if not adv.ConvertSidToStringSidW(C.cast(buffer,C.POINTER(C.c_void_p))[0],C.byref(sid)):
            raise OSError('sid_unavailable')
        sddl = f'O:{sid.value}D:P(A;OICI;FA;;;{sid.value})(A;OICI;FA;;;SY)'
        if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,C.byref(descriptor),None):
            raise OSError('acl_unavailable')
        attributes = Attributes(C.sizeof(Attributes),descriptor,False)
        if not k.CreateDirectoryW(str(path),C.byref(attributes)):
            raise FileExistsError('bridge_session_unavailable')
    finally:
        if descriptor:k.LocalFree(descriptor)
        if sid:k.LocalFree(C.cast(sid,C.c_void_p))
        if token:k.CloseHandle(token)


def check_prior_modules(reader):
    catalog = MonoCatalog(reader)
    catalog.images()  # Validate pinned layout and native accessor signatures.
    node, seen = reader.pointer(catalog.base + 0x740f90), set()
    while node:
        if node in seen or len(seen) >= 512:
            raise RuntimeError('prior_bridge_active')
        seen.add(node)
        image = reader.pointer(reader.pointer(node) + 0x60)
        name = reader.cstring(reader.pointer(image + 0x30)) or ''
        if name.startswith('BongoCatChat.MergeBridge'):
            cls = catalog.klass(image, 'Bridge', 'BongoCatChat.MergeBridge')
            offsets, tables = fields(reader,cls), catalog.vtables(cls)
            if not tables:raise RuntimeError('prior_bridge_active')
            for table in tables:
                if not reader.exact(table + 0x30,1)[0] & 4:raise RuntimeError('prior_bridge_active')
                data = reader.pointer(table + reader.i32(cls + 0x5c)*8 + 0x48)
                installed = reader.exact(data + offsets['installed'],1) != b'\0'
                stopped = reader.exact(data + offsets['stopped'],1) != b'\0'
                unknown = reader.exact(data + offsets['unknown'],1) != b'\0'
                spent = reader.i32(data + offsets['spent'])
                # An older, positively shut-down module may remain in memory.
                # Its ledger is never changed or reused. Re-loading our identity
                # is refused, including after an uncertain initialization.
                if name == HELPER[:-4] or unknown or (installed and not stopped) or (not installed and spent != 0):
                    raise RuntimeError('prior_bridge_active')
        node = reader.pointer(node + 8)


def validate_assets(game, assets):
    try:
        contract = read_json(assets/'contract.json')
        if contract['schema'] not in (2, 3):raise ValueError('unsupported_asset_schema')
        for name,key in [('Bridge.cs','source_sha256'),('MergePrepare.exe','prepare_sha256'),('Mono.Cecil.dll','cecil_sha256')]:
            if hashlib.sha256((assets/name).read_bytes()).hexdigest() != contract[key]:
                raise RuntimeError('bridge_binary_changed')
        files = contract['files']
        if not isinstance(files, dict) or not files:raise ValueError('invalid_game_files')
        allowed = {}
        for name, digests in files.items():
            path = Path(name)
            if path.is_absolute() or path.drive or '..' in path.parts:
                raise ValueError('invalid_game_path')
            if isinstance(digests, str):digests = [digests]
            elif contract['schema'] != 3:raise ValueError('unsupported_hash_list')
            if (not isinstance(digests, list) or not digests
                    or any(not isinstance(d, str) or not re.fullmatch('[0-9a-f]{64}', d) for d in digests)):
                raise ValueError('invalid_game_hash')
            allowed[name] = digests
    except (OSError,KeyError,ValueError,TypeError):
        raise RuntimeError('bridge_assets_missing') from None
    for name,digests in allowed.items():
        try:
            digest = hashlib.sha256((game.root/name).read_bytes()).hexdigest()
        except FileNotFoundError:
            raise RuntimeError('merge_game_files_missing') from None
        except OSError:
            raise RuntimeError('merge_game_files_unreadable') from None
        if digest not in digests:
            raise RuntimeError('unsupported_game_files')
    return assets,contract


def compile_helper(game, assets, session):
    """Compile our fixed source against local verified metadata, never game code execution."""
    compiler = Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():raise RuntimeError('merge_compiler_missing')
    managed = game.root/'BongoCat_Data/Managed'
    names = ('Assembly-CSharp.dll','Assembly-CSharp-firstpass.dll','UnityEngine.CoreModule.dll',
             'Heathen.Steamworks.dll','com.rlabrecque.steamworks.net.dll','Newtonsoft.Json.dll')
    dll = session/HELPER
    commands = [[str(compiler),'/nologo','/target:library','/out:'+str(dll),
                 *('/reference:'+str(managed/name) for name in names),str(assets/'Bridge.cs')],
                [str(assets/'MergePrepare.exe'),str(dll),str(managed)]]
    try:
        for command in commands:
            subprocess.run(command,check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except (OSError,subprocess.SubprocessError):
        raise RuntimeError('merge_prepare_failed') from None
    return dll


def prepare_session(game, assets, session):
    """Prepare in our newly created directory; retain any attachment evidence."""
    try:
        dll = compile_helper(game, assets, session)
        validate_assets(game, assets)  # Recheck inputs before any game memory write.
        return dll
    except Exception:
        try:
            no_links(session)
            # Only this newly created preparation path is eligible for cleanup.
            # An attachment marker, config, ledger or any other file is preserved.
            entries = list(session.iterdir())
            if all(entry.name == HELPER and entry.is_file() for entry in entries):
                no_links(session / HELPER)
                (session / HELPER).unlink(missing_ok=True)
                session.rmdir()  # Never recurse or remove unexpected contents.
        except (OSError, RuntimeError):
            pass
        raise


def connect():
    """Called only by the UI's Connect action, on a background thread."""
    from .merge_connection import InteractiveAdapter
    game = running_game()
    assets, contract = validate_assets(game,asset_directory())
    k = kernel()
    handle = k.OpenProcess(0x043a,False,game.pid)
    if not handle:raise RuntimeError('process_access_failed')
    try:
        ticks = start_ticks(k,handle)
        # Outside AppData: the MSIX development host and the game see the same path.
        parent = no_links(Path(os.environ['USERPROFILE'])/'.bongo-cat-chat')
        if not parent.exists():private_directory(parent)
        parent = parent/'merge-bridge'
        if not parent.exists():private_directory(parent)
        session = no_links(parent/f'{game.pid}-{ticks}')
        if session.exists():
            config = read_json(session/'session.json')
            if config.get('mode') != 'interactive' or config.get('source_sha256') != contract['source_sha256']:
                raise RuntimeError('bridge_session_unavailable')
            channel = BridgeChannel(session)
            try:
                raw = channel.snapshot()
                if raw['reason'] == 'closed':raise RuntimeError('bridge_session_unavailable')
                channel.request('snapshot')  # Read-only refresh; never begin/select/merge.
                return InteractiveAdapter(channel=channel)
            except Exception:
                channel.close()
                raise RuntimeError('bridge_session_unavailable') from None
        reader = Reader(game)
        try:
            check_prior_modules(reader)
            native = 'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll'
            base, exports = reader.module(native), {}
            with pefile.PE(str(game.root/native)) as pe:
                if pe.FILE_HEADER.Machine != 0x8664:raise RuntimeError('unsupported_game_build')
                for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                    name = (symbol.name or b'').decode('ascii')
                    if name not in (*EXPORTS,ERROR_EXPORT):continue
                    if symbol.forwarder or reader.exact(base+symbol.address,24) != pe.get_data(symbol.address,24):
                        raise RuntimeError('unsupported_game_build')
                    exports[name] = base+symbol.address
                if set(exports) != set((*EXPORTS,ERROR_EXPORT)):raise RuntimeError('unsupported_game_build')
        finally:reader.close()
        private_directory(session)  # Exclusive creation is the installation lock.
        dll = prepare_session(game,assets,session)
        digest = hashlib.sha256(dll.read_bytes()).hexdigest()
        config = dict(protocol=1,pid=game.pid,process_start_ticks=ticks,epoch=uuid4().hex,
                      token=secrets.token_hex(32),test_budget=0,mode='interactive',helper_sha256=digest,
                      source_sha256=contract['source_sha256'])
        (session/'session.json').write_text(json.dumps(config),encoding='utf-8')
        if hashlib.sha256((session/HELPER).read_bytes()).hexdigest() != digest:
            raise RuntimeError('bridge_binary_changed')
        if not game.alive() or start_ticks(k,handle) != ticks:raise RuntimeError('game_missing_or_ambiguous')
        (session/'attach-attempt.json').write_text(json.dumps({'attempted_at':time.time()}),encoding='utf-8')
        result = execute(handle,exports,session/HELPER)
        public = dict(status=result['status'],stage=result['stage'],managed_exception=bool(result['exception']))
        (session/'attach-result.json').write_text(json.dumps(public),encoding='utf-8')
        if result['status'] != 1:raise RuntimeError('attach_not_confirmed_no_retry')
        channel = BridgeChannel(session)
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            try:
                channel.snapshot()
                return InteractiveAdapter(channel=channel)
            except (OSError,ValueError,KeyError):time.sleep(.1)
        channel.close()
        raise RuntimeError('attach_not_confirmed_no_retry')
    finally:k.CloseHandle(handle)
