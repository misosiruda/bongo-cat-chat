"""One unattended restart of an interrupted automation, owned by the installed launcher."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import time

import psutil

from .auto_chest import settings as chest_settings
from .auto_merge import GROUP_BY_CATEGORY, MAX_SAFE_COUNT, RECOVERABLE
from .environment import running_game
from .exit_codes import RECOVERY_RETURN, RECOVERY_TOKEN
from .updates import atomic_json, child, load_json


OUTAGE_SECONDS = 120
STABLE_SECONDS = 60
PREF = 'unattended_recovery'
BASE59 = '0123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def fingerprint(value):
    return hashlib.sha256(str(value).encode('ascii')).hexdigest()


def handoff_path(data, token):
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise ValueError('invalid_recovery_token')
    return child(data, 'recovery-' + token + '.json')


def valid_plan(plan):
    """A partial or corrupt handoff never authorizes a restart or a new run."""
    if not isinstance(plan, dict):
        return False
    if any(type(plan.get(k)) is not int or plan[k] <= 0 for k in ('pid', 'ticks')):
        return False
    if type(plan.get('created')) not in (int, float) or not 0 < plan['created'] < float('inf'):
        return False
    for key, length in (('epoch', 32), ('account', 64), ('lobby', 64)):
        if not isinstance(plan.get(key), str) or not re.fullmatch('[0-9a-f]{%d}' % length, plan[key]):
            return False
    if plan.get('mode') == 'chest':
        try:
            chest_settings(plan.get('preferences'))
            return True
        except ValueError:
            return False
    return (plan.get('mode') == 'merge' and plan.get('group') in ('cosmetics', 'emotes')
            and all(type(plan.get(k)) is bool for k in ('favorites', 'events'))
            and all(type(plan.get(k)) is int for k in ('completed', 'limit'))
            and 0 <= plan['completed'] < plan['limit'] <= MAX_SAFE_COUNT)


def saved_lobby_setting(expected_lobby, *, enable=False):
    import winreg
    access = winreg.KEY_QUERY_VALUE | (winreg.KEY_SET_VALUE if enable else 0)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Irox Games\BongoCat', 0, access) as key:
        code, kind = winreg.QueryValueEx(key, 'LAST_LOBBY_h626087530')
        if kind == winreg.REG_BINARY:
            code = code.rstrip(b'\0').decode('ascii')
        if not isinstance(code, str) or not 1 <= len(code) <= 11:
            raise ValueError('missing_saved_lobby')
        lobby = 0
        for char in code:
            lobby = lobby * len(BASE59) + BASE59.index(char)
        if not lobby or fingerprint(lobby) != expected_lobby:
            raise ValueError('different_saved_lobby')
        name = 'JoinLastLobby_h3133418007'
        try:
            value, kind = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            value, kind = 0, winreg.REG_DWORD
        if kind != winreg.REG_DWORD or value not in (0, 1):
            raise ValueError('invalid_lobby_preference')
        if enable and not value:
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)
            winreg.FlushKey(key)
            if winreg.QueryValueEx(key, name) != (1, winreg.REG_DWORD):
                raise OSError('lobby_preference_not_saved')


def game_window(game):
    """Resolve the current Unity window without taking focus."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    matches = []

    @callback
    def collect(window, unused):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == game.pid:
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(window, name, len(name))
            if name.value == 'UnityWndClass':
                matches.append(window)
        return True

    user.EnumWindows(collect, 0)
    if len(matches) != 1 or not game.alive():
        raise RuntimeError('game_window_changed')
    return user, matches[0]


def close_game(game):
    proc = psutil.Process(game.pid)
    user, window = game_window(game)
    if not user.PostMessageW(window, 0x10, 0, 0):
        raise RuntimeError('game_close_failed')
    proc.wait(timeout=30)


def read_recovery_record(path):
    # The largest record is the ledger with up to 512 SHA-256 keys.
    with path.open('rb') as stream:
        record = stream.read(65537)
    if len(record) > 65536:
        raise ValueError('oversized_recovery_record')
    try:
        return load_json(record)
    except RecursionError as exc:
        raise ValueError('invalid_recovery_record') from exc


def previous_chest_requests(plan):
    """Recover only opaque keys for outstanding remote ready cycles, after checking the result ledger."""
    if plan['mode'] != 'chest':
        return []
    session = child(Path.home() / '.bongo-cat-chat' / 'merge-bridge',
                    f"{plan['pid']}-{plan['ticks']}")
    config = read_recovery_record(child(session, 'session.json'))
    if config.get('epoch') != plan['epoch']:
        raise ValueError('unexpected_chest_session')
    ledger = read_recovery_record(child(session, 'chest-ledger.json'))
    # A stopped dispatcher can still be waiting for the result of its last
    # request. Keep the snapshot and the independent write-ahead ledger.
    raw = read_recovery_record(child(session, 'snapshot.json'))
    chest = raw.get('chest')
    if (raw.get('epoch') != plan['epoch'] or not isinstance(chest, dict)
            or chest.get('unknown') is not False or chest.get('pending') is not False
            or ledger.get('state') not in ('armed', 'confirmed', 'failed', 'remote_requested', 'remote_cycle_ended')):
        raise ValueError('unresolved_chest')
    keys = ledger.get('remote_keys')
    if (not isinstance(keys, list) or len(keys) > 512
            or any(not isinstance(k, str) or not re.fullmatch('[0-9A-F]{64}', k) for k in keys)):
        raise ValueError('invalid_remote_chest_keys')
    return keys


def restart_game(plan):
    game = running_game()
    if (game.pid, game.created) != (plan['pid'], plan['created']):
        raise ValueError('game_changed')
    saved_lobby_setting(plan['lobby'])
    if plan['mode'] == 'chest':
        # The old Chat has exited. Even with no IPC response its three-second
        # heartbeat lease must expire before trusting the durable request state.
        time.sleep(4)
    if not game.alive():
        raise ValueError('game_changed')
    previous_chest_requests(plan)
    close_game(game)
    # If Windows fails to save the setting after game exit, still return the
    # user's game and Chat, with automatic actions disabled for this return.
    try:
        if any(p.info['name'].lower() == 'bongocat.exe' for p in psutil.process_iter(['name']) if p.info['name']):
            raise ValueError('another_game_started')
        try:
            saved_lobby_setting(plan['lobby'], enable=True)
            previous_chest_requests(plan)
        finally:
            os.startfile('steam://rungameid/3419430')
    except OSError as exc:
        raise RuntimeError('game_restart_failed') from exc
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            new = running_game()
        except RuntimeError:
            time.sleep(.5)
            continue
        if new.root != game.root or new.created <= game.created:
            raise ValueError('unexpected_game')
        return dict(plan, new_pid=new.pid, new_created=new.created)
    raise RuntimeError('game_launch_timeout')


class GameRecovery:
    def __init__(self, data, store, supported, clock=time.monotonic):
        self.data, self.store, self.clock = data, store, clock
        self.token = os.environ.get(RECOVERY_TOKEN, '') if supported else ''
        self.supported = bool(re.fullmatch('[0-9a-f]{32}', self.token))
        try:
            self.enabled = store.setting(PREF, default=False) is True
        except (TypeError, ValueError):
            self.enabled = False
        self.status = 'idle'
        self.context = self.run = self.since = self.candidate = None
        self.resume = None
        self.last_connect = float('-inf')
        self.group_requested = False
        self.stable_since = None
        self.cooldown = False
        returned = os.environ.get(RECOVERY_RETURN) if self.supported else None
        self.returned = bool(returned)
        if returned:
            self.status = 'failed'
            if self.enabled:
                try:
                    payload = json.loads(returned)
                except ValueError:
                    payload = None
                if (valid_plan(payload) and type(payload.get('new_pid')) is int
                        and type(payload.get('new_created')) in (int, float)
                        and payload['new_created'] > payload['created']):
                    self.resume = payload
                    self.status = 'waiting_room'
            self.cooldown = True

    def cancel(self):
        self.resume = self.run = self.since = self.candidate = self.stable_since = None
        self.status = 'idle'

    def set_enabled(self, value):
        if type(value) is not bool or not self.supported:
            raise ValueError('invalid_setting')
        self.store.setting(PREF, value)
        self.enabled = value
        self.cancel()

    def view(self):
        return dict(supported=self.supported, enabled=self.enabled, status=self.status,
                    can_cancel=self.resume is not None)

    def tick(self, service, merger, chests, connection):
        if not self.supported or not self.enabled or not connection:
            return
        state = service.state
        verified = service.verified()
        current = None
        if verified:
            current = (state['game_pid'], state['game_created'],
                       fingerprint(state['account']), fingerprint(state['lobby']))
        if self.resume:
            self._resume(current, state, merger, chests, connection)
            return
        chest = chests.snapshot()
        if merger.active and not merger.stop_requested:
            run = ('merge', merger.run_attempt)
            base = merger.baseline
            work = dict(group=GROUP_BY_CATEGORY[base.category], favorites=base.favorites_allowed,
                        events=base.events_excluded, limit=merger.limit, completed=merger.completed)
            unsafe = bool(merger.pending_attempt or merger.unresolved or merger.completed >= merger.limit
                          or base.favorites_allowed is None or base.events_excluded is None)
            outage = merger.reason == 'connection_recovering' or merger.recovering_since is not None
        elif chest['armed'] and chest.get('owned_run'):
            run = ('chest', chest['owned_run'])
            work = dict(preferences=dict(chests.preferences))
            unsafe = not chest['enabled'] or chest['pending'] or chest['unknown'] or not chest.get('supported')
            outage = chest['enabled'] and chest['reason'] in ('inventory_refreshing', 'connection_recovering')
        else:
            run = None
        if run is not None and self.run != run:
            self.context, self.run, self.since, self.stable_since = current, run, None, None
            if self.status in ('failed', 'changed', 'blocked'):
                self.status = 'idle'
        # Only the first observation of a given run may establish its room.
        # A pause or a missing lease observation does not create a new run.
        if current and current != self.context:
            self.context = None
        if self.context and state.get('account') and fingerprint(state['account']) != self.context[2]:
            self.context = None
        self.candidate = None
        if run is None:
            self.since = self.stable_since = None
            if self.status in ('watching', 'due'):
                self.status = 'idle'
            return
        if unsafe or not self.context or not outage:
            self.since = None
            if not outage and verified and not unsafe:
                if self.stable_since is None:
                    self.stable_since = self.clock()
                if self.clock() - self.stable_since >= STABLE_SECONDS:
                    self.cooldown = False
            else:
                self.stable_since = None
            if self.status in ('watching', 'due'):
                self.status = 'idle'
            return
        self.stable_since = None
        if self.cooldown:
            return
        if self.since is None:
            self.since = self.clock()
        self.status = 'watching'
        if self.clock() - self.since < OUTAGE_SECONDS:
            return
        identity = connection.recovery_identity()
        pid, created, account, lobby = self.context
        if identity and identity[0] == pid:
            self.candidate = dict(mode=run[0], pid=pid, created=created, account=account, lobby=lobby,
                                  ticks=identity[1], epoch=identity[2], **work)
            self.status = 'due'

    def handoff(self):
        if not self.candidate:
            return False
        atomic_json(handoff_path(self.data, self.token), self.candidate)
        return True

    def _resume(self, current, state, merger, chests, connection):
        plan = self.resume
        if state.get('game_pid') and (state['game_pid'], state['game_created']) != (
                plan['new_pid'], plan['new_created']):
            self._finish('changed')
            return
        if state.get('account') and fingerprint(state['account']) != plan['account']:
            self._finish('changed')
            return
        if not current:
            self.status = 'waiting_room'
            return
        pid, _, account, lobby = current
        if (account, lobby) != (plan['account'], plan['lobby']):
            self._finish('changed')
            return
        # Bind to the first verified new process. User restarts do not transfer that authority.
        if self.context and self.context != current:
            self._finish('changed')
            return
        self.context = current
        self.status = 'waiting_feature'
        link = connection.connection_snapshot()
        if link['state'] in ('disconnected', 'error'):
            if link['state'] == 'error' and link['error'] not in (
                    'bridge_response_pending', 'bridge_reconnect_failed', 'bridge_response_unreadable',
                    'game_missing_or_ambiguous'):
                self._finish('failed')
            elif self.clock() - self.last_connect >= 15:
                self.last_connect = self.clock()
                connection.connect()
            return
        identity = connection.recovery_identity()
        if not identity:
            return
        if identity[0] != pid or identity[2] == plan['epoch']:
            self._finish('changed')
            return
        chest = chests.snapshot()
        if not chest['fresh']:
            return
        if chest['unknown'] or chest['pending'] or chest['armed'] or chest.get('legacy_detected'):
            self._finish('blocked')
            return
        value = merger.observe()
        if not value.ready:
            if value.reason not in RECOVERABLE | {'group_changing', 'adapter_unverified'}:
                self._finish('blocked')
            return
        if value.exchanging or value.selection or value.selected_units or value.exchanges:
            self._finish('blocked')
            return
        if plan['mode'] == 'chest':
            if chest_settings(plan['preferences']) != chests.preferences or not chest['can_start']:
                self._finish('changed')
                return
            try:
                keys = previous_chest_requests(plan)
            except (ValueError, OSError, TypeError, KeyError):
                self._finish('blocked')
                return
            ok = chests.start(remote_keys=keys)
        else:
            if (value.favorites_allowed, value.events_excluded) != (plan['favorites'], plan['events']):
                self._finish('changed')
                return
            if GROUP_BY_CATEGORY.get(value.category) != plan['group']:
                if not self.group_requested:
                    self.group_requested = merger.set_group(plan['group'])
                else:
                    self._finish('changed')
                return
            ok = merger.start(plan['limit'], completed=plan['completed'], expected=value)
        self._finish('resumed' if ok else 'blocked')

    def _finish(self, status):
        self.resume = None
        self.status = status
