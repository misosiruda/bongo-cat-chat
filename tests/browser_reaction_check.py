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
        args=json.loads(raw)
        if args['action']=='setting' and args['key']=='reactions_enabled':
            self.service.set_reactions_enabled(args['value'])
            return json.dumps({'ok':True})
        result=json.loads(super().request(raw))
        if args['action']=='view' and 'reactions' in args:
            result['reactions']=self.service.take_reactions(result['lobby'],args['reactions'] and not args.get('query'))
        return json.dumps(result,ensure_ascii=False)

    def emit(self,count=1,kind='emote'):
        for i in range(count):
            self.service.receive_reaction(reaction(self.service,kind=kind,avatar=self.assets['cat'],
                image=self.assets['item'] if i%2 else self.assets['rocket']))


def check_reaction_setting(f, output):
    page=f.page
    page.emulate_media(reduced_motion='no-preference',color_scheme='light')
    page.set_viewport_size({'width':1280,'height':800})
    f.emit(2);expect(page.locator('.reaction-particle')).to_have_count(2)
    before=f.snapshot()
    page.locator('#settings-button').click()
    control=page.locator('#reactions-enabled')
    expect(control).to_be_checked()
    control.focus();page.keyboard.press('Space')
    expect(control).to_be_enabled();expect(control).not_to_be_checked()
    expect(control).to_be_focused()
    expect(page.locator('.reaction-particle')).to_have_count(0)
    assert f.store.setting('reactions_enabled') is False
    f.emit(10);f.emit(10,kind='meow');f.poll()
    assert page.locator('.reaction-particle').count()==0 and not f.service.reactions
    page.screenshot(path=str(output/'settings-reactions-off-wide.png'))
    page.set_viewport_size({'width':390,'height':740})
    page.emulate_media(color_scheme='dark')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    expect(control).to_be_in_viewport()
    expect(page.get_by_role('button',name='설정 닫기')).to_be_in_viewport()
    page.screenshot(path=str(output/'settings-reactions-off-narrow-dark.png'))
    # The product commits the check state only after the native save reply.
    control.click();expect(control).to_be_checked();expect(control).to_be_enabled()
    assert f.store.setting('reactions_enabled') is True
    assert page.locator('.reaction-particle').count()==0
    page.get_by_role('button',name='설정 닫기').click()
    page.set_viewport_size({'width':1280,'height':800})
    f.poll();same_anchor(before,f.snapshot())
    f.emit(1);f.emit(1,kind='meow')
    expect(page.locator('.reaction-item')).to_have_count(1)
    expect(page.locator('.reaction-meow')).to_have_count(1)
    expect(page.locator('#message-input')).to_have_value('반응이 떠도 계속 쓰는 초안')
    expect(page.locator('.reaction-particle')).to_have_count(0)


def check_continuous_replacement(f, output):
    page=f.page
    page.set_viewport_size({'width':860,'height':800})
    assert page.locator('#reaction-layer').evaluate('(el)=>el.clientWidth')==600
    before=f.snapshot()
    f.emit(16,kind='meow')
    expect(page.locator('.reaction-meow')).to_have_count(16)
    page.evaluate("window.firstParticles=[...document.querySelectorAll('.reaction-particle')]")
    f.emit(4)
    expect(page.locator('.reaction-item')).to_have_count(4)
    assert page.locator('.reaction-particle').count()==16
    assert page.evaluate('firstParticles.slice(0,4).every(el=>!el.isConnected) && firstParticles.slice(4).every(el=>el.isConnected)')
    page.screenshot(path=str(output/'oldest-replaced.png'))
    expect(page.locator('.reaction-particle')).to_have_count(0)
    page.evaluate("""() => {
      window.reactionStats={added:0,peak:0,batches:[]};
      window.reactionObserver=new MutationObserver(records=>{
        const count=records.reduce((n,r)=>n+[...r.addedNodes].filter(el=>el.classList?.contains('reaction-particle')).length,0);
        const active=document.querySelector('#reaction-layer').childElementCount;
        reactionStats.peak=Math.max(reactionStats.peak,active);
        reactionStats.added+=count;
        if(count) reactionStats.batches.push({time:performance.now(),count});
      });
      reactionObserver.observe(document.querySelector('#reaction-layer'),{childList:true});
    }""")
    # Sustained input exceeds the 16 visible slots throughout several lifetimes.
    for _ in range(20):
        f.emit(4)
        page.wait_for_timeout(300)
    page.wait_for_function('() => reactionStats.added === 80')
    expect(page.locator('.reaction-particle')).to_have_count(0)
    stats=page.evaluate('() => {reactionObserver.disconnect(); return reactionStats;}')
    assert stats['peak']==16
    same_anchor(before,f.snapshot())
    expect(page.locator('#message-input')).to_have_value('반응이 떠도 계속 쓰는 초안')
    assert page.locator('.message').count()==60
    return stats


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
                expect(page.locator('.reaction-particle')).to_have_count(24)
                # Shrinking the viewport must also trim existing particles, oldest first.
                page.evaluate("window.wideParticles=[...document.querySelectorAll('.reaction-particle')]")
                page.set_viewport_size({'width':390,'height':740})
                expect(page.locator('.reaction-particle')).to_have_count(10)
                assert page.evaluate('wideParticles.slice(0,14).every(el=>!el.isConnected) && wideParticles.slice(14).every(el=>el.isConnected)')
                expect(page.locator('.reaction-particle')).to_have_count(0)
                page.wait_for_timeout(650)
                assert page.locator('.reaction-particle').count()==0
                page.set_viewport_size({'width':1280,'height':800})
                f.emit(3,kind='meow');expect(page.locator('.reaction-meow')).to_have_count(3)
                f.service.update(dict(f.state,hidden={'fixture-peer':True}))
                expect(page.locator('.reaction-particle')).to_have_count(0)
                f.service.update(f.state);f.poll()
                page.locator('#message-search').fill('검증')
                f.emit(3);f.poll();assert page.locator('.reaction-particle').count()==0
                page.locator('#message-search').fill('');f.poll()
                page.set_viewport_size({'width':390,'height':740})
                page.wait_for_function("() => document.querySelector('.sidebar').getBoundingClientRect().right <= 1")
                f.emit(12);expect(page.locator('.reaction-particle')).to_have_count(10)
                page.evaluate("document.querySelectorAll('.reaction-particle').forEach(el=>{const a=el.getAnimations()[0];a.pause();a.currentTime=1050;})")
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(args.output/'real-items-narrow.png'))
                expect(page.locator('#message-input')).to_have_value('반응이 떠도 계속 쓰는 초안')
                expect(page.locator('.reaction-particle')).to_have_count(0)
                continuous=check_continuous_replacement(f,args.output)
                page.emulate_media(reduced_motion='reduce',color_scheme='dark')
                f.emit(1,kind='meow');expect(page.locator('.reaction-meow')).to_have_count(1)
                particle=page.locator('.reaction-particle')
                assert particle.evaluate('(el)=>getComputedStyle(el).animationName')=='reaction-fade'
                assert particle.evaluate('(el)=>getComputedStyle(el).animationDuration')=='2.2s'
                page.wait_for_timeout(500);page.screenshot(path=str(args.output/'real-items-dark-reduced.png'))
                expect(particle).to_have_count(0)
                check_reaction_setting(f,args.output)
                assert not f.errors and not f.warnings,(f.errors,f.warnings)
                assert f.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==60
                print(json.dumps(dict(passed=True,channel=args.channel,real_local_assets=bool(args.assets),
                    repeated=6,burst=100,peak=24,narrow_peak=10,continuous=continuous,
                    history=60,reaction_setting=True,errors=f.errors,warnings=f.warnings)))
            finally:f.close();browser.close()
    finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
