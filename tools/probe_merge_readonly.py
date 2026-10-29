"""Explicit local UI acceptance probe. Refuses every consuming/selection command.

Uses the real Qt panel and real game counts, with an isolated offline chat profile.
It may install/connect the approved module, change its group, and read counts only.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtWidgets import QApplication
from bongo_chat.auto_merge import AutoMerge
from bongo_chat.desktop import Controller, window
from bongo_chat.merge_bridge import BridgeChannel
from bongo_chat.merge_connection import MergeConnection


def wait(app, predicate, seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return
        time.sleep(.02)
    raise RuntimeError('UI verification timed out')


def javascript(app,page,code):
    results=[]
    page.runJavaScript(code,lambda value:results.append(value))
    wait(app,lambda:bool(results))
    return results[0]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--connect-readonly',required=True,action='store_true')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    profile=output/'offline-profile';profile.mkdir(exist_ok=True)
    request=BridgeChannel.request
    commands=[]
    def readonly(channel, op, **kwargs):
        if op not in {'group','snapshot'}:
            raise AssertionError('read-only probe refuses '+op)
        commands.append(op)
        return request(channel,op,**kwargs)
    BridgeChannel.request=readonly
    app=QApplication([])
    controller=Controller(profile,offline=True)
    connection=MergeConnection()
    controller.merge_connection=connection
    controller.merger=AutoMerge(connection)
    view=window(controller);view.show();page=view.page()
    j=lambda code:javascript(app,page,code)
    try:
        wait(app,lambda:j("document.querySelector('#merge-open') !== null"))
        j("document.querySelector('#merge-open').click()")
        wait(app,lambda:j("!document.querySelector('#merge-connection').hidden"))
        view.grab().save(str(output/'disconnected.png'))
        j("document.querySelector('#merge-connect').click()")
        wait(app,lambda:connection.state in {'connected','error'})
        if connection.state!='connected':raise RuntimeError(connection.error)
        wait(app,lambda:j("!document.querySelector('#merge-maximum').disabled"))
        results={}
        for group in ('cosmetics','emotes'):
            j("document.querySelector('#merge-target-group').value="+json.dumps(group)+";document.querySelector('#merge-target-group').dispatchEvent(new Event('change'))")
            wait(app,lambda:connection.observe().category==group and j("document.querySelector('#merge-target-group').value")==group and not j("document.querySelector('#merge-maximum').disabled"))
            j("document.querySelector('#merge-maximum').click()")
            wait(app,lambda:float(j("document.querySelector('#merge-limit').value"))>0)
            results[group]=dict(available=int(j("document.querySelector('#merge-limit').value")),
                               favorites=j("document.querySelector('#merge-favorites').textContent"),
                               events=j("document.querySelector('#merge-events').textContent"))
            view.grab().save(str(output/(group+'.png')))
        # Reconnect to the same module: neither reinstallation nor automatic start.
        epoch=connection.observe().target
        previous_thread=connection.thread
        j("document.querySelector('#merge-connect').click()")
        wait(app,lambda:connection.thread is not previous_thread)
        wait(app,lambda:connection.state=='connected' and connection.observe().ready)
        wait(app,lambda:j("document.querySelector('#merge-connection-title').textContent")=='게임 연결됨' and not j("document.querySelector('#merge-maximum').disabled"))
        assert connection.observe().target==epoch and not controller.merger.active
        raw=connection.adapter.channel.snapshot()
        assert raw['spent']==0 and raw['test_budget']==0 and raw['selected_units']==0
        assert not raw['pending_attempt'] and not raw['run_attempt']
        view.resize(400,500)
        for _ in range(20):app.processEvents();time.sleep(.02)
        j("document.querySelector('#merge-available').scrollIntoView({block:'center'})")
        for _ in range(10):app.processEvents();time.sleep(.02)
        view.grab().save(str(output/'narrow.png'))
        overflow=j("document.documentElement.scrollWidth>innerWidth || document.querySelector('.merge-content').scrollWidth>document.querySelector('.merge-content').clientWidth")
        assert not overflow and not page.console_errors
        report=dict(groups=results,commands=commands,spent=raw['spent'],authorized_total=raw['test_budget'],
                    selected_units=raw['selected_units'],console_errors=page.console_errors,overflow=overflow,
                    same_session_reconnected=True,chat='offline isolated profile')
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        view.close();controller.close();view.deleteLater();app.processEvents()


if __name__=='__main__':main()
