"""Fixed IPC commands to the opt-in game bridge; each merge requests one item."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import replace
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


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('oversized_bridge_file')
    result = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('invalid_bridge_file')
    return result


def verify_process(config):
    game = running_game()
    if game.pid != config['pid']:
        raise RuntimeError('game_unavailable')
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
                or raw['pid'] != self.config['pid']
                or not 0 <= time.time()*1000 - raw['captured_utc_ms'] <= 1500):
            raise ValueError('observation_stale')
        return raw

    def request(self, op, *, attempt=None, expected=None, group=None, limit=None):
        if op not in {'begin','group','select','merge','stop','snapshot','shutdown'}:
            raise InputRefused
        self.verify_target(self.config)
        raw = self.snapshot()
        if expected is not None:
            if (expected.target != self.config['epoch']
                    or GROUP_BY_CATEGORY.get(expected.category) != raw['group']
                    or (expected.favorites_allowed,expected.events_excluded) != (raw['favorites_allowed'],raw['events_excluded'])):
                raise InputRefused
        request = dict(id=attempt or uuid4().hex,epoch=self.config['epoch'],token=self.config['token'],
                       op=op,issued_utc_ms=int(time.time()*1000),expected_group=raw['group'],
                       favorites_allowed=raw['favorites_allowed'],events_excluded=raw['events_excluded'])
        if self.interactive:
            # Snapshot can lag the acknowledgement. Persist our high-water mark
            # before dispatch so an uncertain request is never sent again.
            sequence_file = self.session/'client-sequence.json'
            previous = read_json(sequence_file)['sequence'] if sequence_file.exists() else 0
            sequence = max(previous, raw['command_sequence']) + 1
            tmp_sequence = self.session/'client-sequence.tmp'
            tmp_sequence.write_text(json.dumps({'sequence':sequence}),encoding='utf-8')
            os.replace(tmp_sequence,sequence_file)
            request.update(sequence=sequence,run_attempt=raw['run_attempt'])
        if op == 'begin':
            if not self.interactive or type(limit) is not int or not 1 <= limit <= 2147483647 - raw['spent']:
                raise InputRefused
            request['limit'] = limit
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
        tmp.write_text(json.dumps(request,separators=(',',':')),encoding='utf-8')
        os.replace(tmp,self.session/'request.json')
        deadline = time.monotonic()+3.5
        while time.monotonic()<deadline:
            try:
                reply = read_json(self.session/'response.json')
                if reply['id'] == request['id'] and reply['epoch'] == self.config['epoch']:
                    if reply.get('ok') is not True:
                        raise RuntimeError('input_failed')
                    return reply
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
        self.thread = threading.Thread(target=self._run,name='merge-bridge',daemon=True)
        self.thread.start()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    command = None
                if command:
                    try:
                        self.channel.request(**command)
                    except Exception:
                        with self.lock:
                            self.fault = True
                            self.latest = replace(self.latest,ready=False,reason='input_failed')
                    finally:
                        with self.lock:self.busy = not self.commands.empty()
                if not self.fault:
                    try:
                        self.channel.verify_target(self.channel.config)
                        value = observation(self.channel.snapshot())
                        with self.lock:
                            if self.requested_group is None or value.category == self.requested_group:
                                self.latest = value
                                self.requested_group = None
                    except (OSError,ValueError,KeyError):
                        pass  # Retain source time. The orchestrator expires it.
                    except Exception:
                        with self.lock:self.latest = Observation(time.monotonic(),reason='game_unavailable')
                self.stop_event.wait(.1)
        finally:
            self.channel.close()

    def observe(self):
        with self.lock:return self.latest

    def _submit(self, op, expected=None, attempt=None, group=None, limit=None):
        with self.lock:
            if self.stop_event.is_set() or self.fault or self.busy:
                raise InputRefused
            if expected is not None and (not self.latest.ready or self.latest.target != expected.target
                    or not 0 <= time.monotonic()-self.latest.captured_at <= 1.5):
                raise InputRefused
            self.commands.put_nowait(dict(op=op,expected=expected,attempt=attempt,group=group,limit=limit))
            self.busy = True
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
                try:self.commands.put_nowait(dict(op='stop'))
                except queue.Full:pass
                self.busy = True

    def close(self):
        self.stop_event.set()
        self.thread.join(.5)
