"""Offline Windows notification feasibility probe; never starts a Steam worker.

Run with the repository venv. All history/settings belong to the explicit probe
directory. This tool is not connected to the shipped application's receive path.
"""
import argparse
import ctypes
import json
from pathlib import Path
import platform
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from bongo_chat.service import ChatService
from bongo_chat.store import Store

FLASH = 'probe_notification_flash'
TOAST = 'probe_notification_toast'


def fixture_state(**changes):
    return dict(dict(state='ready', account='fixture-self', lobby='fixture-room',
                     generation='fixture-generation', connected=True,
                     lobby_verified=True, privacy_ready=True, hidden_ok=True,
                     members=['fixture-self', 'fixture-peer'], profiles={}, send_enabled=False,
                     name='알림 검증 전용'), **changes)


class ProbePolicy:
    def __init__(self, store):
        self.store = store
        self.service = ChatService(store, clock=lambda: 100.0)
        self.service.update(fixture_state())

    def set_enabled(self, key, enabled):
        if key not in (FLASH, TOAST) or type(enabled) is not bool:
            raise ValueError('invalid_notification_setting')
        self.store.setting(key, enabled)

    def enabled(self, key):
        # Probe-only default, not a product default decision.
        return self.store.setting(key, default=True) is True

    def receive(self, foreground, **changes):
        event = dict(id=str(uuid4()), text='새 채팅 알림 기술 검증입니다.',
                     sender='fixture-peer', context=self.service.context())
        event.update(changes)
        before = self.service.revision
        self.service.receive(event)
        accepted = self.service.revision != before
        eligible = accepted and event['sender'] != self.service.state['account'] and not foreground
        # Revision comparison is a synchronous probe adapter only. Production
        # should return an explicit accepted-incoming result from receive().
        return dict(accepted=accepted, foreground=foreground,
                    flash=bool(eligible and self.enabled(FLASH)),
                    toast=bool(eligible and self.enabled(TOAST)))


def run(data):
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QEvent, Qt, QTimer, qVersion
    from PySide6.QtWidgets import (QApplication, QCheckBox, QLabel, QPushButton,
                                   QStyle, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget)

    class FlashInfo(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('hwnd', ctypes.c_void_p),
                    ('dwFlags', ctypes.c_uint), ('uCount', ctypes.c_uint),
                    ('dwTimeout', ctypes.c_uint)]

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.FlashWindowEx.argtypes = [ctypes.POINTER(FlashInfo)]
    user32.FlashWindowEx.restype = ctypes.c_int

    data.mkdir(parents=True, exist_ok=True)
    marker = data / 'notification-probe.marker'
    if any(data.iterdir()) and not marker.exists():
        raise ValueError('Use an empty directory reserved for this probe')
    marker.touch()
    store = Store(data / 'probe.sqlite3')
    policy = ProbePolicy(store)
    app = QApplication([])
    app.setApplicationName('Bongo Cat Chat Notification Probe')
    icon = app.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
    app.setWindowIcon(icon)
    events = []

    class ProbeWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('Bongo Cat Chat · 알림 기술 검증 (오프라인)')
            self.resize(610, 490)
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel('가상 수신만 사용합니다. 게임·실제 대화·제품 설정에 연결하지 않습니다.'))
            layout.addWidget(QLabel('두 체크박스는 이 시험 폴더에 저장되며 다음 실행에도 유지됩니다.'))
            self.checks = {}
            for key, label in ((FLASH, '작업 표시줄 깜빡임'), (TOAST, 'Windows 기본 알림')):
                check = QCheckBox(label)
                check.setChecked(policy.enabled(key))
                check.toggled.connect(lambda value, key=key: self.change_setting(key, value))
                layout.addWidget(check)
                self.checks[key] = check
            for label, callback in (
                ('지금 가상 채팅 수신 (포커스 상태 검사)', self.receive),
                ('15초 후 가상 채팅 수신 (다른 창으로 전환)', self.schedule),
                ('최소화 후 3초 뒤 가상 채팅 수신', self.minimized),
                ('시험 종료', self.close),
            ):
                button = QPushButton(label)
                button.clicked.connect(callback)
                layout.addWidget(button)
            self.log = QTextEdit()
            self.log.setReadOnly(True)
            layout.addWidget(self.log)
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip('Bongo Cat Chat 알림 검증')
            self.tray.messageClicked.connect(self.restore)
            self.tray.show()
            self.record('environment', windows=platform.platform(), qt=qVersion(),
                        pyside=pyside_version, tray_available=self.tray.isSystemTrayAvailable(),
                        supports_messages=self.tray.supportsMessages(),
                        settings={key: policy.enabled(key) for key in (FLASH, TOAST)})

        def record(self, kind, **values):
            entry = dict(kind=kind, **values)
            events.append(entry)
            self.log.append(json.dumps(entry, ensure_ascii=False))
            (data / 'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf-8')

        def stop_flash(self):
            info = FlashInfo(ctypes.sizeof(FlashInfo), int(self.winId()), 0, 0, 0)
            # FlashWindowEx returns the previous caption state, not success.
            user32.FlashWindowEx(ctypes.byref(info))

        def change_setting(self, key, value):
            try:
                policy.set_enabled(key, value)
            except (OSError, sqlite3.Error):
                check = self.checks[key]
                check.blockSignals(True)
                # Restore the previous toggle without reading the failing DB again.
                check.setChecked(not value)
                check.blockSignals(False)
                self.record('setting_save_failed', key=key)
                return
            if key == FLASH and not value:
                self.stop_flash()
            self.record('setting_saved', key=key, value=value)

        def schedule(self):
            self.record('scheduled', delay_seconds=15)
            QTimer.singleShot(15000, self.receive)

        def minimized(self):
            self.showMinimized()
            QTimer.singleShot(3000, self.receive)

        def receive(self):
            foreground = app.applicationState() == Qt.ApplicationState.ApplicationActive
            result = policy.receive(foreground)
            native_before = user32.GetForegroundWindow()
            if result['flash']:
                QApplication.alert(self, 0)
            if result['toast']:
                self.tray.showMessage('Bongo Cat Chat · 알림 검증',
                                      '새 채팅 알림 기술 검증입니다. (가상 메시지)',
                                      QSystemTrayIcon.MessageIcon.Information, 10000)
            self.record('received', **result, minimized=self.isMinimized(),
                        foreground_unchanged=user32.GetForegroundWindow() == native_before,
                        native_foreground_is_probe=native_before == int(self.winId()))

        def restore(self):
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self.stop_flash()
            self.record('notification_clicked')

        def changeEvent(self, event):
            super().changeEvent(event)
            if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and hasattr(self, 'log'):
                self.stop_flash()
                self.record('focus_returned')

        def closeEvent(self, event):
            self.stop_flash()
            self.tray.hide()
            super().closeEvent(event)

    window = ProbeWindow()
    window.show()
    try:
        return app.exec()
    finally:
        store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True, help='Empty probe-only directory (not product data)')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('The native probe requires Windows')
    raise SystemExit(run(args.data.resolve()))
