"""Product UI regression with synthetic peers and a fake protocol adapter.

Browser plugin not available: run the existing local Playwright/Chrome path.
No game/Steam worker, external protocol handler or personal data is used.
"""
import argparse
from http.server import HTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright

from browser_scroll_check import Fixture, Handler, same_anchor


SELF, PEER, SECOND = '76561190000000000', '76561190000000001', '76561190000000002'


class Profiles(Fixture):
    def __init__(self, browser, url):
        self.calls, self.payloads, self.fail = [], [], False
        super().__init__(browser, url, 0, {'width': 1240, 'height': 840})
        self.state = dict(self.state, account=SELF, members=[SELF, PEER, SECOND], name='가상 프로필 검증', notice='read_only', hidden_ok=False, send_enabled=False,
                          hidden={PEER: False, SECOND: False, '76561190000000003': None},
                          profiles={SELF: {'name': '시험 계정'}, PEER: {'name': '같은 이름의 고양이'},
                                    SECOND: {'name': '같은 이름의 고양이'}})
        self.service.update(self.state)
        for index in range(60):
            self.service.receive(dict(id=f'profile-{index}', sender=PEER if index % 2 == 0 else SECOND,
                                      text=f'가상 프로필 대화 {index:02d}', context=self.service.context()))
        expect(self.page.locator('.message')).to_have_count(60)
        expect(self.page.locator('.profile-name')).to_have_count(60)

    def request(self, raw):
        args = json.loads(raw)
        if args['action'] != 'open_steam_profile':
            return super().request(raw)
        self.payloads.append(args)
        try:
            self.calls.append(self.service.profile_uri(args['steam_id'], args['context']))
            return json.dumps({'error': 'steam_profile_failed'} if self.fail else {'ok': True})
        except ValueError as error:
            return json.dumps({'error': str(error)})


def check_actions(f):
    page = f.page
    page.locator('#message-input').fill('작성 중인 한글')
    page.locator('#participants-button').click()
    page.locator(f'#participant-more-{PEER}').click()
    buttons = page.locator('.participant-profile')
    expect(buttons).to_have_count(1)
    buttons.first.focus()
    page.keyboard.press('Enter')
    expect(page.locator('#toast')).to_contain_text('Steam에 프로필 열기를 요청')
    assert f.calls == ['steam://url/SteamIDPage/' + PEER]
    page.keyboard.press('Space')
    page.wait_for_function('() => document.querySelectorAll(".participant-profile")[0].getAttribute("aria-busy")==="false"')
    assert len(f.calls) == 2
    buttons.first.dblclick()
    page.wait_for_timeout(150)
    assert len(f.calls) == 3  # The second click of a double click is ignored.
    page.keyboard.press('Escape')
    page.locator(f'#participant-more-{SECOND}').click()
    buttons.first.click()
    expect(page.locator('#participants-dialog')).to_be_visible()
    expect(buttons.first).to_have_attribute('aria-busy', 'false')
    assert f.calls[-1] == 'steam://url/SteamIDPage/' + SECOND
    assert f.payloads[0]['steam_id'] == PEER and f.payloads[0]['context'] == f.service.context()
    assert f.store.db.execute('SELECT count(*) FROM messages WHERE own=1').fetchone()[0] == 0
    page.keyboard.press('Escape')
    page.locator(f'#participant-more-{PEER}').click()
    buttons.first.focus()
    for index in range(3):
        profiles = dict(f.state['profiles'], **{PEER: {'name': f'가상 이름 갱신 {index}'}})
        f.service.update(dict(f.state, profiles=profiles))
        expect(buttons.first).to_have_accessible_name(f'Steam 프로필 열기 · 가상 이름 갱신 {index}')
        expect(buttons.first).to_be_focused()
    f.service.update(dict(f.state, profiles={SELF: f.state['profiles'][SELF], SECOND: f.state['profiles'][SECOND]}))
    expect(buttons).to_have_count(0)
    expect(page.get_by_role('button', name='참여자 목록 닫기')).to_be_focused()
    f.service.update(f.state)
    expect(page.locator('.participant-more')).to_have_count(2)
    page.keyboard.press('Escape')
    expect(page.locator('#participants-dialog')).not_to_be_visible()
    assert page.locator('#message-input').input_value() == '작성 중인 한글'


def check_preservation_and_boundaries(f):
    page = f.page
    page.locator('#message-search').fill('대화')
    expect(page.locator('mark')).to_have_count(60)
    f.middle()
    anchor = f.snapshot()
    button = page.locator('#' + anchor['id']).locator('.profile-name')
    button.scroll_into_view_if_needed()
    before = f.snapshot()
    f.fail = True
    button.click()
    expect(page.locator('#toast')).to_contain_text('열지 못했어요')
    f.poll()
    same_anchor(before, f.snapshot())
    assert page.locator('#message-input').input_value() == '작성 중인 한글'
    assert page.locator('#message-search').input_value() == '대화'
    expect(page.locator('#send-button')).to_be_disabled()
    assert not f.service.storage_error
    f.fail = False
    count = len(f.calls)
    page.evaluate('window.oldProfile=document.querySelector(".profile-name")')
    f.service.update(dict(f.state, generation='new-generation'))
    page.wait_for_function('() => document.querySelector(".profile-name")?.dataset.profileContext.includes("new-generation")')
    page.evaluate('window.oldProfile.click()')
    f.poll()
    assert len(f.calls) == count
    f.store.session('archive-session', SELF, 'archived-room', '보관된 가상 로비')
    f.poll()
    page.get_by_role('button', name='보관된 가상 로비', exact=True).click()
    expect(page.locator('#room-title')).to_have_text('보관된 가상 로비')
    expect(page.locator('.steam-profile-action')).to_have_count(0)
    page.evaluate('window.oldProfile.click()')
    assert len(f.calls) == count
    page.get_by_role('button', name='가상 프로필 검증', exact=True).click()
    expect(page.locator('.profile-name')).to_have_count(60)
    f.service.updated -= 3
    expect(page.locator('.steam-profile-action')).to_have_count(0)
    f.service.update(f.state)
    expect(page.locator('.profile-name')).to_have_count(60)
    page.locator('.profile-avatar').first.click()
    expect(page.locator('#toast')).to_contain_text('Steam에 프로필 열기를 요청')
    assert f.calls[-1] == 'steam://url/SteamIDPage/' + PEER
    page.locator('.profile-name').first.focus()
    page.keyboard.press('Enter')
    expect(page.locator('.profile-name').first).to_have_attribute('aria-busy', 'false')
    assert f.calls[-1] == 'steam://url/SteamIDPage/' + PEER


def check_layouts(f, output):
    page = f.page
    expect(page.locator('#toast')).not_to_be_visible(timeout=5000)
    for width, height in [(1240, 840), (960, 540), (400, 500)]:
        page.set_viewport_size({'width': width, 'height': height})
        for theme in ['light', 'dark']:
            f.store.setting('theme', theme)
            expect(page.locator('html')).to_have_attribute('data-theme', theme)
            page.locator('#participants-button').click()
            expect(page.locator('.participant-more').first).to_be_in_viewport(ratio=1)
            assert page.locator('#participant-list').evaluate('el=>el.scrollWidth<=el.clientWidth')
            page.get_by_role('button', name='참여자 목록 닫기').focus()
            page.keyboard.press('Tab')
            expect(page.locator('.participant-more').first).to_be_focused()
            page.keyboard.press('Enter')
            expect(page.locator('.participant-profile').first).to_be_focused()
            assert page.locator('.participant-profile').first.evaluate('el=>getComputedStyle(el).outlineStyle') != 'none'
            page.screenshot(path=str(output / f'profiles-{theme}-{width}x{height}.png'))
            page.keyboard.press('Escape')
            expect(page.locator('.participant-more').first).to_be_focused()
            page.keyboard.press('Escape')
            assert page.locator('#message-scroll').evaluate('el=>el.scrollWidth<=el.clientWidth')
        page.screenshot(path=str(output / f'messages-dark-{width}x{height}.png'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(args.browser), headless=True)
            f = Profiles(browser, url)
            try:
                check_actions(f)
                check_preservation_and_boundaries(f)
                check_layouts(f, args.output)
                assert not f.errors, f.errors
                assert not f.warnings, f.warnings
                assert f.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 60
                print(json.dumps(dict(result='passed', browser='Chrome/Playwright', url=url,
                    viewports=['1240x840', '960x540', '400x500'], themes=['light', 'dark'],
                    keyboard=['Enter', 'Space'], screenshots=9, console_errors=f.errors,
                    console_warnings=f.warnings, protocol_handler='mock', game_worker=False)))
            finally:
                f.close(); browser.close()
    finally:
        server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()
