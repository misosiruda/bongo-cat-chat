"""Fixed IPC commands to the opt-in game bridge; each merge requests one item."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time
from uuid import uuid4

from .auto_merge import InputRefused, Observation, Receipt, GROUP_BY_CATEGORY
from .environment import running_game


class CommandRefused(RuntimeError):
    """The game acknowledged rejection before chest dispatch; no automatic retry."""


class CommandDeferred(InputRefused):
    """Positive evidence that no game action was dispatched; safe to try later."""


@lru_cache(maxsize=1)
def _file_api():
    api = C.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    api.CreateFileW.restype = W.HANDLE
    api.ReplaceFileW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.DWORD, W.LPVOID, W.LPVOID]
    api.ReplaceFileW.restype = W.BOOL
    api.CloseHandle.argtypes, api.CloseHandle.restype = [W.HANDLE], W.BOOL
    return api


def shared_reader(path):
    """Keep atomic replacement available while a Windows reader holds the old file."""
    if os.name != 'nt':
        return Path(path).open('rb')
    import msvcrt
    api = _file_api()
    # GENERIC_READ, FILE_SHARE_READ | WRITE | DELETE, OPEN_EXISTING.
    handle = api.CreateFileW(str(Path(path).resolve()), 0x80000000, 7, None, 3, 0x80, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        api.CloseHandle(handle)
        raise
    try:
        return os.fdopen(descriptor, 'rb')
    except Exception:
        os.close(descriptor)
        raise


def read_json(path):
    with shared_reader(path) as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('oversized_bridge_file')
    result = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('invalid_bridge_file')
    return result


def replace_observation(source, target):
    """Publish repeatable telemetry with compatible Windows delete sharing.

    Consuming requests and their sequence/ledger writes keep the existing
    publication path: failures there have different delivery guarantees.
    """
    if os.name == 'nt' and Path(target).exists():
        if not _file_api().ReplaceFileW(str(target), str(source), None, 0, None, None):
            raise C.WinError(C.get_last_error())
    else:
        os.replace(source, target)


def verify_process(config):
    game = running_game()
    if game.pid != config['pid']:
        raise RuntimeError('target_changed')
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes, k.OpenProcess.restype = [W.DWORD,W.BOOL,W.DWORD], W.HANDLE
    k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(C.c_ulonglong)]*4
    k.CloseHandle.argtypes = [W.HANDLE]
    handle = k.OpenProcess(0x400,False,game.pid)
    try:
        times = [C.c_ulonglong() for _ in range(4)]
        if not handle or not k.GetProcessTimes(handle,*(C.byref(v) for v in times)):
            raise RuntimeError('game_unavailable')
        if times[0].value + 504911232000000000 != config['process_start_ticks']:
            raise RuntimeError('target_changed')
    finally:
        if handle:k.CloseHandle(handle)


class BridgeChannel:
    """One writer per session, validated process lifetime, no mutation retries."""
    def __init__(self, session, *, verify_target=verify_process):
        self.session = Path(session).resolve()
        self.config = read_json(self.session/'session.json')
        self.verify_target = verify_target
        if (self.config['protocol'] != 1 or len(self.config['epoch']) != 32
                or len(self.config['token']) != 64 or self.config['test_budget'] not in (0,1,2)):
            raise ValueError('invalid_bridge_session')
        self.interactive = self.config.get('mode') == 'interactive'
        self.heartbeat_sequence = 0
        helper = self.session/('BongoCatChat.MergeBridge.Live.dll' if self.interactive else 'BongoCatChat.MergeBridge.Shared.dll')
        if hashlib.sha256(helper.read_bytes()).hexdigest() != self.config['helper_sha256']:
            raise ValueError('bridge_binary_changed')
        self.verify_target(self.config)
        import msvcrt
        self.lock = (self.session/'client.lock').open('a+b')
        try:
            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
        except Exception:
            self.lock.close()
            raise RuntimeError('bridge_client_in_use') from None

    def close(self):
        self.lock.close()

    def snapshot(self):
        raw = read_json(self.session/'snapshot.json')
        if (raw['protocol'] != 1 or raw['epoch'] != self.config['epoch']
                or raw['pid'] != self.config['pid']):
            raise ValueError('bridge_snapshot_mismatch')
        if not 0 <= time.time()*1000 - raw['captured_utc_ms'] <= 1500:
            raise ValueError('observation_stale')
        return raw

    def heartbeat(self, run_attempt):
        """Non-consuming liveness mailbox, independent of inventory and RPC replies."""
        if not self.interactive or not run_attempt:
            raise InputRefused
        self.verify_target(self.config)
        self.heartbeat_sequence += 1
        value = dict(epoch=self.config['epoch'], token=self.config['token'],
                     chest_run_attempt=run_attempt, sequence=self.heartbeat_sequence,
                     issued_utc_ms=int(time.time()*1000))
        temp = self.session/'heartbeat.client.tmp'
        temp.write_text(json.dumps(value,separators=(',',':')),encoding='utf-8')
        replace_observation(temp,self.session/'heartbeat.json')

    def request(self, op, *, attempt=None, expected=None, group=None, limit=None,
                chest_settings=None, replace_legacy=False, chest_run_attempt=None):
        if op not in {'begin','group','select','merge','stop','snapshot','shutdown',
                      'chest_start','chest_stop','chest_heartbeat'}:
            raise InputRefused
        try:
            self.verify_target(self.config)
        except RuntimeError as exc:
            if str(exc) in {'game_unavailable', 'game_missing_or_ambiguous'}:
                raise CommandDeferred('connection_recovering') from exc
            raise
        try:
            raw = self.snapshot()
        except (OSError, ValueError, KeyError) as exc:
            raise CommandDeferred('connection_recovering') from exc
        if op in {'begin', 'select', 'merge', 'chest_start', 'group'} and not raw['ready']:
            if raw['reason'] in {'inventory_refreshing', 'game_unavailable', 'bridge_observation_failed'}:
                raise CommandDeferred(raw['reason'])
            raise InputRefused
        if expected is not None:
            if (expected.target != self.config['epoch']
                    or GROUP_BY_CATEGORY.get(expected.category) != raw['group']
                    or (expected.favorites_allowed,expected.events_excluded) != (raw['favorites_allowed'],raw['events_excluded'])):
                raise InputRefused
            if op in {'select', 'merge'} and expected.run_attempt and expected.run_attempt != raw.get('run_attempt'):
                raise InputRefused
        request = dict(id=uuid4().hex,epoch=self.config['epoch'],token=self.config['token'],
                       op=op,issued_utc_ms=int(time.time()*1000),expected_group=raw['group'],
                       favorites_allowed=raw['favorites_allowed'],events_excluded=raw['events_excluded'])
        if attempt is not None:
            request['operation_id'] = attempt
        if op == 'chest_heartbeat':
            request['chest_run_attempt'] = chest_run_attempt
        if self.interactive:
            # Snapshot can lag the acknowledgement. Persist our high-water mark
            # before dispatch so an uncertain request is never sent again.
            sequence_file = self.session/'client-sequence.json'
            try:
                previous = read_json(sequence_file)['sequence'] if sequence_file.exists() else 0
            except OSError as exc:
                raise CommandDeferred('connection_recovering') from exc
            sequence = max(previous, raw['command_sequence']) + 1
            tmp_sequence = self.session/'client-sequence.tmp'
            try:
                tmp_sequence.write_text(json.dumps({'sequence':sequence}),encoding='utf-8')
                os.replace(tmp_sequence,sequence_file)
            except OSError as exc:
                raise CommandDeferred('connection_recovering') from exc
            request.update(sequence=sequence,run_attempt=raw['run_attempt'])
        if op == 'begin':
            if not self.interactive or type(limit) is not int or not 1 <= limit <= 2147483647 - raw['spent']:
                raise InputRefused
            request['limit'] = limit
        if op.startswith('chest_') and not self.interactive:
            raise InputRefused
        if op == 'chest_start':
            from .auto_chest import settings
            if type(replace_legacy) is not bool:
                raise InputRefused
            request.update(chest_settings=settings(chest_settings), replace_legacy=replace_legacy)
        if op == 'group':
            if group not in ('cosmetics','emotes'):raise InputRefused
            request['group'] = group
        if op == 'merge':
            if (not raw['ready'] or raw['selected_units'] != 10 or raw['exchanges'] != 1
                    or raw['pending_attempt'] or raw['spent'] >= raw['test_budget']
                    or expected is not None and (expected.selection,expected.selection_attempt) != (raw['selection'],raw['selection_attempt'])):
                raise InputRefused
            request.update(count=1,selection=raw['selection'],selection_attempt=raw['selection_attempt'])
        tmp = self.session/'request.client.tmp'
        try:
            tmp.write_text(json.dumps(request,separators=(',',':')),encoding='utf-8')
            os.replace(tmp,self.session/'request.json')
        except OSError as exc:
            raise CommandDeferred('connection_recovering') from exc
        deadline = time.monotonic()+3.5
        while time.monotonic()<deadline:
            try:
                reply = read_json(self.session/'response.json')
                if reply['id'] == request['id'] and reply['epoch'] == self.config['epoch']:
                    if reply.get('ok') is not True:
                        if reply.get('deferred') is True and reply.get('reason') in {'inventory_refreshing', 'game_unavailable', 'connection_recovering'}:
                            raise CommandDeferred(reply['reason'])
                        if op.startswith('chest_'):
                            safe = {'chest_busy', 'chest_unavailable', 'legacy_busy', 'legacy_unverified',
                                    'legacy_confirmation_required', 'run_not_authorized', 'chest_active'}
                            reason = reply.get('reason')
                            raise CommandRefused(reason if reason in safe else 'input_failed')
                        raise RuntimeError('input_failed')
                    return dict(reply, _sequence=request.get('sequence', 0))
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.05)
        raise RuntimeError('result_unverified')


def observation(raw, *, clock=time.monotonic, wall=time.time):
    """Preserve source age: rereading a stale file cannot renew its lifetime."""
    age = wall()*1000 - raw['captured_utc_ms']
    if (not 0 <= age <= 1500 or raw['group'] not in ('cosmetics','emotes')
            or raw['available_group'] != raw['group'] or raw['per_request_limit'] != 1
            or type(raw['spent']) is not int or type(raw['test_budget']) is not int
            or not 0 <= raw['spent'] <= raw['test_budget'] <= (2147483647 if raw.get('mode') == 'interactive' else 2)):
        raise ValueError('invalid_bridge_snapshot')
    receipt = raw['receipt']
    if receipt is not None:
        receipt = Receipt(receipt['attempt'],receipt['completed'],receipt['finished'],receipt['failed'])
    return Observation(clock()-age/1000,target=raw['epoch'],category=raw['group'],
        ready=raw['ready'],reason=raw['reason'],favorites_allowed=raw['favorites_allowed'],
        events_excluded=raw['events_excluded'],selected_units=raw['selected_units'],exchanges=raw['exchanges'],
        selection=raw['selection'],selection_attempt=raw['selection_attempt'],can_select=raw['can_select'],
        exchanging=raw['exchanging'],receipt=receipt,available_exchanges=raw['available_exchanges'],
        available_group=raw['available_group'],run_attempt=raw.get('run_attempt',''),
        execution_budget_remaining=None if raw.get('mode') == 'interactive' else raw['test_budget']-raw['spent'])


class BridgeAdapter:
    def __init__(self, session=None, *, channel=None):
        self.channel = channel if channel is not None else BridgeChannel(session)
        self.latest = Observation(time.monotonic(),reason='adapter_unverified')
        self.lock = threading.Lock()
        self.commands = queue.Queue(maxsize=2)
        self.stop_event = threading.Event()
        self.busy = False
        self.fault = False
        self.requested_group = None
        self.chest = None
        self.chest_requested = False
        self.next_heartbeat = 0.0
        self.chest_sequence = 0
        self.chest_owns_lease = False
        self.chest_command_error = ''
        self.chest_run_attempt = ''
        self.chest_stop_pending = False
        self.command_generation = 0
        self.cancelled_attempt = ''
        self.thread = threading.Thread(target=self._run,name='merge-bridge',daemon=True)
        self.thread.start()

    def _run(self):
        deferred = None
        try:
            while not self.stop_event.is_set():
                command, deferred = deferred, None
                if command is None:
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        pass
                if (command and command['op'] not in {'stop', 'chest_stop'}
                        and command.get('_generation', 0) != self.command_generation):
                    if command['op'] == 'merge':self.cancelled_attempt = command['attempt']
                    command = None
                if command:
                    try:
                        reply = self.channel.request(**{k:v for k,v in command.items() if not k.startswith('_')})
                        if command['op'].startswith('chest_'):
                            self.chest_sequence = reply.get('_sequence', 0)
                            self.chest_command_error = ''
                            if command['op'] == 'chest_start' and not self.chest_stop_pending:
                                self.chest_owns_lease = True
                            if command['op'] == 'chest_stop':
                                self.chest_owns_lease = False
                    except CommandDeferred:
                        deferred = command
                        with self.lock:
                            self.latest = replace(self.latest, ready=False, reason='connection_recovering')
                    except CommandRefused as exc:
                        self.chest_command_error = str(exc)
                        if command['op'] == 'chest_start':self.chest_run_attempt = ''
                    except RuntimeError as exc:
                        if str(exc) == 'result_unverified':
                            # Never resend an uncertain action. Its operation id
                            # can still be reconciled from a later fresh snapshot.
                            with self.lock:
                                self.latest = replace(self.latest, ready=False, reason='connection_recovering')
                        else:
                            with self.lock:
                                self.fault = True
                                self.latest = replace(self.latest, ready=False, reason='input_failed')
                    except Exception:
                        with self.lock:
                            self.fault = True
                            self.latest = replace(self.latest,ready=False,reason='input_failed')
                            if self.chest:
                                self.chest = dict(self.chest, reason='input_failed')
                    finally:
                        with self.lock:self.busy = deferred is not None or not self.commands.empty()
                else:
                    with self.lock:self.busy = not self.commands.empty()
                if (not self.fault and self.chest_requested and self.chest_owns_lease
                        and not self.chest_stop_pending and time.monotonic() >= self.next_heartbeat):
                    try:
                        self.channel.heartbeat(self.chest_run_attempt)
                        self.next_heartbeat = time.monotonic() + .75
                    except Exception as exc:
                        if str(exc) == 'target_changed':
                            self.fault = True
                            self.chest_owns_lease = False
                        # Source health is still observed below. No response wait
                        # or heartbeat error may starve the observation loop.
                if not self.fault or self.chest is not None:
                    try:
                        self.channel.verify_target(self.channel.config)
                        raw = self.channel.snapshot()
                        value = observation(raw)
                        with self.lock:
                            chest = raw.get('chest')
                            if isinstance(chest, dict) and raw.get('command_sequence', 0) >= self.chest_sequence:
                                from .auto_chest import observation as chest_observation
                                self.chest = chest_observation(chest, value.captured_at)
                                if self.chest_command_error:
                                    self.chest['reason'] = self.chest_command_error
                                self.chest_requested = self.chest['armed']
                                if (not self.chest_stop_pending and self.chest_run_attempt
                                        and chest.get('run_attempt') == self.chest_run_attempt
                                        and self.chest['armed'] and not self.chest['unknown']):
                                    self.chest_owns_lease = True
                            if not self.fault and (self.requested_group is None or value.category == self.requested_group):
                                self.latest = (replace(value, ready=False, reason='connection_recovering')
                                               if deferred else value)
                                self.requested_group = None
                    except (OSError,ValueError,KeyError):
                        pass  # Retain source time. The orchestrator expires it.
                    except Exception as exc:
                        with self.lock:
                            changed = str(exc) == 'target_changed'
                            if changed:
                                self.fault = True
                                self.chest_owns_lease = False
                            self.latest = Observation(time.monotonic(),reason='target_changed' if changed else 'connection_recovering')
                self.stop_event.wait(.5 if deferred else .1)
        finally:
            # No new consuming operation; an uncertain stop is bounded by the game-side lease.
            if self.chest_requested:
                try:self.channel.request('chest_stop')
                except Exception:pass
            if self.latest.run_attempt:
                # Release only our verified selection/run, without resending a
                # merge or cancelling an exchange already accepted by the game.
                try:self.channel.request('stop')
                except Exception:pass
            self.channel.close()

    def observe(self):
        with self.lock:return replace(self.latest, cancelled_attempt=self.cancelled_attempt)

    def _submit(self, op, expected=None, attempt=None, group=None, limit=None, **extra):
        with self.lock:
            if self.stop_event.is_set() or self.fault or self.busy:
                raise InputRefused
            if expected is not None and (not self.latest.ready or self.latest.target != expected.target
                    or not 0 <= time.monotonic()-self.latest.captured_at <= 1.5):
                raise InputRefused
            if op == 'chest_start':
                attempt = uuid4().hex
                self.chest_run_attempt = attempt
                self.chest_stop_pending = False
            self.commands.put_nowait(dict(op=op,expected=expected,attempt=attempt,group=group,limit=limit,
                                          _generation=self.command_generation,**extra))
            self.busy = True
            if op == 'chest_start':
                self.chest_requested = True
                if self.chest:
                    self.chest = dict(self.chest, armed=True, reason='starting')
            if op == 'group':
                self.requested_group = group
                self.latest = replace(self.latest,ready=False,reason='group_changing',category=group,
                                      available_exchanges=None,available_group='')

    def select_duplicates(self, expected, attempt):
        self._submit('select',expected,attempt)

    def merge(self, expected, attempt):
        self._submit('merge',expected,attempt)

    def set_group(self, group):
        self._submit('group',group=group)

    def stop_selection(self):
        # No new consume request; an already submitted consume is not cancelled.
        with self.lock:
            if not self.stop_event.is_set() and not self.fault:
                self._cancel_pending()
                self.commands.put_nowait(dict(op='stop', _generation=self.command_generation))
                self.busy = True

    def _cancel_pending(self):
        self.command_generation += 1
        while True:
            try:
                command = self.commands.get_nowait()
                if command['op'] == 'merge':self.cancelled_attempt = command['attempt']
            except queue.Empty:break

    def cancel_pending(self):
        with self.lock:
            self.command_generation += 1
            stops = []
            while True:
                try:
                    command = self.commands.get_nowait()
                    if command['op'] in {'stop', 'chest_stop'}:stops.append(command)
                    elif command['op'] == 'merge':self.cancelled_attempt = command['attempt']
                except queue.Empty:break
            for command in stops:self.commands.put_nowait(command)

    def chest_snapshot(self):
        with self.lock:
            if self.chest is None:return None
            value = dict(self.chest, supported=self.chest['supported'] and not self.fault)
            if (self.busy and self.chest_run_attempt and not self.chest_stop_pending
                    and not value['armed'] and not value['unknown'] and not self.chest_command_error):
                value.update(armed=True, reason='connection_recovering')
            return value

    def chest_start(self, preferences, replace_legacy=False):
        self._submit('chest_start', chest_settings=preferences, replace_legacy=replace_legacy)

    def chest_stop(self):
        with self.lock:
            if self.stop_event.is_set():return
            self.chest_stop_pending = True
            self.chest_owns_lease = False
            self._cancel_pending()
            self.commands.put_nowait(dict(op='chest_stop', _generation=self.command_generation))
            self.busy = True

    def close(self):
        self.chest_stop_pending = True
        self.chest_owns_lease = False
        self.stop_event.set()
        self.thread.join(.5)
