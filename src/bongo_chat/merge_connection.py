"""User-initiated connection lifecycle. Connecting never selects or merges."""
import threading
import time

from .auto_merge import InputRefused, Observation
from .merge_bridge import BridgeAdapter
from .diagnostics import clean_details, connection_error


class InteractiveAdapter(BridgeAdapter):
    def begin_run(self, expected, limit, attempt):
        self._submit('begin', expected, attempt, limit=limit)


class MergeConnection:
    def __init__(self, connector=None):
        if connector is None:
            from .merge_install import connect
            connector = connect
        self.connector = connector
        self.adapter = None
        self.state, self.error = 'disconnected', ''
        self.revision = 0
        self.lock = threading.Lock()
        self.closed = False
        self.thread = None
        self.diagnostics = []

    def diagnostic_snapshot(self):
        with self.lock:
            return dict(state=self.state, error=self.error,
                        attempts=[dict(item) for item in self.diagnostics])

    def connection_snapshot(self):
        with self.lock:
            return dict(state=self.state, error=self.error,
                        revision=self.revision,
                        can_connect=not self.closed and self.state != 'connecting')

    def connect(self):
        with self.lock:
            if self.closed or self.state == 'connecting':
                return False
            self.state, self.error = 'connecting', ''
            self.revision += 1
            self.thread = threading.Thread(target=self._connect, name='merge-connect', daemon=True)
            self.thread.start()
        return True

    def _connect(self):
        try:
            with self.lock:
                previous, self.adapter = self.adapter, None
            if previous:
                previous.close()
                previous.thread.join(4)  # Release the one-writer lock before reuse.
            adapter = self.connector()
            with self.lock:
                if self.closed:
                    adapter.close()
                else:
                    self.adapter, self.state = adapter, 'connected'
        except Exception as exc:
            # Never return filesystem paths, account details or raw native errors.
            with self.lock:
                self.state = 'error'
                self.error = connection_error(str(exc))
                self.diagnostics.append(dict(clean_details(getattr(exc, 'connection_diagnostics', None)),
                                             error=self.error))
                self.diagnostics = self.diagnostics[-3:]

    def observe(self):
        with self.lock:
            adapter = self.adapter
        return adapter.observe() if adapter else Observation(time.monotonic(), reason='adapter_unverified')

    def _call(self, method, *args):
        with self.lock:
            adapter = self.adapter
            if self.closed or adapter is None:
                raise InputRefused
        return getattr(adapter, method)(*args)

    def begin_run(self, expected, limit, attempt):
        return self._call('begin_run', expected, limit, attempt)

    def select_duplicates(self, expected, attempt):
        return self._call('select_duplicates', expected, attempt)

    def merge(self, expected, attempt):
        return self._call('merge', expected, attempt)

    def set_group(self, group):
        return self._call('set_group', group)

    def stop_selection(self):
        return self._call('stop_selection')

    def cancel_pending(self):
        with self.lock:
            adapter = self.adapter
        if adapter:adapter.cancel_pending()

    def chest_snapshot(self):
        with self.lock:
            adapter = self.adapter
        return adapter.chest_snapshot() if adapter else None

    def chest_start(self, preferences, replace_legacy=False):
        return self._call('chest_start', preferences, replace_legacy)

    def chest_stop(self):
        with self.lock:
            adapter = self.adapter
        if adapter:adapter.chest_stop()

    def close(self):
        with self.lock:
            self.closed = True
            adapter = self.adapter
        if adapter:
            adapter.close()
