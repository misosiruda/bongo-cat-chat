"""Translation coverage plus actual Qt language switching; no game connection."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

import pytest

from bongo_chat import localization
from bongo_chat.desktop import Controller, legal_document
from bongo_chat.localization import ENGLISH, resolve_language
from bongo_chat.store import Store
from test_core import received
from test_desktop import qt_chat, js, wait_until


@pytest.mark.parametrize('preference,system,expected', [
    ('system','ko-KR','ko'), ('system','ko_KR','ko'), ('system','en-GB','en'),
    ('system','ja-JP','en'), ('system','','en'), ('en','ko-KR','en'), ('ko','en-US','ko'),
])
def test_language_resolution(preference, system, expected):
    assert resolve_language(preference, system) == expected


def test_english_legal_documents_are_available_without_network():
    name,text=legal_document('privacy','en')
    assert name=='PRIVACY.en.md'
    assert 'unencrypted SQLite' in text and 'Language preferences' in text
    name,text=legal_document('licenses','en')
    assert 'Source checkout' in text and 'MIT License' in text
    assert 'Corresponding' in text or 'corresponding' in text


def test_catalog_covers_app_owned_text_and_preserves_placeholders():
    root=Path(__file__).resolve().parents[1]/'src/bongo_chat'
    keys=set(re.findall(r"\bt\('([^'\n]+)'", (root/'ui/app.js').read_text(encoding='utf-8')))
    class Shell(HTMLParser):
        def handle_data(self, text):
            if re.search('[가-힣]',text) and text.strip()!='한국어': keys.add(text.strip())
        def handle_starttag(self, tag, attrs):
            for attr,text in attrs:
                if attr in ('aria-label','placeholder','title') and re.search('[가-힣]',text): keys.add(text)
    Shell().feed((root/'ui/index.html').read_text(encoding='utf-8'))
    for filename in ('desktop.py','windows_notifications.py'):
        keys.update(re.findall(r"translate\('([^'\n]+)'",(root/filename).read_text(encoding='utf-8')))
    assert keys <= ENGLISH.keys(), sorted(keys-ENGLISH.keys())
    for key,value in ENGLISH.items():
        assert value.strip() and not re.search('[가-힣]',value), key
        assert set(re.findall(r'\{\w+\}',key)) == set(re.findall(r'\{\w+\}',value)), key


def choose_language(app, page, value):
    js(app,page,f"document.querySelector('#language-select').value={json.dumps(value)};document.querySelector('#language-select').dispatchEvent(new Event('change'))")
    wait_until(app,lambda:js(app,page,"!document.querySelector('#language-select').disabled"))


def test_switch_preserves_user_text_search_draft_scroll_and_reload(qt_chat):
    app,controller,page=qt_chat
    service=controller.service
    # Deliberately match catalog keys: user data must never be translated.
    service.update(dict(service.state, profiles={'fixture-peer':{'name':'설정'}},name='게임 로비'))
    controller.store.db.execute('UPDATE sessions SET name=?', ('게임 로비',))
    controller.store.db.commit()
    received(service,'설정')
    js(app,page,"document.querySelector('#message-input').value='설정';document.querySelector('#message-input').dispatchEvent(new Event('input'))")
    wait_until(app,lambda:controller.store.draft('fixture-self','fixture-room-a')=='설정')
    js(app,page,"document.querySelector('#message-search').value='설정';document.querySelector('#message-search').dispatchEvent(new Event('input'))")
    wait_until(app,lambda:js(app,page,"document.querySelectorAll('.message-bubble').length") == 1)
    before=js(app,page,"document.querySelector('#message-scroll').scrollTop")
    js(app,page,"document.querySelector('#settings-button').click();document.querySelector('#language-select').focus()")
    choose_language(app,page,'en')
    assert controller.language=='en' and controller.store.setting('language')=='en'
    assert js(app,page,"document.documentElement.lang")=='en'
    assert js(app,page,"document.querySelector('#settings-title').textContent")=='Settings'
    assert js(app,page,"document.querySelector('.message-bubble').textContent")=='설정'
    assert js(app,page,"document.querySelector('.message-meta strong').textContent")=='설정'
    assert js(app,page,"document.querySelector('#room-title').textContent")=='게임 로비'
    assert js(app,page,"document.querySelector('#message-input').value")=='설정'
    assert js(app,page,"document.querySelector('#message-search').value")=='설정'
    assert js(app,page,"document.querySelector('#message-scroll').scrollTop")==before
    assert js(app,page,"document.querySelector('#language-status').textContent")=='Language preference saved.'
    assert js(app,page,"document.activeElement.id")=='language-select'
    assert 'Development build' in page.title()
    assert 'Development build' in page.parent().windowTitle()
    choose_language(app,page,'ko')
    assert js(app,page,"document.querySelector('#settings-title').textContent")=='설정'
    choose_language(app,page,'en')
    page.triggerAction(page.WebAction.Reload)
    wait_until(app,lambda:js(app,page,"document.documentElement.lang")=='en')
    assert js(app,page,"document.querySelector('#language-select').value")=='en'
    assert js(app,page,"document.querySelector('#message-input').value")=='설정'
    assert not page.console_errors


def test_language_save_failure_and_invalid_value_keep_previous_choice(qt_chat,monkeypatch):
    app,controller,page=qt_chat
    choose_language(app,page,'en')
    original=controller.store.setting
    def fail(key,value=None,default=None):
        if key=='language' and value is not None: raise sqlite3.OperationalError('synthetic failure')
        return original(key,value,default)
    monkeypatch.setattr(controller.store,'setting',fail)
    choose_language(app,page,'ko')
    assert controller.language=='en' and original('language')=='en'
    assert js(app,page,"document.documentElement.lang")=='en'
    assert js(app,page,"document.querySelector('#language-select').value")=='en'
    assert 'Could not save' in js(app,page,"document.querySelector('#language-status').textContent")
    for value in ('fr',None,True,[],{}):
        assert 'error' in json.loads(controller.request(json.dumps({'action':'setting','key':'language','value':value})))
    assert controller.language=='en'


def test_system_default_and_explicit_choice_survive_controller_restart(tmp_path,monkeypatch):
    # QApplication is created by the imported fixture's helpers in other tests;
    # create it explicitly so this test also works by itself.
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(localization,'QLocale',SimpleNamespace(system=lambda:SimpleNamespace(uiLanguages=lambda:['en-US'])))
    controller=Controller(tmp_path,offline=True)
    try:
        assert controller.language=='en'
        result=controller.dispatch({'action':'view','language':'ko'})
        assert result['translations']==ENGLISH
        assert 'translations' not in controller.dispatch({'action':'view','language':'en'})
        controller.dispatch({'action':'setting','key':'language','value':'ko'})
    finally: controller.close()
    controller=Controller(tmp_path,offline=True)
    try:
        assert controller.language=='ko'
        controller.dispatch({'action':'setting','key':'language','value':'system'})
        assert controller.language=='en'
    finally: controller.close()
    app.processEvents()


def test_unreadable_language_setting_keeps_app_available_with_storage_error(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    original=Store.setting
    def fail(self,key,value=None,default=None):
        if key=='language':raise sqlite3.OperationalError('synthetic read failure')
        return original(self,key,value,default)
    monkeypatch.setattr(Store,'setting',fail)
    controller=Controller(tmp_path,offline=True)
    try:
        assert controller.language=='ko' and controller.language_preference=='system'
        result=controller.dispatch({'action':'view'})
        assert result['storage_error'] and not result['can_send']
    finally:controller.close()
    app.processEvents()
