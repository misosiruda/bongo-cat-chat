"""Headless product UI screenshots with a synthetic lobby and actual pat service."""
import argparse
from http.server import HTTPServer
import json
from pathlib import Path
import threading
import time

from playwright.sync_api import expect, sync_playwright
from browser_scroll_check import Fixture, Handler, same_anchor
from test_pats import pat


class Pats(Fixture):
    def __init__(self, browser, url):
        super().__init__(browser, url, 40)
        self.service.clock = time.monotonic
        self.service.pats_enabled_since = time.monotonic()
        members = ['fixture-self', 'fixture-peer', 'fixture-third', 'fixture-fourth', 'fixture-fifth', 'fixture-sixth']
        self.state.update(pats_supported=True, members=members,
            profiles={uid: dict(name=name) for uid, name in zip(members, ['두부','모카','밤이','유자','솜이','호두'])})
        self.service.update(self.state)
        self.poll()

    def request(self, raw):
        args = json.loads(raw)
        if args['action'] == 'pat_view':
            self.service.update(self.state)
            return json.dumps(self.service.pat_view(args.get('lobby')), ensure_ascii=False)
        if args['action'] == 'setting' and args['key'] == 'pats_enabled':
            self.service.set_pats_enabled(args['value'])
            return json.dumps({'ok': True})
        return super().request(raw)

    def emit(self):
        self.service.update(self.state)
        for sender, target, count in [('fixture-self','fixture-peer',7), ('fixture-third','fixture-peer',3),
                                      ('fixture-peer','fixture-fourth',12), ('fixture-fifth','fixture-third',2),
                                      ('fixture-fourth','fixture-sixth',5), ('fixture-sixth','fixture-self',1)]:
            for _ in range(count):
                self.service.receive_pat(pat(self.service, sender, target))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('artifacts/pat-alerts'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            try:
                f = Pats(browser, f'http://127.0.0.1:{server.server_port}/')
                try:
                    f.page.locator('#message-input').fill('복복 알림 중에도 유지되는 초안')
                    for width, height, theme in [(1240,840,'light'),(400,500,'light'),(1240,840,'dark'),(400,500,'dark')]:
                        f.page.set_viewport_size(dict(width=width, height=height))
                        f.store.setting('theme', theme)
                        f.poll()
                        f.middle()
                        before = f.snapshot()
                        f.emit()
                        expect(f.page.locator('.pat-row')).to_have_count(3)
                        expect(f.page.locator('#pat-overflow')).to_have_text('+3쌍도 복복 중')
                        same_anchor(before, f.snapshot())
                        assert f.page.locator('#message-input').input_value() == '복복 알림 중에도 유지되는 초안'
                        assert f.page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        assert f.page.locator('.pat-count').evaluate_all('(els)=>els.every(el=>el.getBoundingClientRect().right<=innerWidth)')
                        assert f.page.locator('.composer-region').evaluate('(el)=>el.getBoundingClientRect().bottom<=innerHeight')
                        f.page.screenshot(path=str(args.output / f'slim-{width}-{theme}.png'))
                        expect(f.page.locator('.pat-row')).to_have_count(0)
                        same_anchor(before, f.snapshot())
                        print(f'PASS {width}x{height} {theme}: cap, overflow, expiry, scroll, draft', flush=True)
                    assert not f.errors, f.errors
                    assert not f.warnings, f.warnings
                finally:
                    f.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    main()
