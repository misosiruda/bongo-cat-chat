"""Explicit single-command developer client. Never loops or retries a merge."""
import argparse
import json
from pathlib import Path
import os
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from bongo_chat.environment import running_game
from bongo_chat.merge_bridge import BridgeChannel
from bootstrap import kernel, start_ticks


class Client:
    def __init__(self, session):
        self.session = Path(session).resolve()
        self.channel = BridgeChannel(self.session)
        self.config = self.channel.config

    def verify(self):
        game = running_game()
        if game.pid != self.config['pid']: raise RuntimeError('process_changed')
        k = kernel(); handle = k.OpenProcess(0x0400,False,game.pid)
        try:
            if not handle or start_ticks(k,handle) != self.config['process_start_ticks']:
                raise RuntimeError('process_changed')
        finally:
            if handle:k.CloseHandle(handle)

    def snapshot(self):
        value = json.loads((self.session/'snapshot.json').read_text(encoding='utf-8-sig'))
        if (value['protocol'] != 1 or value['epoch'] != self.config['epoch']
                or value['pid'] != self.config['pid']
                or not 0 <= time.time()*1000-value['captured_utc_ms'] <= 1500):
            raise RuntimeError('stale_or_wrong_snapshot')
        return value

    def request(self, op, **extra):
        self.verify()
        before = self.snapshot()
        request = dict(id=uuid.uuid4().hex, epoch=self.config['epoch'],token=self.config['token'],
                       issued_utc_ms=int(time.time()*1000),op=op,expected_group=before['group'],
                       favorites_allowed=before['favorites_allowed'],events_excluded=before['events_excluded'],**extra)
        if op == 'merge':
            if (not before['ready'] or before['selected_units'] != 10 or before['exchanges'] != 1
                    or before['spent'] >= before['test_budget'] or before['pending_attempt']):
                raise RuntimeError('single_merge_not_ready')
            request.update(count=1,selection=before['selection'],selection_attempt=before['selection_attempt'])
        # A mutation is submitted once. A response timeout is never an invitation to retry.
        with (self.session/'client-requests.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(id=request['id'],op=op,issued_utc_ms=request['issued_utc_ms']))+'\n')
        tmp=self.session/'request.client.tmp'
        tmp.write_text(json.dumps(request,separators=(',',':')),encoding='utf-8')
        os.replace(tmp,self.session/'request.json')
        end=time.monotonic()+5
        reply=None
        while time.monotonic()<end:
            try:
                candidate=json.loads((self.session/'response.json').read_text(encoding='utf-8-sig'))
                if candidate['id']==request['id'] and candidate['epoch']==self.config['epoch']:
                    reply=candidate
                    snapshot=self.snapshot()
                    if snapshot['generation']>before['generation']:
                        return dict(response=reply,snapshot=snapshot)
            except (OSError,ValueError,KeyError):pass
            time.sleep(0.05)
        raise RuntimeError('request_outcome_unknown_no_retry' if reply is None else 'response_received_snapshot_unavailable')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('operation',choices=['read','snapshot','group','select','merge-one','stop','shutdown'])
    p.add_argument('--group',choices=['cosmetics','emotes'])
    args=p.parse_args();client=Client(args.session)
    try:
        if args.operation=='read':result=client.snapshot()
        elif args.operation=='group':
            if not args.group:p.error('--group is required')
            result=client.request('group',group=args.group)
        else:result=client.request('merge' if args.operation=='merge-one' else args.operation)
        print(json.dumps(result,ensure_ascii=False))
    finally:client.channel.close()
