"""Synthetic browser regression checks for product history and scroll navigation."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bongo_chat.service import ChatService
from bongo_chat.store import Store
from playwright.sync_api import expect, sync_playwright

UI = Path(__file__).resolve().parents[1] / "src/bongo_chat/ui"
SNAPSHOT = """() => {
 const el=document.querySelector('#message-scroll'), rect=el.getBoundingClientRect();
 const row=[...el.querySelectorAll('.message')].find(x=>x.getBoundingClientRect().bottom>rect.top);
 return {id:row?.id,offset:row?row.getBoundingClientRect().top-rect.top:0,
   gap:el.scrollHeight-el.scrollTop-el.clientHeight, count:el.querySelectorAll('.message').length};
}"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == '/favicon.ico':
            self.send_response(204); self.end_headers(); return
        if self.path == '/channel.js':
            body=b"window.qt={webChannelTransport:{}};window.QWebChannel=function(t,cb){cb({objects:{bridge:{request:(raw,done)=>window.fixtureRequest(raw).then(done)}}})};"
            mime='text/javascript'
        elif self.path in ('/', '/index.html', '/app.js', '/messenger.css'):
            name=self.path.lstrip('/') or 'index.html'
            body=(UI/name).read_bytes()
            if name=='index.html': body=body.replace(b'qrc:///qtwebchannel/qwebchannel.js',b'/channel.js')
            mime='text/html' if name.endswith('html') else 'text/css' if name.endswith('css') else 'text/javascript'
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type',mime+'; charset=utf-8')
        self.end_headers(); self.wfile.write(body)

class Fixture:
    def __init__(self, browser, url, count, viewport=None):
        self.temp=TemporaryDirectory(prefix='bongo-scroll-regression-')
        self.store=Store(Path(self.temp.name)/'fixture.sqlite3')
        self.service=ChatService(self.store,clock=lambda:100)
        self.state=dict(state='ready',account='fixture-self',lobby='fixture-room-a',generation='fixture-a',
            connected=True,lobby_verified=True,privacy_ready=True,
            name='가상 스크롤 검증',hidden_ok=True,hidden={'fixture-peer':False},send_enabled=True,
            profiles={'fixture-self':{'name':'테스트 계정'},'fixture-peer':{'name':'검증 고양이'}})
        self.service.update(self.state); self.index=0
        for _ in range(count): self.add()
        self.page=browser.new_page(viewport=viewport or {'width':1280,'height':800},color_scheme='light')
        self.errors=[]; self.warnings=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('console',lambda message:self.errors.append(message.text) if message.type=='error'
                     else self.warnings.append(message.text) if message.type=='warning' else None)
        self.page.expose_function('fixtureRequest',self.request)
        self.page.goto(url)
        expect(self.page.locator('#room-title')).to_have_text('가상 스크롤 검증')
        expect(self.page.locator('.message')).to_have_count(min(100,count))
        assert self.page.title()=='Bongo Cat Chat · 개발판' and self.page.url==url
    def add(self, text=None):
        self.index+=1
        self.service.receive(dict(id=f'fixture-{self.index}',sender='fixture-peer',
            text=text or f'스크롤 검증 {self.index:04d}',context=self.service.context()))
    def request(self,raw):
        args=json.loads(raw); action=args['action']
        if action=='view':
            result=self.service.view(args.get('lobby'),args.get('query',''),args.get('before'),
                                     args.get('start'),args.get('seen'),args.get('limit',100))
        elif action=='setting': self.store.setting(args['key'],args['value']); result={'ok':True}
        elif action=='draft': self.store.draft(args['account'],args['lobby'],args['text']); result={'ok':True}
        elif action=='send':
            command=self.service.prepare(args['context'],args['text'])
            self.service.result(command['id'],'accepted'); result={'id':command['id']}
        elif action=='refresh': result={'ok':True}
        else: result={'error':'unsupported_fixture_action'}
        return json.dumps(result,ensure_ascii=False)
    def poll(self): self.page.wait_for_timeout(750)
    def snapshot(self): return self.page.evaluate(SNAPSHOT)
    def middle(self):
        self.page.locator('#message-scroll').evaluate('(el)=>el.scrollTop=(el.scrollHeight-el.clientHeight)/2')
        self.page.wait_for_timeout(60)
    def top(self):
        self.page.locator('#message-scroll').evaluate('(el)=>el.scrollTop=0')
    def bottom(self):
        self.page.locator('#message-scroll').evaluate('(el)=>el.scrollTop=el.scrollHeight')
    def close(self):
        self.page.close(); self.store.close(); self.temp.cleanup()

@contextmanager
def fixture(browser,url,count,viewport=None):
    value=Fixture(browser,url,count,viewport)
    try:
        yield value
        assert not value.errors, value.errors
        assert not value.warnings, value.warnings
    finally: value.close()

def same_anchor(before,after):
    assert after['id']==before['id'], (before,after)
    assert abs(after['offset']-before['offset'])<2, (before,after)

def wait_bottom(f):
    for _ in range(100):
        if f.snapshot()['gap']<=1:
            return
        f.page.wait_for_timeout(30)
    raise AssertionError(f.snapshot())

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    server=HTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}/'
    checks=[]
    def passed(name):
        checks.append(name); print(f'PASS {name}',flush=True)
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=str(args.browser),headless=True)
        try:
          for viewport in [{'width':1280,'height':800},{'width':480,'height':800}]:
            with fixture(browser,url,48,viewport) as f:
                f.middle(); f.add(); f.poll()
                expect(f.page.locator('#new-messages')).to_be_visible()
                bounds=f.page.locator('#new-messages').bounding_box()
                assert 0 <= bounds['x'] and bounds['x']+bounds['width']<=viewport['width']
                f.bottom(); f.poll()
                expect(f.page.locator('#new-messages')).to_be_hidden()
                expect(f.page.locator('#latest')).to_be_hidden()
                assert f.snapshot()['gap']<=1
                f.middle(); expect(f.page.locator('#latest')).to_be_visible()
                f.page.locator('#latest').click()
                wait_bottom(f)
                f.page.screenshot(path=str(args.output/f"scroll-bottom-{viewport['width']}.png"))
                passed(f"manual_bottom_and_fixed_navigation_{viewport['width']}")
          with fixture(browser,url,300) as f:
            f.page.locator('#message-input').fill('가상 초안')
            f.middle(); anchor=f.snapshot()
            for _ in range(5): f.add()
            expect(f.page.locator('.message')).to_have_count(105)
            same_anchor(anchor,f.snapshot())
            expect(f.page.locator('#new-messages')).to_be_visible()
            f.page.screenshot(path=str(args.output/'reading-anchor.png'))
            f.page.locator('#new-messages').click()
            expect(f.page.locator('.message')).to_have_count(100)
            assert f.snapshot()['gap']<=1
            assert f.page.locator('#message-input').input_value()=='가상 초안'
            f.top(); expect(f.page.locator('.message')).to_have_count(200)
            assert f.page.locator('#message-fixture-206').count()==1
            f.top(); expect(f.page.locator('.message')).to_have_count(300)
            f.top(); expect(f.page.locator('.message')).to_have_count(305)
            expect(f.page.locator('#older')).to_be_hidden()
            expect(f.page.locator('#latest')).to_be_visible()
            f.page.locator('#latest').click(); expect(f.page.locator('.message')).to_have_count(100)
            wait_bottom(f)
            passed('live_anchor_and_continuous_older_history')
          with fixture(browser,url,100) as f:
            f.top(); f.poll()
            expect(f.page.locator('#older')).to_be_hidden()
            expect(f.page.locator('.message')).to_have_count(100)
            expect(f.page.locator('#empty-state')).to_be_hidden()
            passed('exact_100_history_end')
          with fixture(browser,url,1250) as f:
            f.page.locator('#message-search').fill('검증 0250')
            expect(f.page.locator('.message')).to_have_count(1)
            f.page.get_by_role('button',name='대화에서 보기',exact=True).click()
            expect(f.page.locator('.message')).to_have_count(1000)
            assert f.page.locator('#message-fixture-251').count()==1
            f.middle(); anchor=f.snapshot()
            f.add('과거 열람 중 새 가상 메시지'); f.poll()
            same_anchor(anchor,f.snapshot())
            expect(f.page.locator('#new-messages')).to_be_visible()
            f.page.screenshot(path=str(args.output/'history-new-message.png'))
            f.page.locator('#message-search').fill('검증 0250')
            expect(f.page.locator('.message')).to_have_count(1)
            f.page.get_by_role('button',name='대화에서 보기',exact=True).click()
            expect(f.page.locator('.message')).to_have_count(1000)
            expect(f.page.locator('#new-messages')).to_be_visible()
            f.page.locator('#message-input').fill('과거 열람 중 내 가상 메시지')
            f.page.locator('#send-button').click()
            expect(f.page.locator('.message.is-own')).to_have_count(1)
            expect(f.page.locator('.message-status')).to_have_text('전송됨 · Steam 접수')
            assert f.snapshot()['gap']<=1
            expect(f.page.locator('#message-input')).to_have_value('')
            passed('bounded_history_notification_and_own_send')
            f.page.locator('#message-search').fill('검증 0250')
            expect(f.page.locator('.message')).to_have_count(1)
            f.page.get_by_role('button',name='대화에서 보기',exact=True).click()
            expect(f.page.locator('.message')).to_have_count(1000)
            f.middle(); anchor=f.snapshot()
            f.page.locator('#message-search').fill('검증 0050')
            expect(f.page.locator('.message')).to_have_count(1)
            f.page.locator('#clear-search').click()
            expect(f.page.locator('.message')).to_have_count(1000)
            same_anchor(anchor,f.snapshot())
            f.service.update(dict(f.state,lobby='fixture-room-b',generation='fixture-b',name='두 번째 가상 방'))
            for _ in range(16): f.add()
            f.service.update(f.state); f.poll()
            f.page.get_by_role('button',name='두 번째 가상 방',exact=True).click()
            expect(f.page.locator('#room-title')).to_have_text('두 번째 가상 방')
            f.page.get_by_role('button',name='가상 스크롤 검증',exact=True).click()
            expect(f.page.locator('#room-title')).to_have_text('가상 스크롤 검증')
            same_anchor(anchor,f.snapshot())
            f.bottom(); f.poll()
            assert f.page.locator('#message-fixture-1251').count()==1
            assert f.snapshot()['count']<=1000
            passed('search_room_restore_and_forward_history')
          with fixture(browser,url,48) as f:
            f.middle(); f.add(); f.poll()
            expect(f.page.locator('#new-messages')).to_be_visible()
            f.service.update(dict(f.state,hidden={'fixture-peer':True})); f.poll()
            expect(f.page.locator('.message')).to_have_count(0)
            expect(f.page.locator('#new-messages')).to_be_hidden()
            passed('hidden_messages_and_unread_metadata_removed')
          result=dict(url=url,browser=browser.version,viewports=['1280x800','480x800'],checks=checks,
              page_identity='passed',not_blank='passed',framework_overlay='none',console_errors=[],
              console_warnings=[],screenshots='captured',interactions='passed',steam_connected=False)
          (args.output/'scroll-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
          print(json.dumps(result,ensure_ascii=False),flush=True)
        finally: browser.close()
    finally: server.shutdown(); server.server_close()

if __name__=='__main__': main()

