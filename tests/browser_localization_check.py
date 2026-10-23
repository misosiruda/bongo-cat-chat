"""English/Korean layout QA with synthetic chat and no Steam or Windows delivery."""
import argparse
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading

from playwright.sync_api import expect, sync_playwright

from bongo_chat.localization import ENGLISH, resolve_language
from bongo_chat.service import ChatService
from bongo_chat.store import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[1]/'src/bongo_chat/ui'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            if self.path=='/channel.js':
                body=b'window.qt={webChannelTransport:{}};window.QWebChannel=function(_,cb){cb({objects:{bridge:{request:(raw,done)=>window.fixtureRequest(raw).then(done)}}});};'
                mime='text/javascript'
            elif self.path in ('/','/index.html','/app.js','/messenger.css','/app-icon.png','/favicon.ico'):
                name=self.path.lstrip('/') or 'index.html'
                body=(root/name).read_bytes()
                if name=='index.html': body=body.replace(b'qrc:///qtwebchannel/qwebchannel.js',b'/channel.js')
                mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.ico':'image/x-icon'}[Path(name).suffix]
            else:
                self.send_error(404); return
            self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(body)
    with TemporaryDirectory() as tmp,sync_playwright() as p,ExitStack() as resources:
        server=HTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        resources.callback(server.server_close);resources.callback(server.shutdown)
        url=f'http://127.0.0.1:{server.server_port}/'
        store=Store(Path(tmp)/'history.sqlite3');resources.callback(store.close)
        store.setting('language','en')
        service=ChatService(store,clock=lambda:100)
        ready=dict(state='ready',account='fixture-self',lobby='fixture-room',generation='fixture-generation',
                   connected=True,lobby_verified=True,privacy_ready=True,hidden_ok=True,send_enabled=True,
                   name='Community lounge (sample)',hidden={'fixture-peer':False},
                   profiles={'fixture-self':{'name':'Sample Cat'},'fixture-peer':{'name':'Demo Cat'}})
        service.update(ready)
        texts=['Hello from the community lounge!','This is synthetic chat for the language preview.',
               'Try Settings → Language to switch between English and Korean.',
               'The app keeps received messages on this device.']
        for i in range(48):
            service.receive(dict(id=f'fixture-{i}',sender='fixture-peer',text=texts[i%4],context=service.context()))
        options={'fail_language':False,'update':'development'}
        def request(raw):
            data=json.loads(raw);action=data['action']
            if action=='view':
                result=service.view(data.get('lobby'),data.get('query',''),data.get('before'),data.get('start'),data.get('seen'),data.get('limit',100))
                preference=store.setting('language',default='system');language=resolve_language(preference,'en-US')
                result.update(language=language,language_preference=preference,
                              update={'state':options['update'],'current':'source preview','allowed':True},
                              notification_status={'toast':'unavailable','flash':'unavailable'})
                if data.get('language')!=language:result['translations']=ENGLISH if language=='en' else {}
            elif action=='setting':
                if data['key']=='language' and options['fail_language']:return json.dumps({'error':'storage_failed'})
                if data['key'].startswith('notification_'):service.set_notification(data['key'],data['value'])
                elif data['key']=='reactions_enabled':service.set_reactions_enabled(data['value'])
                else:store.setting(data['key'],data['value'])
                result={'ok':True}
            elif action=='draft':store.draft(data['account'],data['lobby'],data['text']);result={'ok':True}
            elif action=='refresh':result={'ok':True}
            else:result={'error':'unsupported_test_action'}
            return json.dumps(result,ensure_ascii=False)
        browser=p.chromium.launch(executable_path=str(args.browser),headless=True);resources.callback(browser.close)
        page=browser.new_page(viewport={'width':1240,'height':840},device_scale_factor=1)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
        page.expose_function('fixtureRequest',request);page.goto(url)
        expect(page.locator('html')).to_have_attribute('lang','en')
        assert page.url==url and 'Development build' in page.title()
        expect(page.locator('.message-bubble')).to_have_count(48)
        assert not page.locator('nextjs-portal, vite-error-overlay').count()
        page.locator('#message-input').fill('Draft stays unchanged: 설정')
        page.locator('#message-scroll').evaluate('(el)=>el.scrollTop=900')
        anchor=page.evaluate("""()=>{const box=document.querySelector('#message-scroll').getBoundingClientRect();const row=[...document.querySelectorAll('.message')].find(el=>el.getBoundingClientRect().bottom>box.top);return {id:row.id,y:row.getBoundingClientRect().top-box.top}}""")
        page.locator('#settings-button').click()
        page.locator('#language-select').select_option('ko')
        expect(page.locator('html')).to_have_attribute('lang','ko')
        page.locator('#language-select').select_option('en')
        expect(page.locator('html')).to_have_attribute('lang','en')
        expect(page.locator('#language-status')).to_have_text('Language preference saved.')
        page.keyboard.press('Escape')
        offset=page.locator('#'+anchor['id']).evaluate('(el)=>el.getBoundingClientRect().top-document.querySelector("#message-scroll").getBoundingClientRect().top')
        assert abs(offset-anchor['y'])<2,(anchor,offset)
        assert page.locator('#message-input').input_value()=='Draft stays unchanged: 설정'
        page.locator('#message-search').fill('synthetic')
        expect(page.locator('.message-bubble')).to_have_count(12)
        page.locator('#settings-button').click()
        options['fail_language']=True
        page.locator('#language-select').select_option('ko')
        expect(page.locator('#language-status')).to_contain_text('Could not save')
        expect(page.locator('#language-select')).to_have_value('en')
        assert page.locator('#message-search').input_value()=='synthetic'
        page.screenshot(path=str(args.output/'english-language-save-failure.png'))
        options['fail_language']=False
        page.locator('#language-select').select_option('en')
        expect(page.locator('#language-status')).to_have_text('Language preference saved.')
        page.keyboard.press('Escape');page.locator('#clear-search').click()
        page.locator('#latest').click()
        page.screenshot(path=str(args.output/'english-conversation.png'))
        for width,height in [(1240,840),(960,540),(400,500)]:
            page.set_viewport_size({'width':width,'height':height})
            if width<=760:expect(page.locator('#sidebar')).not_to_be_in_viewport()
            assert page.locator('#app').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(args.output/f'english-conversation-{width}.png'))
            if width<=760:page.locator('#mobile-menu').click()
            for theme in ('light','dark'):
                page.locator('#settings-button').click()
                expect(page.locator('#language-select')).to_be_in_viewport()
                page.locator(f'[value={theme}]').check()
                page.locator('#language-select').scroll_into_view_if_needed()
                expect(page.locator('#language-select')).to_be_in_viewport()
                page.screenshot(path=str(args.output/f'english-settings-{theme}-{width}.png'))
                page.locator('#delete-room').click()
                page.locator('#confirm-delete').scroll_into_view_if_needed()
                expect(page.get_by_role('button',name='Close settings',exact=True)).to_be_in_viewport(ratio=1)
                assert page.locator('#settings-content').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                assert page.locator('#settings-dialog').evaluate('(el)=>el.scrollHeight<=el.clientHeight')
                page.screenshot(path=str(args.output/f'english-settings-bottom-{theme}-{width}.png'))
                page.keyboard.press('Escape')
            if width<=760:page.locator('#drawer-backdrop').click(position={'x':350,'y':250})
        page.set_viewport_size({'width':1240,'height':840})
        # Exercise error and progress copy with the real rendering code.
        for notice in ('offline','discovering','read_only','hidden_unavailable','hidden_syncing','unsupported_game_build','worker_stopped'):
            service.update(dict(ready,notice=notice))
            expect(page.locator('html')).to_have_attribute('data-notice',notice)
            assert not any('\uac00'<=c<='\ud7a3' for c in page.locator('#connection-notice').inner_text())
        for status in ('checking','downloading','verification_failed','network_error','ready','rolled_back'):
            options['update']=status
            expected=ENGLISH[{
                'checking':'새 버전을 확인하고 있어요.','downloading':'새 버전을 내려받고 있어요. 채팅을 계속 이용할 수 있습니다.',
                'verification_failed':'업데이트를 확인하지 못했어요. 현재 버전을 유지합니다.',
                'network_error':'업데이트 서버에 연결하지 못했어요. 다음 확인 때 다시 시도합니다.',
                'ready':'업데이트 준비 완료 · 다음 실행 때 적용합니다.',
                'rolled_back':'새 버전이 시작되지 않아 이전 버전으로 돌아왔습니다.'}[status]]
            expect(page.locator('#update-status')).to_have_text(expected)
        page.reload();expect(page.locator('html')).to_have_attribute('lang','en')
        expect(page.locator('#message-input')).to_have_value('Draft stays unchanged: 설정')
        assert not errors,errors
        print(json.dumps({'url':url,'checks':'passed','viewports':['1240x840','960x540','400x500'],
                          'settings_layout_cases':6,'console_errors':errors,'steam_connected':False,
                          'scroll_anchor_delta':round(offset-anchor['y'],2),'screenshots':str(args.output)}))


if __name__=='__main__':main()
