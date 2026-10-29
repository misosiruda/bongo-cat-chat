"""File IPC and the actual async adapter, with a synthetic server; no game calls."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time

import pytest

from bongo_chat.auto_merge import AutoMerge
from bongo_chat.merge_bridge import BridgeAdapter, BridgeChannel, observation


def raw_snapshot():
    return dict(protocol=1,epoch='a'*32,pid=42,captured_utc_ms=int(time.time()*1000),generation=1,
        group='cosmetics',available_group='cosmetics',ready=True,reason='ready',favorites_allowed=False,
        events_excluded=True,selected_units=0,exchanges=0,selection='',selection_attempt='',
        can_select=True,exchanging=False,available_exchanges=180,receipt=None,pending_attempt='',
        spent=0,test_budget=2,per_request_limit=1)


class FileServer:
    def __init__(self,path,interactive=False):
        self.path=path;self.state=raw_snapshot();self.requests=[];self.seen=set();self.pending=None
        self.stopping=threading.Event()
        helper=b'synthetic helper, never loaded'
        (path/('BongoCatChat.MergeBridge.Live.dll' if interactive else 'BongoCatChat.MergeBridge.Shared.dll')).write_bytes(helper)
        config=dict(protocol=1,epoch='a'*32,token='b'*64,pid=42,process_start_ticks=1,test_budget=2,
                    helper_sha256=hashlib.sha256(helper).hexdigest())
        if interactive:
            config.update(mode='interactive',test_budget=0)
            self.state.update(mode='interactive',test_budget=0,run_attempt='',command_sequence=0)
        (path/'session.json').write_text(json.dumps(config))
        self.publish()
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def write(self,name,value):
        temp=self.path/(name+'.server.tmp');temp.write_text(json.dumps(value));os.replace(temp,self.path/name)

    def publish(self):
        self.state.update(captured_utc_ms=int(time.time()*1000),generation=self.state['generation']+1)
        self.write('snapshot.json',self.state)

    def run(self):
        while not self.stopping.wait(.02):
            try:
                if self.pending and time.monotonic()>=self.pending[1]:
                    self.state.update(exchanging=False,selected_units=0,exchanges=0,selection='',
                        pending_attempt='',available_exchanges=179,can_select=True,
                        receipt=dict(attempt=self.pending[0],completed=1,finished=True,failed=False))
                    self.pending=None
                try:r=json.loads((self.path/'request.json').read_text())
                except (OSError,ValueError):r=None
                if r and r['id'] not in self.seen:
                    self.seen.add(r['id']);self.requests.append(r)
                    if self.state.get('mode') == 'interactive':
                        assert r['sequence'] > self.state['command_sequence']
                        self.state['command_sequence'] = r['sequence']
                        if r['op'] in {'select','merge'}:
                            assert r['run_attempt'] and r['run_attempt'] == self.state['run_attempt']
                            assert self.state['spent'] < self.state['test_budget']
                    if r['op']=='begin':
                        self.state.update(run_attempt=r['id'],test_budget=self.state['spent']+r['limit'],receipt=None)
                    elif r['op']=='select':
                        self.state.update(selected_units=10,exchanges=1,selection=r['id'],selection_attempt=r['id'],
                                          available_exchanges=None,can_select=None,receipt=None)
                    elif r['op']=='merge':
                        assert r['count']==1 and r['expected_group']==self.state['group']
                        assert r['selection']==self.state['selection']
                        self.state.update(exchanging=True,pending_attempt=r['id'],spent=self.state['spent']+1)
                        self.pending=(r['id'],time.monotonic()+.15)
                    elif r['op']=='group':
                        self.state.update(group=r['group'],available_group=r['group'],available_exchanges=193)
                    elif r['op']=='stop':
                        self.state.update(selected_units=0,exchanges=0,selection='')
                        if self.state.get('mode')=='interactive':
                            self.state.update(run_attempt='',test_budget=self.state['spent'])
                    self.publish()
                    self.write('response.json',dict(id=r['id'],epoch=r['epoch'],ok=True))
                else:self.publish()
            except OSError:pass  # File sharing race: the next observation stays timestamped.

    def close(self):
        self.stopping.set();self.thread.join(1)


def until(predicate,timeout=5):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.03)
    raise AssertionError('condition did not arrive')


@pytest.mark.skipif(os.name!='nt',reason='Windows session file locks')
def test_real_ipc_adapter_serializes_two_single_merges_then_stops_at_test_budget(tmp_path):
    server=FileServer(tmp_path)
    adapter=BridgeAdapter(channel=BridgeChannel(tmp_path,verify_target=lambda config:None))
    runner=AutoMerge(adapter)
    try:
        until(lambda:adapter.observe().ready)
        assert runner.maximum()==180
        assert not server.requests  # Maximum never selects or consumes.
        assert runner.start(180)
        def finished():runner.tick();return not runner.active
        until(finished)
        assert runner.completed==2 and runner.reason=='test_budget_exhausted'
        assert [r['op'] for r in server.requests]==['select','merge','select','merge']
        assert all(r['count']==1 for r in server.requests if r['op']=='merge')
        assert not runner.start(1)
    finally:runner.close();server.close()


@pytest.mark.skipif(os.name!='nt',reason='Windows session file locks')
def test_single_writer_lock_and_async_group_selection(tmp_path):
    server=FileServer(tmp_path)
    adapter=BridgeAdapter(channel=BridgeChannel(tmp_path,verify_target=lambda config:None))
    try:
        with pytest.raises(RuntimeError,match='bridge_client_in_use'):
            BridgeChannel(tmp_path,verify_target=lambda config:None)
        until(lambda:adapter.observe().ready)
        runner=AutoMerge(adapter)
        assert runner.set_group('emotes')
        until(lambda:adapter.observe().ready and adapter.observe().category=='emotes')
        assert runner.maximum()==193
        assert [r['op'] for r in server.requests]==['group']
    finally:adapter.close();server.close()


def test_snapshot_age_is_not_refreshed_and_budget_is_separate_from_inventory():
    raw=raw_snapshot();raw.update(captured_utc_ms=100000,spent=2,available_exchanges=180)
    value=observation(raw,clock=lambda:50,wall=lambda:101)
    assert value.captured_at==49 and value.execution_budget_remaining==0
    assert value.available_exchanges==180
    with pytest.raises(ValueError):observation(raw,wall=lambda:102)


@pytest.mark.parametrize('patch',[{'spent':3},{'spent':True},{'test_budget':3},{'per_request_limit':2},{'available_group':'emotes'}])
def test_unverified_snapshot_rejected(patch):
    raw=raw_snapshot();raw.update(patch)
    with pytest.raises(ValueError):observation(raw)
