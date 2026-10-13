"""Explicitly authorized ONE-send test through the real Qt UI and native worker.

The reviewed plan and irreversible attempt marker remain in research/private.
An attempted plan can never be reused, even when the result is unknown.
"""
import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import time
from uuid import uuid4

from bongo_chat.environment import running_game


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execute-authorized-once", action="store_true", required=True)
    parser.add_argument("--observe-seconds", type=int, default=15)
    args = parser.parse_args()
    private = Path(__file__).resolve().parents[1] / "research" / "private"
    plan_path = args.plan.resolve()
    if not plan_path.is_relative_to(private.resolve()):
        parser.error("The reviewed plan must be inside research/private")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    from bongo_chat.protocol import encode
    encode(plan["text"])
    if plan["count"] != 1 or not 5 <= args.observe_seconds <= 120:
        parser.error("Unexpected authorization scope")
    marker = plan_path.with_suffix(".attempted.json")
    if marker.exists():
        parser.error("This plan was already attempted. Retrying is forbidden.")

    def check_process():
        game = running_game()
        if game.pid != plan["pid"] or game.created != plan["created"]:
            raise RuntimeError("planned_game_process_changed")
        return game

    check_process()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    from PySide6.QtWidgets import QApplication
    from bongo_chat.desktop import Controller, window

    class OneShotController(Controller):
        sends = 0

        def dispatch(self, request):
            if request.get("action") == "send":
                check_process()
                current = self.service.context()
                if (self.sends or request.get("text") != plan["text"]
                        or current["account"] != plan["account"]
                        or current["lobby"] != plan["lobby"]
                        or request.get("context") != current):
                    raise ValueError("connection_changed")
                # Consume authorization BEFORE queuing. No exception can permit retry.
                with marker.open("x", encoding="utf-8") as stream:
                    json.dump({"attempted": time.time(), "count": 1}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                self.sends += 1
            return super().dispatch(request)

    app = QApplication([])
    data = plan_path.parent / ("live-ui-" + uuid4().hex)
    data.mkdir()
    controller = OneShotController(data)
    view = window(controller)
    view.show()
    page = view.page()

    def wait_for(predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False

    def js(code):
        result = []
        page.runJavaScript(code, lambda value: result.append(value))
        if not wait_for(lambda: bool(result), 10):
            raise RuntimeError("renderer_timeout")
        return result[0]

    def matching_rows():
        return controller.store.db.execute(
            "SELECT status,echo FROM messages WHERE own=1 AND body=?", (plan["text"],)
        ).fetchall()

    report = {"ui_send_attempts": 0, "api_status": "not_attempted", "self_echo": False,
              "peer_screen": "unverified", "game_files_modified": False,
              "lobby_mutations": 0, "process_writes": 0, "automatic_retries": 0}
    try:
        if not wait_for(lambda: controller.service.can_send(), 180):
            raise RuntimeError("ready_timeout")
        current = controller.service.context()
        if current["account"] != plan["account"] or current["lobby"] != plan["lobby"]:
            raise RuntimeError("planned_destination_changed")
        check_process()
        if not wait_for(lambda: js("!document.querySelector('#message-input').disabled && document.querySelector('#connection-label').textContent.includes('게임과 연결됨')"), 10):
            raise RuntimeError("renderer_not_ready")
        js("document.querySelector('#message-input').value=" + json.dumps(plan["text"])
           + ";document.querySelector('#message-input').dispatchEvent(new Event('input'))")
        if not wait_for(lambda: js("!document.querySelector('#send-button').disabled"), 5):
            raise RuntimeError("send_control_disabled")
        js("document.querySelector('#send-button').click()")  # Exactly one UI action.
        wait_for(lambda: False, args.observe_seconds)
        rows = matching_rows()
        report.update(ui_send_attempts=controller.sends,
                      matching_own_rows=len(rows),
                      api_status=rows[0][0] if rows else "unknown",
                      self_echo=bool(rows and rows[0][1]),
                      sqlite_saved=bool(rows),
                      same_game_process=check_process().alive(),
                      same_lobby=controller.service.context()["lobby"] == plan["lobby"],
                      renderer_console_error_count=len(page.console_errors))
        report["peer_messages_saved"] = controller.store.db.execute("SELECT count(*) FROM messages WHERE own=0").fetchone()[0]
        report["peer_meow_reply_count"] = controller.store.db.execute("SELECT count(*) FROM messages WHERE own=0 AND instr(body,'야옹야옹')>0").fetchone()[0]
        report["ui_peer_message_count"] = js("document.querySelectorAll('.message:not(.is-own) .message-bubble').length")
        report["ui_own_message_visible"] = bool(js(
            "Array.from(document.querySelectorAll('.message.is-own .message-bubble')).some(e=>e.textContent==="
            + json.dumps(plan["text"]) + ")"))
        # Private database is reopened below; no other users' text is printed.
    except Exception as exc:
        code = str(exc)
        report["error"] = code if code.isascii() and code.replace("_", "").isalnum() else "test_unavailable"
        report["ui_send_attempts"] = controller.sends
    finally:
        view.close()
        controller.close()
        view.deleteLater()
        app.processEvents()
        import sqlite3
        with sqlite3.connect(data / "history.sqlite3") as db:
            report["reopened_search_count"] = db.execute(
                "SELECT count(*) FROM messages WHERE own=1 AND instr(body,?)>0", (plan["text"],)
            ).fetchone()[0]
        report["game_still_running_after_shutdown"] = check_process().alive()
        plan_path.with_suffix(".result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["ui_send_attempts"] == 1 and report["api_status"] == "accepted" and report["self_echo"] else 2


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
