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


@pytest.mark.parametrize('error,fragment',[
    ('unsupported_game_files','런타임 또는 연결 모듈'),
    ('unsupported_automation_features','상자·합성·인벤토리 기능'),
    ('automation_probe_failed','호환성을 확인하지 못했습니다'),
    ('automation_files_changed','검사 도중 게임 파일이 바뀌었거나'),
    ('merge_game_files_missing','게임 파일이 없습니다'),
    ('merge_game_files_unreadable','게임 파일을 읽지 못했습니다'),
    ('bridge_response_pending','게임 창이 최소화되어 있으면'),
    ('attach_not_confirmed_no_retry','연결 모듈의 로드·초기화'),
    ('bridge_session_unavailable','원인 확인이 필요'),
    ('prior_bridge_active','이미 로드된 연결 모듈'),
    ('bridge_client_in_use','다른 앱이 상자·합성'),
    ('process_access_failed','실행 권한'),
    ('merge_compiler_missing','Windows .NET Framework'),
    ('merge_prepare_failed','연결 모듈을 준비하지 못했습니다'),
    ('bridge_assets_missing','게임 연결 파일이 없거나 올바르지 않습니다'),
    ('bridge_binary_changed','무결성을 확인하지 못했습니다'),
    ('bridge_path_unsupported','다른 위치로 연결된 경로'),
    ('bridge_storage_access_denied','접근이 거부됐습니다'),
    ('bridge_storage_full','디스크 공간이 부족합니다'),
    ('bridge_storage_conflict','이미 파일이나 폴더가 있습니다'),
    ('bridge_storage_failed','폴더·파일을 처리하지 못했습니다'),
    ('bridge_storage_security_failed','접근 권한 보호를 설정하지 못했습니다'),
    ('bridge_module_scan_failed','모듈 목록이나 상태를 검사하지 못했습니다'),
    ('bridge_session_incompatible','현재 앱과 호환되지 않습니다'),
    ('bridge_session_closed','연결 모듈이 종료되어'),
    ('bridge_session_invalid','필요한 정보가 없거나'),
    ('bridge_response_unreadable','응답 파일을 읽지 못했습니다'),
    ('bridge_response_invalid','대상 정보가 예상과 다릅니다'),
    ('bridge_reconnect_failed','재연결 확인 응답을 받지 못했습니다'),
    ('bridge_stop_unconfirmed','이전 자동 개봉의 중지'),
    ('bridge_target_changed','실행 대상이 바뀌었습니다'),
    ('bridge_target_unverified','실행 중인 게임을 확인하지 못했습니다'),
    ('bridge_connection_failed','원인을 분류하지 못한 오류'),
    ('game_missing_or_ambiguous','Bongo Cat 하나를 확인하지 못했습니다'),
])
def test_file_compatibility_errors_reach_renderer_without_enabling_start(qt_chat,error,fragment):
    app,controller,page=qt_chat
    def failure():raise RuntimeError(error)
    manager=MergeConnection(failure)
    controller.merge_connection=manager
    controller.merger=AutoMerge(manager)
    try:
        js(app,page,"document.querySelector('#merge-open').click()")
        wait_until(app,lambda:js(app,page,"!document.querySelector('#merge-connection').hidden"))
        js(app,page,"document.querySelector('#merge-connect').click()")
        wait_until(app,lambda:fragment in js(app,page,"document.querySelector('#merge-connection-message').textContent"))
        assert manager.connection_snapshot()['error']==error
        assert error in js(app,page,"document.querySelector('#merge-connection-message').textContent")
        assert js(app,page,"document.querySelector('#merge-start').disabled && document.querySelector('#merge-maximum').disabled")
        assert not controller.merger.active
        js(app,page,"document.querySelector('#merge-dialog').close();document.querySelector('#chest-open').click()")
        wait_until(app,lambda:fragment in js(app,page,"document.querySelector('#chest-connection-message').textContent"))
        assert error in js(app,page,"document.querySelector('#chest-connection-message').textContent")
        assert js(app,page,"document.querySelector('#chest-start').disabled")
        message = js(app,page,"document.querySelector('#chest-connection-message').textContent")
        restart_required = error in {'automation_files_changed', 'prior_bridge_active', 'attach_not_confirmed_no_retry',
                                    'bridge_session_incompatible', 'bridge_session_closed', 'bridge_stop_unconfirmed'}
        assert ('한 번 완전히 종료' in message) == restart_required
        assert '다시 실행' not in message
        if error == 'bridge_response_pending':
            controller.dispatch(dict(action='setting',key='language',value='en'))
            wait_until(app,lambda:'If the game window is minimized' in js(app,page,"document.querySelector('#chest-connection-message').textContent"))
    finally:manager.close()


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
