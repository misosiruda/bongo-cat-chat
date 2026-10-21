"""Product UI with synthetic peers, optionally locally extracted real artwork.

The optional artwork is local-only: never commit or distribute game assets.
"""
import argparse
from http.server import HTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright

from browser_scroll_check import Fixture, Handler, same_anchor
from test_reactions import PNG, reaction


class Reactions(Fixture):
    def __init__(self, browser, url, assets):
        self.assets=assets
        super().__init__(browser,url,60)
        profiles={'fixture-peer':{'name':'미리보기 고양이','avatar':assets['cat']}}
        self.state=dict(self.state,profiles=profiles)
        self.service.update(self.state)
        self.poll()

    def request(self,raw):
        result=json.loads(super().request(raw));args=json.loads(raw)
        if args['action']=='view' and 'reactions' in args:
            result['reactions']=self.service.take_reactions(result['lobby'],args['reactions'] and not args.get('query'))
        return json.dumps(result,ensure_ascii=False)

    def emit(self,count=1,kind='emote'):
        for i in range(count):
            self.service.receive_reaction(reaction(self.service,kind=kind,avatar=self.assets['cat'],
                image=self.assets['item'] if i%2 else self.assets['rocket']))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--channel',default='msedge')
    parser.add_argument('--assets',type=Path)
    parser.add_argument('--output',type=Path,default=Path('artifacts/reactions'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    assets=json.loads(args.assets.read_text(encoding='utf-8')) if args.assets else dict(cat=PNG,item=PNG,rocket=PNG)
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel=args.channel,headless=True)
            f=Reactions(browser,f'http://127.0.0.1:{server.server_port}/',assets)
            try:
                page=f.page;f.middle();before=f.snapshot()
                page.locator('#message-input').fill('반응이 떠도 계속 쓰는 초안')
                f.emit(6)
                expect(page.locator('.reaction-particle')).to_have_count(6)
                page.evaluate("document.querySelectorAll('.reaction-particle').forEach(el=>{const a=el.getAnimations()[0];a.pause();a.currentTime=0;})")
                y0=page.locator('.reaction-particle').first.bounding_box()['y']
                page.evaluate("document.querySelectorAll('.reaction-particle').forEach(el=>el.getAnimations()[0].currentTime=1050)")
                y1=page.locator('.reaction-particle').first.bounding_box()['y']
                assert y1<y0-100
                assert page.locator('.reaction-particle img').evaluate_all('(els)=>els.every(el=>el.complete&&el.naturalWidth>0)')
                assert page.locator('#reaction-layer').evaluate('(el)=>getComputedStyle(el).pointerEvents')=='none'
                same_anchor(before,f.snapshot())
                assert page.locator('.message').count()==60
                assert not page.locator('#new-messages').is_visible()
                assert '×' not in page.locator('#reaction-layer').inner_text()
                page.screenshot(path=str(args.output/'real-items-wide.png'))
                page.evaluate("document.querySelectorAll('.reaction-particle').forEach(el=>el.getAnimations()[0].play())")
                expect(page.locator('.reaction-particle')).to_have_count(0)
                f.emit(100)
                expect(page.locator('.reaction-particle')).to_have_count(12)
                expect(page.locator('.reaction-particle')).to_have_count(0)
                page.wait_for_timeout(650)
                assert page.locator('.reaction-particle').count()==0
                f.emit(3,kind='meow');expect(page.locator('.reaction-meow')).to_have_count(3)
                f.service.update(dict(f.state,hidden={'fixture-peer':True}))
                expect(page.locator('.reaction-particle')).to_have_count(0)
                f.service.update(f.state);f.poll()
                page.locator('#message-search').fill('검증')
                f.emit(3);f.poll();assert page.locator('.reaction-particle').count()==0
                page.locator('#message-search').fill('');f.poll()
                page.set_viewport_size({'width':390,'height':740})
                f.emit(6);expect(page.locator('.reaction-particle')).to_have_count(5)
                page.evaluate("document.querySelectorAll('.reaction-particle').forEach(el=>{const a=el.getAnimations()[0];a.pause();a.currentTime=1050;})")
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(args.output/'real-items-narrow.png'))
                expect(page.locator('#message-input')).to_have_value('반응이 떠도 계속 쓰는 초안')
                expect(page.locator('.reaction-particle')).to_have_count(0)
                page.emulate_media(reduced_motion='reduce',color_scheme='dark')
                f.emit(1,kind='meow');expect(page.locator('.reaction-meow')).to_have_count(1)
                particle=page.locator('.reaction-particle')
                assert particle.evaluate('(el)=>getComputedStyle(el).animationName')=='reaction-fade'
                assert particle.evaluate('(el)=>getComputedStyle(el).animationDuration')=='2.2s'
                page.wait_for_timeout(500);page.screenshot(path=str(args.output/'real-items-dark-reduced.png'))
                expect(particle).to_have_count(0)
                assert not f.errors,f.errors
                assert f.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==60
                print(json.dumps(dict(passed=True,channel=args.channel,real_local_assets=bool(args.assets),
                    repeated=6,burst=100,peak=12,narrow_peak=5,history=60,errors=f.errors)))
            finally:f.close();browser.close()
    finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
