"""Pinned Windows runtime connection; no game files, restart or automation changes."""
import ctypes as C
from ctypes import wintypes as W
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import pefile

from .automation_compat import validate_game_files
from .environment import running_game
from .memory import Reader, MonoCatalog, fields
from .merge_bootstrap import EXPORTS, ERROR_EXPORT, DIAGNOSTIC_EXPORTS, execute, kernel, start_ticks
from .merge_bridge import BridgeChannel, read_json

HELPER = 'BongoCatChat.MergeBridge.Live.dll'


def asset_directory():
    return (Path(__file__).with_name('merge-assets') if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parents[2]/'artifacts/merge-bridge/shipped')


def no_links(path):
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or part.is_junction()):
            raise RuntimeError('bridge_path_unsupported')
    return path


def storage_error(exc):
    """Classify only known filesystem operations; never publish a raw OS message."""
    code = getattr(exc, 'winerror', None)
    if code == 5 or isinstance(exc, PermissionError):
        return 'bridge_storage_access_denied'
    if code in (39, 112) or exc.errno == errno.ENOSPC:
        return 'bridge_storage_full'
    if code in (80, 183) or isinstance(exc, FileExistsError):
        return 'bridge_storage_conflict'
    return 'bridge_storage_failed'


def write_session_json(path, value):
    try:
        path.write_text(json.dumps(value), encoding='utf-8')
    except OSError as exc:
        raise RuntimeError(storage_error(exc)) from None


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
            raise RuntimeError('bridge_storage_security_failed')
        adv.GetTokenInformation(token,1,None,0,C.byref(size))
        buffer = C.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token,1,buffer,size,C.byref(size)):
            raise RuntimeError('bridge_storage_security_failed')
        if not adv.ConvertSidToStringSidW(C.cast(buffer,C.POINTER(C.c_void_p))[0],C.byref(sid)):
            raise RuntimeError('bridge_storage_security_failed')
        sddl = f'O:{sid.value}D:P(A;OICI;FA;;;{sid.value})(A;OICI;FA;;;SY)'
        if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,C.byref(descriptor),None):
            raise RuntimeError('bridge_storage_security_failed')
        attributes = Attributes(C.sizeof(Attributes),descriptor,False)
        if not k.CreateDirectoryW(str(path),C.byref(attributes)):
            raise C.WinError(C.get_last_error())
    except OSError as exc:
        raise RuntimeError(storage_error(exc)) from None
    finally:
        if descriptor:k.LocalFree(descriptor)
        if sid:k.LocalFree(C.cast(sid,C.c_void_p))
        if token:k.CloseHandle(token)


def check_prior_modules(reader):
    try:
        _check_prior_modules(reader)
    except Exception as exc:
        if str(exc) == 'prior_bridge_active':
            raise
        raise RuntimeError('bridge_module_scan_failed') from None


def _check_prior_modules(reader):
    catalog = MonoCatalog(reader)
    catalog.images()  # Validate pinned layout and native accessor signatures.
    node, seen = reader.pointer(catalog.base + 0x740f90), set()
    while node:
        if node in seen or len(seen) >= 512:
            raise RuntimeError('bridge_module_scan_failed')
        seen.add(node)
        image = reader.pointer(reader.pointer(node) + 0x60)
        name = reader.cstring(reader.pointer(image + 0x30)) or ''
        if name.startswith('BongoCatChat.MergeBridge'):
            cls = catalog.klass(image, 'Bridge', 'BongoCatChat.MergeBridge')
            offsets, tables = fields(reader,cls), catalog.vtables(cls)
            if not tables:raise RuntimeError('bridge_module_scan_failed')
            for table in tables:
                if not reader.exact(table + 0x30,1)[0] & 4:raise RuntimeError('bridge_module_scan_failed')
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
        schema = contract['schema']
        if schema != 6:raise ValueError('unsupported_asset_schema')
        for name,key in [('Bridge.cs','source_sha256'),('MergePrepare.exe','prepare_sha256'),('Mono.Cecil.dll','cecil_sha256'),
                         ('FeatureProbe.exe','probe_sha256'),('feature-spec.json','spec_sha256')]:
            if hashlib.sha256((assets/name).read_bytes()).hexdigest() != contract[key]:
                raise RuntimeError('bridge_binary_changed')
    except (OSError,KeyError,ValueError,TypeError):
        raise RuntimeError('bridge_assets_missing') from None
    validate_game_files(game.root, contract, assets)
    return assets,contract


def compile_helper(game, assets, session):
    """Compile our fixed source against local verified metadata, never game code execution."""
    compiler = Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():raise RuntimeError('merge_compiler_missing')
    managed = game.root/'BongoCat_Data/Managed'
    names = ('Assembly-CSharp.dll','Assembly-CSharp-firstpass.dll','UnityEngine.CoreModule.dll',
             'Heathen.Steamworks.dll','com.rlabrecque.steamworks.net.dll','Newtonsoft.Json.dll','DOTween.dll')
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


def prepare_session(game, assets, session, compatibility=None):
    """Prepare in our newly created directory; retain any attachment evidence."""
    try:
        _, contract = validate_assets(game, assets)
        before = validate_game_files(game.root, contract, assets)
        if compatibility is not None and compatibility != before:
            raise RuntimeError('automation_files_changed')
        dll = compile_helper(game, assets, session)
        validate_assets(game, assets)  # Recheck inputs before any game memory write.
        if before != validate_game_files(game.root, contract, assets):
            raise RuntimeError('automation_files_changed')
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


def open_channel(session):
    try:
        return BridgeChannel(session)
    except OSError as exc:
        raise RuntimeError(storage_error(exc)) from None
    except (ValueError, KeyError, TypeError) as exc:
        reason = 'bridge_binary_changed' if str(exc) == 'bridge_binary_changed' else 'bridge_session_invalid'
        raise RuntimeError(reason) from None
    except RuntimeError as exc:
        if str(exc) == 'bridge_client_in_use':raise
        reason = 'bridge_target_changed' if str(exc) in {'target_changed', 'game_missing_or_ambiguous'} else 'bridge_target_unverified'
        raise RuntimeError(reason) from None


def wait_snapshot(channel, timeout_error='bridge_response_pending'):
    """Wait only for telemetry; never reload a module or resend an operation."""
    deadline = time.monotonic() + 5
    while True:
        try:
            channel.verify_target(channel.config)
        except Exception as exc:
            reason = 'bridge_target_changed' if str(exc) in {'target_changed', 'game_missing_or_ambiguous'} else 'bridge_target_unverified'
            raise RuntimeError(reason) from None
        try:
            raw = channel.snapshot()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, FileNotFoundError) or str(exc) == 'observation_stale':
                failure = timeout_error
            elif isinstance(exc, PermissionError):
                failure = 'bridge_storage_access_denied'
            elif isinstance(exc, OSError):
                failure = 'bridge_response_unreadable'
            else:
                failure = 'bridge_response_invalid'
            # A shutdown snapshot is terminal even after its timestamp expires.
            try:
                last = read_json(channel.session/'snapshot.json')
            except (OSError, ValueError):
                last = {}
            if (last.get('epoch') == channel.config['epoch'] and last.get('pid') == channel.config['pid']
                    and last.get('protocol') == channel.config['protocol'] and last.get('reason') == 'closed'):
                raise RuntimeError('bridge_session_closed') from None
            if time.monotonic() >= deadline:
                raise RuntimeError(failure) from None
            time.sleep(.1)
            continue
        if raw.get('reason') == 'closed':
            raise RuntimeError('bridge_session_closed')
        return raw


def connect():
    """Background connection after manual Connect or saved chest startup consent."""
    from .diagnostics import clean_details
    details = {'phase': 'find_game'}
    try:
        return _connect(details)
    except Exception as exc:
        # Only fixed labels/numbers reach reports. Keep the original exception
        # type and failure behavior; never retry a load to collect diagnostics.
        if isinstance(exc, OSError):
            details['winerror'] = getattr(exc, 'winerror', None)
        exc.connection_diagnostics = clean_details(details)
        raise


def _connect(details):
    from .merge_connection import InteractiveAdapter
    game = running_game()
    details['phase'] = 'validate_assets'
    assets, contract = validate_assets(game,asset_directory())
    details['phase'] = 'open_process'
    k = kernel()
    handle = k.OpenProcess(0x043a,False,game.pid)
    if not handle:
        details['winerror'] = C.get_last_error()
        raise RuntimeError('process_access_failed')
    try:
        details['phase'] = 'session_path'
        ticks = start_ticks(k,handle)
        # Outside AppData: the MSIX development host and the game see the same path.
        parent = no_links(Path(os.environ['USERPROFILE'])/'.bongo-cat-chat')
        if not parent.exists():private_directory(parent)
        parent = parent/'merge-bridge'
        if not parent.exists():private_directory(parent)
        session = no_links(parent/f'{game.pid}-{ticks}')
        if session.exists():
            details.update(source='existing', phase='read_session')
            try:
                config = read_json(session/'session.json')
            except FileNotFoundError:
                raise RuntimeError('bridge_session_invalid') from None
            except OSError as exc:
                raise RuntimeError(storage_error(exc)) from None
            except (ValueError, KeyError, TypeError):
                raise RuntimeError('bridge_session_invalid') from None
            if not isinstance(config.get('mode'), str) or not isinstance(config.get('source_sha256'), str):
                raise RuntimeError('bridge_session_invalid')
            if config.get('mode') != 'interactive' or config.get('source_sha256') != contract['source_sha256']:
                raise RuntimeError('bridge_session_incompatible')
            details['phase'] = 'open_channel'
            channel = open_channel(session)
            try:
                details['phase'] = 'read_attach_result'
                try:
                    attached = read_json(session/'attach-result.json')
                    details.update(attach_record='present')
                    from .diagnostics import clean_details
                    details.update(clean_details({key: attached.get(key) for key in
                        ('status', 'stage', 'managed_exception', 'load_error', 'managed_exception_types',
                         'managed_reason', 'initialization_step')}))
                except FileNotFoundError:
                    details['attach_record'] = 'missing'
                    attached = {}
                except OSError as exc:
                    details['attach_record'] = 'unreadable'
                    raise RuntimeError(storage_error(exc)) from None
                except ValueError:
                    details['attach_record'] = 'invalid'
                    raise RuntimeError('bridge_session_invalid') from None
                confirmed = (attached.get('status') == 1 and attached.get('stage') == 7
                             and attached.get('managed_exception') is False)
                details['phase'] = 'wait_response'
                failed = attached.get('status') == 2 and attached.get('stage') == 7 and attached.get('managed_exception') is True
                raw = wait_snapshot(channel, 'bridge_response_pending' if confirmed else
                    'bridge_initialization_failed' if failed else 'attach_not_confirmed_no_retry')
                if raw.get('chest', {}).get('armed'):
                    details['phase'] = 'stop_previous'
                    try:
                        channel.request('chest_stop')  # Reconnect never adopts an earlier run's lease.
                    except Exception:
                        raise RuntimeError('bridge_stop_unconfirmed') from None
                details['phase'] = 'refresh_response'
                try:
                    channel.request('snapshot')  # Read-only refresh; never begin/select/merge.
                except Exception:
                    raise RuntimeError('bridge_reconnect_failed') from None
                return InteractiveAdapter(channel=channel)
            except Exception:
                channel.close()
                raise
        details.update(source='new', phase='inspect_modules')
        reader = Reader(game)
        try:
            check_prior_modules(reader)
            native = 'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll'
            base, exports = reader.module(native), {}
            with pefile.PE(str(game.root/native)) as pe:
                if pe.FILE_HEADER.Machine != 0x8664:raise RuntimeError('unsupported_game_build')
                for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                    name = (symbol.name or b'').decode('ascii')
                    if name not in (*EXPORTS,ERROR_EXPORT,*DIAGNOSTIC_EXPORTS):continue
                    if symbol.forwarder or reader.exact(base+symbol.address,24) != pe.get_data(symbol.address,24):
                        raise RuntimeError('unsupported_game_build')
                    exports[name] = base+symbol.address
                if set(exports) != set((*EXPORTS,ERROR_EXPORT,*DIAGNOSTIC_EXPORTS)):raise RuntimeError('unsupported_game_build')
        finally:reader.close()
        details['phase'] = 'validate_game'
        compatibility = validate_game_files(game.root, contract, assets)
        details['phase'] = 'prepare_module'
        private_directory(session)  # Exclusive creation is the installation lock.
        dll = prepare_session(game,assets,session,compatibility)
        digest = hashlib.sha256(dll.read_bytes()).hexdigest()
        config = dict(protocol=1,pid=game.pid,process_start_ticks=ticks,epoch=uuid4().hex,
                      token=secrets.token_hex(32),test_budget=0,mode='interactive',helper_sha256=digest,
                      source_sha256=contract['source_sha256'],
                      assembly_mvids=compatibility['modules'])
        details['phase'] = 'write_session'
        write_session_json(session/'session.json', config)
        if hashlib.sha256((session/HELPER).read_bytes()).hexdigest() != digest:
            raise RuntimeError('bridge_binary_changed')
        if not game.alive() or start_ticks(k,handle) != ticks:raise RuntimeError('game_missing_or_ambiguous')
        if compatibility != validate_game_files(game.root, contract, assets):
            raise RuntimeError('automation_files_changed')
        write_session_json(session/'attach-attempt.json', {'attempted_at':time.time()})
        details.update(phase='bootstrap', attach_record='missing')
        try:
            result = execute(handle,exports,session/HELPER)
        except (OSError, RuntimeError) as exc:
            from .diagnostics import NATIVE_ERRORS
            details['native_error'] = (str(exc) if str(exc) in NATIVE_ERRORS else
                                       'native_os_error' if isinstance(exc, OSError) else 'native_failed')
            details['winerror'] = getattr(exc, 'winerror', None)
            raise RuntimeError('attach_not_confirmed_no_retry') from None
        details.update(status=result['status'], stage=result['stage'],
                       managed_exception=bool(result['exception']), load_error=result.get('load_error'))
        from .diagnostics import clean_details
        details.update(clean_details({key: result.get(key) for key in
            ('managed_exception_types', 'managed_reason', 'initialization_step')}))
        details['phase'] = 'write_attach_result'
        public = dict(status=result['status'],stage=result['stage'],managed_exception=bool(result['exception']))
        public.update(clean_details({key: details.get(key) for key in
            ('load_error', 'managed_exception_types', 'managed_reason', 'initialization_step')}))
        write_session_json(session/'attach-result.json', public)
        details.update(phase='bootstrap', attach_record='present')
        if result['status'] != 1:
            try:
                failure = read_json(session/'compatibility-error.json')
            except (OSError, ValueError):
                failure = {}
            if failure == {'epoch': config['epoch'], 'reason': 'automation_files_changed'}:
                raise RuntimeError('automation_files_changed')
            if result['status'] == 2 and result['stage'] == 7 and result['exception']:
                raise RuntimeError('bridge_initialization_failed')
            raise RuntimeError('attach_not_confirmed_no_retry')
        details['phase'] = 'open_channel'
        channel = open_channel(session)
        try:
            details['phase'] = 'wait_response'
            wait_snapshot(channel)
            return InteractiveAdapter(channel=channel)
        except Exception:
            channel.close()
            raise
    finally:k.CloseHandle(handle)
