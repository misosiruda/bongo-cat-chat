"""Small Windows boundary: owned shortcut repair, taskbar attention and WinRT.

All methods run on the GUI STA. No shell commands or network operations.
"""
import ctypes
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import uuid
from xml.sax.saxutils import escape

from .localization import resolve_language, translate

APP_ID = 'BongoCatChat.Desktop'
TOAST_GROUP = 'incoming'
TOAST_TAG = 'new-message'
# Fixed text only. No account, room, sender, or message content reaches the OS.
TOAST_XML = ('<toast><visual><binding template="ToastGeneric">'
             '<text>Bongo Cat Chat</text><text>새 메시지가 도착했어요.</text>'
             '</binding></visual></toast>')


def set_app_id():
    shell = ctypes.WinDLL('shell32')
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    if shell.SetCurrentProcessExplicitAppUserModelID(APP_ID) < 0:
        raise OSError('notification_identity_failed')


class Attention:
    def __init__(self, window):
        self.window = window

    def start(self):
        from PySide6.QtWidgets import QApplication
        QApplication.alert(self.window, 0)

    def stop(self):
        if os.name != 'nt':
            return
        from ctypes import wintypes

        class FlashInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.UINT), ('window', wintypes.HWND),
                        ('flags', wintypes.DWORD), ('count', wintypes.UINT), ('timeout', wintypes.DWORD)]

        user = ctypes.WinDLL('user32')
        user.FlashWindowEx.argtypes = [ctypes.POINTER(FlashInfo)]
        user.FlashWindowEx.restype = wintypes.BOOL
        # Return value describes the previous caption state, not success.
        user.FlashWindowEx(ctypes.byref(FlashInfo(ctypes.sizeof(FlashInfo), int(self.window.winId()), 0, 0, 0)))


def repair_shortcut(root):
    """Upgrade a legacy default shortcut only after checking its exact target.

    Fresh shortcuts are made by Setup. Missing/custom shortcuts are not created
    by the app, so -NoShortcut remains respected. The stable launcher is used
    through version switches and rollback. COM calls are narrowly scoped here.
    """
    root = Path(root).resolve(strict=True)
    launcher = root / 'BongoCatChat.exe'
    link_path = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk'
    if not launcher.is_file() or not link_path.is_file() or link_path.is_symlink():
        raise OSError('notification_shortcut_missing')

    class Guid(ctypes.Structure):
        _fields_ = [('bytes', ctypes.c_ubyte * 16)]

        def __init__(self, value):
            super().__init__((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))

    class Key(ctypes.Structure):
        _fields_ = [('fmtid', Guid), ('pid', ctypes.c_ulong)]

    class Value(ctypes.Structure):
        _fields_ = [('vt', ctypes.c_ushort), ('reserved', ctypes.c_ushort * 3),
                    ('text', ctypes.c_void_p), ('padding', ctypes.c_void_p)]

    def call(ptr, index, argtypes, *args):
        table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        function = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
        result = function(ptr, *args)
        if result < 0:
            raise OSError('notification_shortcut_failed')

    def query(ptr, iid):
        result = ctypes.c_void_p()
        call(ptr, 0, [ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(Guid(iid)), ctypes.byref(result))
        return result

    ole = ctypes.OleDLL('ole32')
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(Guid), ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)]
    link, persist, properties = ctypes.c_void_p(), None, None
    try:
        ole.CoCreateInstance(ctypes.byref(Guid('00021401-0000-0000-C000-000000000046')), None, 1,
                             ctypes.byref(Guid('000214F9-0000-0000-C000-000000000046')), ctypes.byref(link))
        persist = query(link, '0000010b-0000-0000-C000-000000000046')
        call(persist, 5, [ctypes.c_wchar_p, ctypes.c_ulong], str(link_path), 2)  # STGM_READWRITE
        target = ctypes.create_unicode_buffer(32768)
        call(link, 3, [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong], target, len(target), None, 4)
        if os.path.normcase(os.path.abspath(target.value)) != os.path.normcase(str(launcher)):
            raise OSError('notification_shortcut_foreign')
        properties = query(link, '886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99')
        key = Key(Guid('9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3'), 5)
        current = Value()
        call(properties, 5, [ctypes.POINTER(Key), ctypes.POINTER(Value)], ctypes.byref(key), ctypes.byref(current))
        try:
            app_id = ctypes.wstring_at(current.text) if current.vt == 31 and current.text else ''
        finally:
            ole.PropVariantClear(ctypes.byref(current))
        if app_id and app_id != APP_ID:
            raise OSError('notification_shortcut_foreign')
        if app_id == APP_ID:
            return
        text = ctypes.create_unicode_buffer(APP_ID)
        value = Value(31, (ctypes.c_ushort * 3)(), ctypes.cast(text, ctypes.c_void_p), None)
        call(properties, 6, [ctypes.POINTER(Key), ctypes.POINTER(Value)], ctypes.byref(key), ctypes.byref(value))
        call(properties, 7, [])
        call(link, 17, [ctypes.c_wchar_p, ctypes.c_int], str(launcher), 0)
        call(persist, 6, [ctypes.c_wchar_p, ctypes.c_int], str(link_path), 1)
    finally:
        for ptr in (properties, persist, link):
            if ptr:
                # IUnknown::Release returns ULONG; its value is not an HRESULT.
                table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(ptr)


class WindowsToast:
    def __init__(self, root, language=resolve_language):
        self.root = root
        self.language = language
        self.notifier = None

    def prepare(self):
        if self.notifier is None:
            repair_shortcut(self.root)
            from winrt.windows.ui.notifications import ToastNotificationManager
            self.notifier = ToastNotificationManager.create_toast_notifier_with_id(APP_ID)
        return self.notifier

    def show(self):
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import NotificationSetting, ToastNotification
        notifier = self.prepare()
        try:
            if notifier.setting != NotificationSetting.ENABLED:
                return 'disabled'
        except OSError as exc:
            # On a brand-new AUMID Windows has no notification-settings row yet:
            # Setting returns ERROR_NOT_FOUND until the first Show creates it.
            # Show still enforces OS notification policy; never change that policy.
            if getattr(exc, 'winerror', 0) & 0xffffffff != 0x80070490:
                raise
        document = XmlDocument()
        document.load_xml(TOAST_XML.replace('새 메시지가 도착했어요.', escape(translate('새 메시지가 도착했어요.', self.language()))))
        toast = ToastNotification(document)
        toast.tag, toast.group = TOAST_TAG, TOAST_GROUP
        toast.expiration_time = datetime.now(timezone.utc) + timedelta(days=1)
        notifier.show(toast)
        return 'sent'  # API submitted; not a statement about display or reading.

    def clear(self):
        from winrt.windows.ui.notifications import ToastNotificationManager
        ToastNotificationManager.history.remove_group_with_id(TOAST_GROUP, APP_ID)
