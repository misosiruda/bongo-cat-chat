"""Browser-only fixture QA of product HTML. Native bridge is covered separately.

Browser plugin not available in this session: use local Playwright Chromium.
No Steam initialization. Screenshots only contain synthetic messages.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from playwright.sync_api import expect, sync_playwright

from bongo_chat.service import ChatService
from bongo_chat.store import Store


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--browser",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[1]/"src/bongo_chat/ui"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path == "/channel.js":
                body=b"window.qt={webChannelTransport:{}}; window.QWebChannel=function(t,cb){cb({objects:{bridge:{request:(raw,done)=>window.fixtureRequest(raw).then(done)}}})};"
                mime="text/javascript"
            elif self.path in ("/","/index.html","/app.js","/messenger.css"):
                name=self.path.lstrip('/') or 'index.html';body=(root/name).read_bytes()
                if name=='index.html':body=body.replace(b'qrc:///qtwebchannel/qwebchannel.js',b'/channel.js')
                mime='text/html' if name.endswith('html') else 'text/css' if name.endswith('css') else 'text/javascript'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',mime+'; charset=utf-8');self.end_headers();self.wfile.write(body)
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    with TemporaryDirectory() as temp, sync_playwright() as p, ExitStack() as resources:
        store=Store(Path(temp)/'fixture.sqlite3');service=ChatService(store,clock=lambda:100)
        resources.callback(server.server_close);resources.callback(server.shutdown)
        resources.callback(store.close)
        state=dict(state='ready',account='fixture-self',lobby='fixture-room',generation='fixture-generation',name='오후의 대화',hidden_ok=True,
                   hidden={'fixture-peer':False},profiles={'fixture-self':{'name':'테스트 계정'},'fixture-peer':{'name':'연습 고양이'}},send_enabled=True)
        service.update(state)
        for index,text in enumerate(['오늘의 한글 입력을 확인해요.','이 기록은 실제 Steam 채팅이 아닌 시험 자료입니다.','같은 말을 두 번 해도 두 개의 발언으로 보관해요.','긴 대화의 스크롤 위치도 함께 확인합니다.']*12):
            service.receive(dict(id=f'fixture-{index}',sender='fixture-peer',text=text,context=service.context()))
        def request(raw):
            args=json.loads(raw);action=args['action']
            if action=='view':result=service.view(args.get('lobby'),args.get('query',''),args.get('before'))
            elif action=='setting':store.setting(args['key'],args['value']);result={'ok':True}
            elif action=='draft':store.draft(args['account'],args['lobby'],args['text']);result={'ok':True}
            elif action=='refresh':result={'ok':True}
            elif action=='send':command=service.prepare(args['context'],args['text']);service.result(command['id'],'accepted');result={'id':command['id']}
            else:result={'error':'unsupported_test_action'}
            return json.dumps(result,ensure_ascii=False)
        browser=p.chromium.launch(executable_path=str(args.browser),headless=True)
        resources.callback(browser.close)
        page=browser.new_page(viewport={'width':1536,'height':1024},device_scale_factor=1)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
        page.expose_function('fixtureRequest',request);page.goto(url)
        page.locator('.message-bubble').first.wait_for()
        assert '개발판' in page.title() and page.url==url
        assert page.locator('.message-bubble').count()==48
        page.locator('#message-input').fill('작성 중인 한글')
        page.wait_for_timeout(250)
        page.locator('#settings-button').click();page.locator('[value=light]').check();page.locator('[aria-label="설정 닫기"]').click()
        page.locator('#message-scroll').evaluate('(el)=>el.scrollTop=0')
        page.screenshot(path=str(args.output/'messenger-light.png'))
        top=page.locator('#message-scroll').evaluate('(el)=>el.scrollTop')
        page.locator('#settings-button').click();page.locator('[value=dark]').check();page.locator('[aria-label="설정 닫기"]').click()
        assert page.locator('#message-input').input_value()=='작성 중인 한글'
        assert page.locator('#message-scroll').evaluate('(el)=>el.scrollTop')==top
        page.screenshot(path=str(args.output/'messenger-dark.png'))
        page.locator('#sidebar-toggle').click();assert 'is-collapsed' in page.locator('#app').get_attribute('class')
        page.keyboard.press('Control+k');page.locator('#message-search').fill('한글 입력');page.wait_for_timeout(800)
        assert page.locator('.message-bubble').count()==12
        assert page.locator('mark').count()==12
        page.locator('#settings-button').click();page.locator('[value=system]').check();page.locator('[aria-label="설정 닫기"]').click()
        page.emulate_media(color_scheme='light')
        expect(page.locator('html')).to_have_attribute('data-theme','light')
        page.emulate_media(color_scheme='dark')
        expect(page.locator('html')).to_have_attribute('data-theme','dark')
        assert page.locator('#message-search').input_value()=='한글 입력'
        assert page.locator('#message-input').input_value()=='작성 중인 한글'
        page.locator('#clear-search').click();page.wait_for_timeout(800)
        page.locator('#message-input').dispatch_event('compositionstart')
        page.locator('#message-input').dispatch_event('keydown',{'key':'Enter','isComposing':True,'keyCode':229})
        assert store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==48
        page.locator('#message-input').dispatch_event('compositionend')
        page.locator('#message-scroll').evaluate('(el)=>el.scrollTop=0')
        service.receive(dict(id='fixture-new-visible',sender='fixture-peer',text='추가 시험 발언',context=service.context()))
        page.wait_for_timeout(800)
        assert page.locator('#new-messages').is_visible()
        service.update(dict(state,hidden={'fixture-peer':True}));page.wait_for_timeout(800)
        assert page.locator('.message-bubble').count()==0
        assert page.locator('#new-messages').is_hidden()
        service.update(dict(state,hidden_ok=False));page.wait_for_timeout(800)
        assert page.locator('#send-button').is_disabled()
        assert page.locator('#connection-label .status-dot').get_attribute('class').find('unavailable')>=0
        page.screenshot(path=str(args.output/'messenger-unavailable.png'))
        service.update(state);page.set_viewport_size({'width':480,'height':800});page.wait_for_timeout(800)
        page.screenshot(path=str(args.output/'messenger-narrow.png'))
        assert page.locator('#mobile-menu').is_visible()
        page.locator('#mobile-menu').click();assert page.locator('#message-search').is_visible()
        page.locator('#drawer-backdrop').click(position={'x':400,'y':400})
        assert not errors,errors
        print(json.dumps({'url':url,'viewports':['1536x1024','480x800'],'checks':'passed','console_errors':errors,'steam_connected':False}))


if __name__=='__main__':main()
