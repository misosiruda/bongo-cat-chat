"""Product connection and UI tests use fake game IPC, never the real game."""
import json
import os
import threading
import time

import pytest

from bongo_chat.auto_merge import AutoMerge
from bongo_chat.merge_bridge import BridgeChannel
from bongo_chat.merge_connection import InteractiveAdapter, MergeConnection
from test_merge_bridge import FileServer, until
from test_desktop import qt_chat, js, wait_until


def connected(path):
    return InteractiveAdapter(channel=BridgeChannel(path,verify_target=lambda config:None))


@pytest.mark.skipif(os.name!='nt',reason='Windows locks')
def test_interactive_requires_explicit_start_and_reopens_without_resuming(tmp_path):
    server = FileServer(tmp_path,interactive=True)
    manager = MergeConnection(lambda:connected(tmp_path))
    runner = AutoMerge(manager)
    try:
        assert not server.requests and not manager.adapter
        assert manager.connect()
        until(lambda:manager.observe().ready)
        assert runner.maximum()==180 and not server.requests
        assert runner.start(3)
        def done():runner.tick();return not runner.active
        until(done)
        assert runner.state=='completed' and runner.completed==3
        assert [r['op'] for r in server.requests]==['begin','select','merge','select','merge','select','merge']
        assert server.state['spent']==server.state['test_budget']==3
        runner.close()
        manager = MergeConnection(lambda:connected(tmp_path))
        runner = AutoMerge(manager)
        assert manager.connect()
        until(lambda:manager.observe().ready)
        runner.tick()
        assert runner.state=='idle' and not runner.active and server.state['spent']==3
        assert runner.start(1)
        until(done)
        assert runner.completed==1 and server.state['spent']==4
    finally:runner.close();server.close()


def test_connection_errors_are_bounded_and_close_during_connect_does_not_publish():
    def failure():raise RuntimeError('secret local path')
    manager = MergeConnection(failure)
    assert manager.connect()
    until(lambda:manager.state=='error')
    assert manager.connection_snapshot()['error']=='bridge_connection_failed'
    manager.close()
    gate=threading.Event()
    class Dummy:
        closed=False
        def close(self):self.closed=True
    dummy=Dummy()
    def slow():gate.wait(2);return dummy
    manager=MergeConnection(slow)
    assert manager.connect() and not manager.connect()
    manager.close();gate.set();manager.thread.join(2)
    assert dummy.closed and manager.adapter is None and not manager.connect()


def test_real_renderer_connect_maximum_start_and_completion(qt_chat,tmp_path):
    app,controller,page=qt_chat
    server=FileServer(tmp_path,interactive=True)
    manager=MergeConnection(lambda:connected(tmp_path))
    controller.merge_connection=manager
    controller.merger=AutoMerge(manager)
    try:
        js(app,page,"document.querySelector('#merge-open').click()")
        wait_until(app,lambda:js(app,page,"!document.querySelector('#merge-connection').hidden"))
        assert not server.requests
        js(app,page,"document.querySelector('#merge-connect').click()")
        wait_until(app,lambda:js(app,page,"!document.querySelector('#merge-maximum').disabled"))
        assert js(app,page,"document.querySelector('#merge-connection-title').textContent")=='게임 연결됨'
        js(app,page,"document.querySelector('#merge-maximum').click()")
        wait_until(app,lambda:js(app,page,"document.querySelector('#merge-limit').value")=='180')
        assert not server.requests
        js(app,page,"document.querySelector('#merge-limit').value='3';document.querySelector('#merge-limit').dispatchEvent(new Event('input'));document.querySelector('#merge-start').click()")
        wait_until(app,lambda:controller.merger.completed==3 and not controller.merger.active,seconds=8)
        assert server.state['spent']==3 and all(r['count']==1 for r in server.requests if r['op']=='merge')
        assert not controller.merger.unresolved
    finally:manager.close();server.close()
