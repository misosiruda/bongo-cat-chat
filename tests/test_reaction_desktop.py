"""Actual Qt bridge/controller and renderer, synthetic peers and assets."""
import time
import json
import sqlite3

import pytest

from test_desktop import qt_chat, js, wait_until
from test_reactions import PNG, reaction
from bongo_chat.reactions import MAX_REACTIONS


def test_reaction_switch_clears_effects_preserves_draft_and_survives_reload(qt_chat):
    app, controller, page = qt_chat
    service = controller.service
    service.update(dict(service.state, profiles={'fixture-peer': dict(name='합성 고양이', avatar=PNG)}))
    js(app, page, "document.querySelector('#message-input').value='효과 설정 중 초안';document.querySelector('#message-input').dispatchEvent(new Event('input'))")
    wait_until(app, lambda: controller.store.draft('fixture-self', 'fixture-room-a') == '효과 설정 중 초안')
    service.receive_reaction(reaction(service, observed=time.monotonic()))
    service.receive_reaction(reaction(service, kind='emote', image=PNG, observed=time.monotonic()))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.reaction-particle').length") == 2)
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#reactions-enabled').focus();document.querySelector('#reactions-enabled').click()")
    wait_until(app, lambda: controller.store.setting('reactions_enabled') is False)
    wait_until(app, lambda: js(app, page, "!document.querySelector('#reactions-enabled').checked && !document.querySelector('#reactions-enabled').disabled"))
    assert js(app, page, "document.querySelectorAll('.reaction-particle').length") == 0
    assert js(app, page, "document.activeElement.id") == 'reactions-enabled'
    assert js(app, page, "document.querySelector('#settings-dialog').open")
    assert js(app, page, "document.querySelector('#message-input').value") == '효과 설정 중 초안'
    assert all(service.notifications.values())
    for kind in ('meow', 'emote'):
        service.receive_reaction(reaction(service, kind=kind, image=PNG, observed=time.monotonic()))
    assert not service.reactions
    page.triggerAction(page.WebAction.Reload)
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.message-bubble').length") == 1)
    assert js(app, page, "document.querySelector('#reactions-enabled').checked") is False
    assert js(app, page, "document.querySelector('#message-input').value") == '효과 설정 중 초안'
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#reactions-enabled').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#reactions-enabled').checked && !document.querySelector('#reactions-enabled').disabled"))
    assert controller.store.setting('reactions_enabled') is True
    assert js(app, page, "document.querySelectorAll('.reaction-particle').length") == 0
    service.receive_reaction(reaction(service, observed=time.monotonic()))
    service.receive_reaction(reaction(service, kind='emote', image=PNG, observed=time.monotonic()))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.reaction-particle').length") == 2)
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 1


@pytest.mark.parametrize('enabled', [False, True])
def test_reaction_switch_failed_save_restores_previous_value(qt_chat, monkeypatch, enabled):
    app, controller, page = qt_chat
    controller.service.set_reactions_enabled(enabled)
    wait_until(app, lambda: js(app, page, "document.querySelector('#reactions-enabled').checked") is enabled)
    original = controller.store.setting

    def failing(key, value=None, default=None):
        if key == 'reactions_enabled' and value is not None:
            raise sqlite3.OperationalError('synthetic write failure')
        return original(key, value, default)

    monkeypatch.setattr(controller.store, 'setting', failing)
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#reactions-enabled').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#reaction-save-status').textContent.includes('이전 값')"))
    assert js(app, page, "document.querySelector('#reactions-enabled').checked") is enabled
    assert js(app, page, "document.querySelector('#reactions-enabled').disabled") is False
    assert controller.service.reactions_enabled is enabled
    assert original('reactions_enabled') is enabled
    monkeypatch.setattr(controller.store, 'setting', original)
    js(app, page, "document.querySelector('#reactions-enabled').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#reactions-enabled').checked") is not enabled)
    assert original('reactions_enabled') is not enabled


def test_old_view_reply_cannot_reenable_or_replay_after_toggle(qt_chat):
    app, controller, page = qt_chat
    service = controller.service
    service.update(dict(service.state, profiles={'fixture-peer': dict(name='합성 고양이', avatar=PNG)}))
    js(app, page, 'window.holdNextView=true')
    service.receive_reaction(reaction(service, observed=time.monotonic()))
    wait_until(app, lambda: js(app, page, "typeof window.releaseView === 'function'"))
    js(app, page, "document.querySelector('#settings-button').click();document.querySelector('#reactions-enabled').click()")
    wait_until(app, lambda: js(app, page, "!document.querySelector('#reactions-enabled').checked && !document.querySelector('#reactions-enabled').disabled"))
    js(app, page, "document.querySelector('#reactions-enabled').click()")
    wait_until(app, lambda: js(app, page, "document.querySelector('#reactions-enabled').checked && !document.querySelector('#reactions-enabled').disabled"))
    js(app, page, "window.addedReactions=0;new MutationObserver(records=>{for(const record of records) addedReactions+=record.addedNodes.length;}).observe(document.querySelector('#reaction-layer'),{childList:true});window.releaseView()")
    service.receive_reaction(reaction(service, observed=time.monotonic()))
    wait_until(app, lambda: js(app, page, "document.querySelectorAll('.reaction-particle').length") == 1)
    assert js(app, page, 'window.addedReactions') == 1
    assert service.reactions_enabled


def test_native_reaction_setting_rejects_non_booleans(qt_chat):
    _, controller, _ = qt_chat
    for value in ('false', 0, 1, [], {}, None):
        result = json.loads(controller.request(json.dumps(dict(action='setting', key='reactions_enabled', value=value))))
        assert result == {'error': 'request_failed'}
        assert controller.service.reactions_enabled


def test_qt_particles_use_sender_cat_and_item_without_notifications_or_log(qt_chat, monkeypatch):
    app, controller, page=qt_chat
    service=controller.service
    profiles=dict(service.state['profiles'])
    profiles['fixture-peer']=dict(name='합성 고양이',avatar=PNG)
    service.update(dict(service.state,profiles=profiles))
    notifications=[]
    monkeypatch.setattr(controller.notifications,'incoming',lambda item:notifications.append(item))
    before=controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]
    js(app,page,"document.querySelector('#message-input').value='한글 초안';document.querySelector('#message-input').focus()")
    for _ in range(5):
        controller.events.put(reaction(service,kind='emote',image=PNG,item=927,observed=time.monotonic()))
    wait_until(app,lambda:js(app,page,"document.querySelectorAll('.reaction-particle').length") == 5)
    assert js(app,page,"document.querySelectorAll('.reaction-cat').length === 5 && document.querySelectorAll('.reaction-item').length === 5")
    assert js(app,page,"getComputedStyle(document.querySelector('#reaction-layer')).pointerEvents")=='none'
    assert js(app,page,"document.querySelector('#message-input').value")=='한글 초안'
    assert not notifications
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==before
    wait_until(app,lambda:js(app,page,"document.querySelectorAll('.reaction-particle').length") == 0)
    assert not service.reactions


def test_delayed_bridge_reply_cannot_replay_an_expired_reaction(qt_chat):
    app, controller, page=qt_chat
    service=controller.service
    service.update(dict(service.state,profiles={'fixture-peer':dict(name='합성 고양이',avatar=PNG)}))
    js(app,page,'window.holdNextView=true')
    service.receive_reaction(reaction(service,observed=time.monotonic()))
    wait_until(app,lambda:js(app,page,"typeof window.releaseView === 'function'"))
    assert not service.reactions
    deadline=time.monotonic()+1.4
    wait_until(app,lambda:time.monotonic()>deadline)
    js(app,page,'window.releaseView()')
    deadline=time.monotonic()+.25
    wait_until(app,lambda:time.monotonic()>deadline)
    assert js(app,page,"document.querySelectorAll('.reaction-particle').length")==0


def test_full_qt_layer_replaces_oldest_particles_without_waiting(qt_chat, monkeypatch):
    app, controller, page=qt_chat
    service=controller.service
    service.update(dict(service.state,profiles={'fixture-peer':dict(name='합성 고양이',avatar=PNG)}))
    notifications=[]
    monkeypatch.setattr(controller.notifications,'incoming',lambda item:notifications.append(item))
    before=controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]
    for _ in range(MAX_REACTIONS):
        service.receive_reaction(reaction(service,observed=time.monotonic()))
    wait_until(app,lambda:js(app,page,"document.querySelectorAll('.reaction-particle').length")==24)
    js(app,page,"window.firstParticles=[...document.querySelectorAll('.reaction-particle')]")
    for _ in range(4):
        controller.events.put(reaction(service,kind='emote',image=PNG,observed=time.monotonic()))
    wait_until(app,lambda:js(app,page,"document.querySelectorAll('.reaction-item').length")==4)
    assert js(app,page,"document.querySelectorAll('.reaction-particle').length")==24
    assert js(app,page,"firstParticles.slice(0,4).every(el=>!el.isConnected) && firstParticles.slice(4).every(el=>el.isConnected)")
    assert not notifications
    assert controller.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==before
    wait_until(app,lambda:js(app,page,"document.querySelectorAll('.reaction-particle').length")==0)
    assert not service.reactions
