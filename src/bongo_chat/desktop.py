"""Qt WebEngine desktop shell with a narrow local bridge and private worker IPC."""
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sqlite3
import sys
import time

from PySide6.QtCore import QObject, QLockFile, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog, QVBoxLayout, QTextBrowser

from .service import ChatService
from .store import Store
from .worker import run_worker, unavailable
from . import __version__
from .exit_codes import PROFILE_IN_USE, RESTART_FOR_UPDATE, RESTART_CAPABILITY
from .updates import UpdateManager
from .privacy import update_checks_allowed, set_update_checks_allowed

UI = Path(__file__).with_name("ui").resolve()
LEGAL = Path(__file__).with_name('legal')
SOURCE_ROOT = Path(__file__).resolve().parents[2]


def legal_document(document):
    names = {'privacy': 'PRIVACY.md', 'licenses': 'THIRD-PARTY-NOTICES.txt',
             'chromium': 'CHROMIUM-LICENSES.html', 'sources': 'SOURCES.md'}
    name = names.get(document)
    if name is None:
        raise ValueError('invalid_document')
    try:
        path = LEGAL / name
        if not getattr(sys, 'frozen', False) and not path.is_file():
            # Source runs have no assembled distribution. Show the checked-in
            # policy/review instead; frozen copies must use their own notices.
            sources = {'privacy': 'docs/privacy-policy.md', 'licenses': 'docs/license-review.md',
                       'chromium': 'packaging/licenses/CHROMIUM-LICENSES.html',
                       'sources': 'docs/licensing/SOURCES.md'}
            path = SOURCE_ROOT / sources[document]
            if document == 'licenses':
                return name, ('소스 실행 환경: 자체 라이선스와 의존성 검토 안내입니다.\n'
                              '배포물의 전체 고지는 tools/collect_license_notices.py로 생성합니다.\n\n'
                              + (SOURCE_ROOT / 'LICENSE').read_text(encoding='utf-8')
                              + '\n\n' + path.read_text(encoding='utf-8'))
        return name, path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        raise ValueError('legal_unavailable') from None


class Requests(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        if url.scheme() == "file":
            allowed = Path(url.toLocalFile()).resolve() in {
                UI / name for name in ("index.html", "app.js", "messenger.css", "app-icon.png", "favicon.ico")
            }
        else:
            allowed = url.toString() == "qrc:///qtwebchannel/qwebchannel.js" or url.scheme() == "data"
        info.block(not allowed)


class Page(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)
        self.console_errors = []

    def acceptNavigationRequest(self, url, kind, main_frame):
        return main_frame and url.isLocalFile() and Path(url.toLocalFile()).resolve() == UI / "index.html"

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            # Kept in process for test diagnostics, not written to disk.
            self.console_errors.append((str(level), line, message[:300]))


class Controller(QObject):
    restart_requested = Signal()

    def __init__(self, data, offline=False, read_only=False, parent=None, install_root=None, update_smoke=False):
        super().__init__(parent)
        self.store = Store(data / "history.sqlite3")
        self.service = ChatService(self.store)
        if update_smoke and (not offline or not install_root):
            raise ValueError('update_diagnostic_requires_offline_installation')
        self.updates = UpdateManager(install_root, __version__, offline and not update_smoke, allowed=update_checks_allowed())
        self.legal_dialogs = []
        self.worker = None
        self.closed = False
        self.restarting = False
        self.restart_supported = bool(install_root and (not offline or update_smoke)
                                      and os.environ.get(RESTART_CAPABILITY) == '1')
        self.context = mp.get_context("spawn")
        self.commands = self.context.Queue(maxsize=64)
        self.events = self.context.Queue(maxsize=2048)
        self.stop = self.context.Event()
        self.last_prune = time.monotonic()
        self.known_accounts = set()
        self.unsupported_fingerprint = None
        if offline:
            self.service.update(unavailable("offline"))
        else:
            self.worker = self.context.Process(target=run_worker, args=(self.commands,self.events,self.stop,read_only), daemon=True)
            self.worker.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)

    def poll(self):
        try:
            self.updates.poll()
            for _ in range(200):
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                if event.get("type") == "state":
                    if event.get("notice") == "unsupported_game_build" and not self.closed:
                        fingerprint = event.get("build_fingerprint", "unknown")
                        if fingerprint != self.unsupported_fingerprint:
                            self.unsupported_fingerprint = fingerprint
                            self.updates.request()
                    if event.get("account"):
                        self.known_accounts.add(event["account"])
                    self.service.update(event)
                elif event.get("type") == "message":
                    self.service.receive(event)
                elif event.get("type") == "result":
                    self.service.result(event["id"], event["status"])
            if self.worker and not self.worker.is_alive() and self.service.state.get("notice") != "worker_stopped":
                self.service.update(unavailable("worker_stopped"))
            if time.monotonic()-self.last_prune > 60:
                self.service.write(self.store.prune)
                self.last_prune = time.monotonic()
        except (sqlite3.Error, OSError):
            self.service.storage_error = True

    @Slot(str, result=str)
    def request(self, raw):
        try:
            if len(raw) > 32768:
                raise ValueError("request_too_large")
            args = json.loads(raw)
            result = self.dispatch(args)
            return json.dumps(result, ensure_ascii=False)
        except (sqlite3.Error, OSError):
            self.service.storage_error = True
            return json.dumps({"error": "storage_failed"})
        except (ValueError, TypeError, KeyError, queue.Full) as exc:
            # Don't return native exception messages or paths through the renderer.
            code = str(exc)
            if code not in {"connection_changed", "development_limit_50", "control_character", "storage_failed_before_send", "legal_unavailable"}:
                code = "request_failed"
            return json.dumps({"error": code})

    def dispatch(self, args):
        action = args["action"]
        account = self.service.state.get("account", "")
        if action == "view":
            lobby = args.get("lobby") if args.get("account", account) == account else None
            query = args.get("query", "")
            before = args.get("before")
            start, seen, limit = args.get('start'), args.get('seen'), args.get('limit', 100)
            if (not isinstance(query, str) or len(query) > 120
                    or any(value is not None and (type(value) is not int or value < 0) for value in (before, start, seen))
                    or before is not None and start is not None
                    or type(limit) is not int or not 1 <= limit <= 1000):
                raise ValueError("invalid_query")
            result = self.service.view(lobby, query, before, start, seen, limit)
            result['update'] = self.updates.snapshot()
            result['update']['can_restart'] = self.can_restart()
            return result
        if action == "send":
            if self.restarting:
                raise ValueError('restart_in_progress')
            command = self.service.prepare(args["context"], args["text"])
            command["queued"] = time.monotonic()
            try:
                self.commands.put_nowait(command)
            except queue.Full:
                self.service.result(command["id"], "failed")
                raise
            return {"id": command["id"]}
        if action == "draft":
            owner = args["account"]
            if not owner or owner not in self.known_accounts | {account} or args["lobby"] not in {r["lobby"] for r in self.store.rooms(owner)}:
                raise ValueError("account_changed")
            self.store.draft(owner, args["lobby"], args["text"])
        elif action == "setting":
            key, value = args["key"], args["value"]
            if not (key == "theme" and value in ("light", "dark", "system") or key == "collapsed" and type(value) is bool):
                raise ValueError("invalid_setting")
            self.store.setting(key, value)
        elif action == "delete":
            if not account or args["account"] != account:
                raise ValueError("account_changed")
            self.service.forget(account, args.get("lobby"))
        elif action == "refresh":
            try:
                self.service.recover_storage()
            except (sqlite3.Error, OSError):
                self.service.storage_error = True
            if self.worker and self.worker.is_alive():
                self.commands.put_nowait({"type": "refresh"})
        elif action == 'check_updates':
            self.updates.request()
        elif action == 'restart_update':
            if not self.can_restart():
                return {'ok': False, 'reason': 'unavailable'}
            if self.service.storage_error or self.service.volatile:
                return {'ok': False, 'reason': 'storage'}
            if any(item.get('status', 'pending') == 'pending' for item in self.service.pending):
                return {'ok': False, 'reason': 'sending'}
            if not self.restarting:
                self.restarting = True
                QTimer.singleShot(0, self.restart_requested.emit)
            return {'ok': True}
        elif action == 'update_permission':
            try:
                set_update_checks_allowed(args['allowed'])
            except OSError:
                return {'error': 'update_permission_failed'}
            self.updates.set_allowed(args['allowed'])
        elif action == 'legal':
            name, text = legal_document(args.get('document'))
            dialog = QDialog()
            dialog.setWindowTitle('개인정보 및 오픈소스 안내')
            dialog.resize(760, 620)
            layout = QVBoxLayout(dialog)
            viewer = QTextBrowser(dialog)
            viewer.setOpenLinks(False)
            viewer.setOpenExternalLinks(False)
            if name.endswith('.html'):
                viewer.setHtml(text)
            else:
                viewer.setPlainText(text)
            layout.addWidget(viewer)
            self.legal_dialogs.append(dialog)
            dialog.finished.connect(lambda: self.legal_dialogs.remove(dialog))
            dialog.show()
        else:
            raise ValueError("unknown_action")
        return {"ok": True}

    def can_restart(self):
        return (self.restart_supported and not self.closed and self.updates.enabled
                and self.updates.snapshot()['state'] == 'ready')

    def close(self):
        if self.closed:
            return
        self.closed = True
        for dialog in list(self.legal_dialogs):
            dialog.close()
        self.timer.stop()
        self.updates.close()
        self.stop.set()
        if self.worker:
            self.worker.join(3)
            if self.worker.is_alive():
                self.worker.terminate()  # Only this app's own child, never the game.
                self.worker.join(2)
        self.poll()
        self.service.end("app_closed")
        self.store.close()
        for pipe in (self.commands, self.events):
            pipe.cancel_join_thread()
            pipe.close()


def window(controller):
    view = QWebEngineView()
    profile = QWebEngineProfile(view)  # Off-the-record: renderer never persists chat/cache.
    interceptor = Requests(profile)
    profile.setUrlRequestInterceptor(interceptor)
    profile.downloadRequested.connect(lambda download: download.cancel())
    page = Page(profile, view)
    view.setPage(page)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
    channel = QWebChannel(page)
    channel.registerObject("bridge", controller)
    page.setWebChannel(channel)
    view.setWindowTitle("Bongo Cat Chat · 개발판")
    view.setWindowIcon(QIcon(str(UI / "app-icon.ico")))
    view.resize(1240, 840)
    view.setMinimumSize(400, 500)
    view.load(QUrl.fromLocalFile(str(UI / "index.html")))
    view._resources = (profile, interceptor, page, channel)
    return view


def run(data, offline=False, read_only=False, smoke_report=None, connection_report=None, install_root=None, update_smoke_dir=None):
    app = QApplication.instance() or QApplication([])
    app.setWindowIcon(QIcon(str(UI / "app-icon.ico")))
    data.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        if smoke_report:
            smoke_report.parent.mkdir(parents=True, exist_ok=True)
            smoke_report.write_text(json.dumps({"startup_error": "profile_in_use", "version": __version__,
                                                "offline": offline}), encoding="utf-8")
        else:
            QMessageBox.information(None, "Bongo Cat Chat", "이미 실행 중인 앱이 있습니다.")
        return PROFILE_IN_USE
    try:
        controller = Controller(data, offline, read_only, install_root=install_root, update_smoke=bool(update_smoke_dir))
    except (sqlite3.Error, OSError, RuntimeError):
        QMessageBox.critical(None, "Bongo Cat Chat", "기록 저장소를 열 수 없습니다. 기존 파일은 보존했습니다.")
        return 1
    view = window(controller)
    if smoke_report or connection_report:
        controller.restart_supported = False
    controller.restart_requested.connect(lambda: app.exit(RESTART_FOR_UPDATE))
    app.aboutToQuit.connect(controller.close)
    view.show()
    if update_smoke_dir:
        from .update_diagnostic import observe_update
        observe_update(app, controller, view, update_smoke_dir)
    if smoke_report:
        def finish():
            def report(result):
                payload = {"renderer": result, "console_errors": view.page().console_errors,
                           "steam_connected": False, "offline": True, "version": __version__}
                smoke_report.parent.mkdir(parents=True, exist_ok=True)
                smoke_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                app.exit(0 if result and not view.page().console_errors else 2)
            view.page().runJavaScript("document.querySelector('#connection-notice')?.textContent.includes('오프라인') && document.querySelector('#send-button')?.disabled", report)
        QTimer.singleShot(4000, finish)
    if connection_report:
        started, ready_since = time.monotonic(), [None]
        diagnostic = QTimer(view)

        def inspect_connection():
            state = controller.service.state
            ready = state.get("state") == "ready" and controller.service.fresh()
            if ready and ready_since[0] is None:
                ready_since[0] = time.monotonic()
            if not ready:
                ready_since[0] = None
            avatar_count = sum(bool(p.get("avatar")) for p in state.get("profiles", {}).values())
            duration = time.monotonic()-ready_since[0] if ready_since[0] is not None else 0
            observing = ready_since[0] is None or duration < 15 or (duration < 45 and not avatar_count and not state.get("avatar_error"))
            if time.monotonic() - started < 180 and observing:
                return
            diagnostic.stop()
            payload = {"ready": ready, "state": state.get("state"), "notice": state.get("notice"),
                       "read_only": read_only, "send_enabled": controller.service.can_send(),
                       "profile_count": len(state.get("profiles", {})),
                       "rendered_avatar_count": avatar_count,
                       "avatar_stage": state.get("avatar_stage"), "avatar_error": state.get("avatar_error"),
                       "stored_messages": controller.store.db.execute("SELECT count(*) FROM messages").fetchone()[0],
                       "console_error_count": len(view.page().console_errors)}

            def report(result):
                payload["renderer_read_only"] = bool(result)
                connection_report.parent.mkdir(parents=True, exist_ok=True)
                connection_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                app.exit(0 if ready and result and not payload["send_enabled"] and not payload["console_error_count"] else 2)

            view.page().runJavaScript("document.querySelector('#connection-notice')?.textContent.includes('읽기 전용') && document.querySelector('#send-button')?.disabled", report)

        diagnostic.timeout.connect(inspect_connection)
        diagnostic.start(500)
    result = app.exec()
    lock.unlock()
    return result
