"""GUI-thread notification policy. No deferred receipts, Steam, or message text."""
import time

TOAST_INTERVAL = 5.0


class UnavailableToast:
    def show(self):
        return 'unavailable'

    def clear(self):
        pass


class Notifications:
    def __init__(self, service, toast=None, *, clock=time.monotonic, enabled=True):
        self.service = service
        self.toast = toast or UnavailableToast()
        self.clock = clock
        self.enabled = enabled
        self.attention = None
        self.active = lambda: True
        self.closed = False
        self.flashing = False
        self.has_toast = False
        self.last_toast = float('-inf')
        self.last_incoming = None
        self.toast_status = 'ready' if toast else 'unavailable'
        self.flash_status = 'ready'
        self.toast_failed = False

    def bind(self, attention, active):
        self.attention, self.active = attention, active

    def stop_flash(self):
        if self.flashing:
            self.flashing = False
            try:
                self.attention.stop()
            except Exception:
                self.flash_status = 'unavailable'

    def clear_toast(self):
        if self.has_toast:
            self.has_toast = False
            try:
                self.toast.clear()
            except Exception:
                # Never retry a failing OS API on every 100 ms poll.
                self.toast_status = 'cleanup_failed'

    def cancel(self):
        self.stop_flash()
        self.clear_toast()
        self.last_incoming = None

    def sync(self):
        if self.closed:
            return
        if self.active() or (self.last_incoming and not self.last_incoming.current(self.service)):
            self.cancel()
            self.last_toast = float('-inf')

    def settings_changed(self, key, value):
        if key == 'notification_flash' and not value:
            self.stop_flash()
        if key == 'notification_toast':
            if not value:
                self.clear_toast()
            # A user OFF/ON cycle or restart is the explicit retry boundary.
            self.toast_failed = False
            self.last_toast = float('-inf')

    def incoming(self, receipt):
        if (not receipt or self.closed or not self.enabled or self.active()
                or not receipt.current(self.service)):
            return
        self.last_incoming = receipt
        settings = self.service.notifications
        if settings['notification_flash'] and self.attention and not self.flashing:
            try:
                if self.attention.start() is False:
                    self.flash_status = 'unavailable'
                else:
                    self.flashing = True
            except Exception:
                self.flash_status = 'unavailable'
        now = self.clock()
        if settings['notification_toast'] and not self.toast_failed and now - self.last_toast >= TOAST_INTERVAL:
            self.last_toast = now
            try:
                result = self.toast.show()
                self.toast_status = result if isinstance(result, str) else 'unavailable'
                if result == 'sent':
                    self.has_toast = True
                elif result != 'disabled':
                    self.toast_failed = True
            except Exception:
                self.toast_status = 'unavailable'
                self.toast_failed = True

    def close(self):
        if not self.closed:
            self.closed = True
            self.cancel()

    def snapshot(self):
        return dict(toast=self.toast_status, flash=self.flash_status)
