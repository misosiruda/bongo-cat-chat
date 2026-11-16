"""Render README examples from product UI and fictional data; never connect to Steam."""
import argparse
import base64
from contextlib import ExitStack
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bongo_chat import __version__
from bongo_chat.localization import ENGLISH
from bongo_chat.service import ChatService
from bongo_chat.store import Store


def avatars():
    # Existing fictional artwork is a 2x2 sprite sheet. No game art or account data.
    sheet = QImage(str(ROOT / 'docs/design/assets/cat-avatars.png'))
    result = []
    for x, y in ((0, 0), (1, 0), (0, 1)):
        tile = sheet.copy(x * sheet.width() // 2, y * sheet.height() // 2,
                          sheet.width() // 2, sheet.height() // 2)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        tile.save(buffer, 'PNG')
        result.append('data:image/png;base64,' + base64.b64encode(bytes(buffer.data())).decode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/screenshots')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ui = ROOT / 'src/bongo_chat/ui'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == '/channel.js':
                body = b'window.qt={webChannelTransport:{}};window.QWebChannel=function(_,cb){cb({objects:{bridge:{request:(raw,done)=>window.fixtureRequest(raw).then(done)}}});};'
                mime = 'text/javascript'
            elif self.path in ('/', '/index.html', '/app.js', '/messenger.css', '/app-icon.png', '/favicon.ico'):
                name = self.path.lstrip('/') or 'index.html'
                body = (ui / name).read_bytes()
                if name == 'index.html':
                    body = body.replace(b'qrc:///qtwebchannel/qwebchannel.js', b'/channel.js')
                mime = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
                        '.png': 'image/png', '.ico': 'image/x-icon'}[Path(name).suffix]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.end_headers()
            self.wfile.write(body)
    with TemporaryDirectory() as temp, sync_playwright() as p, ExitStack() as resources:
        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        resources.callback(server.server_close)
        resources.callback(server.shutdown)
        browser = p.chromium.launch(executable_path=str(args.browser), headless=True)
        resources.callback(browser.close)
        portraits = avatars()
        texts = {
            'ko': ['창가 자리 비었어요. 여기 앉아요!', '두부야, 오늘 모자 새로 썼네?', '응! 방금 나온 식빵 모자야.',
                   '오, 우리 셋 다 다른 모자네!', '그럼 이대로 사진 한 장 찍자.'],
            'en': ['There is a seat by the window. Come sit here!', 'Tofu, is that a new hat?', 'Yes! I just got this toast hat.',
                   'Oh, we all have different hats!', 'Then let us take a photo together.'],
        }
        for language in ('ko', 'en'):
            store = Store(Path(temp) / f'{language}.sqlite3')
            resources.callback(store.close)
            store.setting('theme', 'light')
            service = ChatService(store, clock=lambda: 100)
            names = ['모카', '두부', '밤이'] if language == 'ko' else ['Mocha', 'Tofu', 'Chestnut']
            ids = ['fixture-self', 'fixture-tofu', 'fixture-chestnut']
            service.update(dict(state='ready', account=ids[0], lobby='fixture-room', generation='fixture-generation',
                                name='햇살 드는 창가' if language == 'ko' else 'Sunny windowsill',
                                hidden={uid: False for uid in ids}, hidden_ok=True, connected=True,
                                lobby_verified=True, members=ids, send_enabled=True,
                                profiles={uid: {'name': name, 'avatar': avatar}
                                          for uid, name, avatar in zip(ids, names, portraits)}))
            for i, (sender, text) in enumerate(zip([1, 0, 1, 2, 0], texts[language])):
                service.receive(dict(id=f'fixture-{i}', sender=ids[sender], text=text,
                                     received=datetime(2026, 11, 14, 15, 26 + i).timestamp(), context=service.context()))
            def request(raw):
                data = json.loads(raw)
                if data['action'] != 'view':
                    return json.dumps({'ok': True})
                result = service.view(data.get('lobby'), data.get('query', ''), data.get('before'),
                                      data.get('start'), data.get('seen'), data.get('limit', 100))
                result.update(language=language, language_preference=language,
                              translations=ENGLISH if language == 'en' else {},
                              update={'state': 'current', 'current': __version__, 'allowed': False})
                return json.dumps(result, ensure_ascii=False)
            page = browser.new_page(viewport={'width': 1240, 'height': 840}, device_scale_factor=1,
                                    timezone_id='Asia/Seoul', locale='ko-KR' if language == 'ko' else 'en-US')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.expose_function('fixtureRequest', request)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect(page).to_have_title('Bongo Cat Chat')
            expect(page.locator('.message-bubble')).to_have_count(5)
            expect(page.locator('html')).to_have_attribute('lang', language)
            page.wait_for_function('Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)')
            for size, width, height in [('default', 1240, 840), ('narrow', 720, 640), ('minimum', 400, 500)]:
                page.set_viewport_size({'width': width, 'height': height})
                page.locator('#message-scroll').evaluate('(el) => el.scrollTop = el.scrollHeight')
                page.evaluate('document.fonts.ready')
                page.wait_for_timeout(300)
                assert page.locator('#app').evaluate('(el) => el.scrollWidth <= el.clientWidth')
                assert '개발판' not in page.locator('#connection-notice').inner_text()
                assert 'Development build' not in page.locator('#connection-notice').inner_text()
                page.screenshot(path=str(args.output / f'chat-{language}-{size}.png'))
            assert not errors, errors
            page.close()
    print('Captured six product UI screenshots using fictional conversations and artwork.')


if __name__ == '__main__':
    main()
