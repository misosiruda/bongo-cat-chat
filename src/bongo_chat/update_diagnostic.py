"""Explicit installed updater diagnostics; no Steam worker or trust overrides."""
import os
import time

from PySide6.QtCore import QTimer

from . import __version__
from .exit_codes import UPDATE_DIAGNOSTIC_FAILED
from .updates import atomic_json


def observe_update(app, controller, view, directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{__version__}-{os.getpid()}.json'
    started = time.monotonic()
    report = {'version': __version__, 'pid': os.getpid(), 'steam_connected': False,
              'worker_started': controller.worker is not None, 'events': [], 'renderer': False}
    timer = QTimer(view)
    previous = [None]

    def save():
        report['console_errors'] = view.page().console_errors
        atomic_json(path, report)

    def inspect():
        state = controller.updates.snapshot()['state']
        if previous[0] != state:
            report['events'].append({'state': state, 'elapsed': round(time.monotonic()-started, 3)})
            previous[0] = state
            save()
        if not report['renderer']:
            def rendered(value):
                report['renderer'] = bool(value)
                save()
            view.page().runJavaScript("document.querySelector('#connection-notice')?.textContent.includes('오프라인')", rendered)
        if report['renderer'] and state in {'current', 'disabled', 'verification_failed', 'network_error', 'unavailable'}:
            report['complete'] = state == 'current' and not view.page().console_errors
            save()
            timer.stop()
            app.exit(0 if report['complete'] else UPDATE_DIAGNOSTIC_FAILED)
        elif time.monotonic()-started > 1800:
            report['complete'] = False
            report['timeout'] = True
            save()
            timer.stop()
            app.exit(UPDATE_DIAGNOSTIC_FAILED)

    def shutdown():
        timer.stop()
        report['restart_requested'] = controller.restarting
        report['shutdown_elapsed'] = round(time.monotonic()-started, 3)
        save()

    app.aboutToQuit.connect(shutdown)
    timer.timeout.connect(inspect)
    timer.start(250)
