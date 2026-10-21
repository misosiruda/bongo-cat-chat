"""Actual Qt bridge/controller and renderer, synthetic peers and assets."""
import time

from test_desktop import qt_chat, js, wait_until
from test_reactions import PNG, reaction


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
