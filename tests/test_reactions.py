"""Synthetic reaction packets/assets only. No lobby traffic or game resources."""
import json
import sqlite3
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from bongo_chat.protocol import decode_event, decode, encode, InvalidMessage
from bongo_chat.reactions import ReactionAssets, MAX_REACTIONS
from bongo_chat.service import ChatService
from bongo_chat.store import Store
from test_core import service, store, state

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=='


def reaction(service, **changes):
    return dict(dict(type='reaction', kind='meow', text='야옹 야옹', avatar=PNG,
        id=str(uuid4()), sender='fixture-peer', context=service.context(), observed=100.0), **changes)


def connect(service):
    service.update(state(profiles={'fixture-peer': {'name': '합성 고양이', 'avatar': PNG}}))


@pytest.mark.parametrize('enabled', [False, True])
def test_reaction_setting_defaults_on_and_survives_reopen(tmp_path, enabled):
    path = tmp_path / 'history.sqlite3'
    store = Store(path)
    service = ChatService(store)
    assert service.view()['reactions_enabled'] is True
    service.set_reactions_enabled(enabled)
    store.close()
    reopened = Store(path)
    try:
        assert ChatService(reopened).view()['reactions_enabled'] is enabled
        assert reopened.db.execute('PRAGMA user_version').fetchone()[0] == 1
    finally:
        reopened.close()


def test_off_discards_pending_and_inflight_reactions_without_changing_chat(service):
    connect(service)
    before = service.view()
    service.receive_reaction(reaction(service))
    service.set_reactions_enabled(False)
    assert not service.reactions
    service.receive_reaction(reaction(service, kind='emote', image=PNG))
    assert not service.reactions
    assert not service.take_reactions(service.context()['lobby'], True)
    # An asset/IPC reply observed while OFF can arrive after enabling again.
    delayed = reaction(service, observed=100.1)
    service.clock = lambda: 100.2
    service.set_reactions_enabled(True)
    service.receive_reaction(delayed)
    assert not service.reactions
    for kind in ('meow', 'emote'):
        service.receive_reaction(reaction(service, kind=kind, image=PNG, observed=100.3))
    # Future observations must still be rejected by the existing boundary.
    assert not service.reactions
    service.clock = lambda: 100.4
    for kind in ('meow', 'emote'):
        service.receive_reaction(reaction(service, kind=kind, image=PNG, observed=100.3))
    assert len(service.take_reactions(service.context()['lobby'], True)) == 2
    after = service.view()
    assert {key: value for key, value in after.items() if key != 'revision'} == {
        key: value for key, value in before.items() if key != 'revision'}
    assert service.store.db.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    assert service.store.db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0


@pytest.mark.parametrize('enabled', [False, True])
def test_reaction_setting_write_failure_preserves_committed_value(service, monkeypatch, enabled):
    connect(service)
    service.set_reactions_enabled(enabled)
    service.receive_reaction(reaction(service))
    before, pending = service.view(), list(service.reactions)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic setting write failure')

    with monkeypatch.context() as patch:
        patch.setattr(service.store, 'setting', fail)
        with pytest.raises(sqlite3.OperationalError):
            service.set_reactions_enabled(not enabled)
    assert service.view() == before
    assert list(service.reactions) == pending
    assert service.store.setting('reactions_enabled') is enabled


def test_reaction_setting_read_failure_stays_off_until_recovery(store, monkeypatch):
    store.setting('reactions_enabled', False)
    original = store.setting

    def read(key, *args, **kwargs):
        if key == 'reactions_enabled':
            raise sqlite3.OperationalError('synthetic setting read failure')
        return original(key, *args, **kwargs)

    monkeypatch.setattr(store, 'setting', read)
    service = ChatService(store, clock=lambda: 100)
    connect(service)
    assert service.storage_error
    assert service.view()['reactions_enabled'] is False
    service.receive_reaction(reaction(service))
    assert not service.reactions
    monkeypatch.setattr(store, 'setting', original)
    service.recover_storage()
    assert not service.storage_error
    assert service.reactions_enabled is False


@pytest.mark.parametrize('value', ['false', 0, 1, [], {}, None])
def test_reaction_setting_rejects_non_boolean_values(service, value):
    with pytest.raises(ValueError, match='invalid_setting'):
        service.set_reactions_enabled(value)
    assert service.reactions_enabled is True
    assert service.store.setting('reactions_enabled') is None


@pytest.mark.parametrize('item', ['1','927','2147483647'])
def test_item_channel_is_separate_from_text(item):
    raw=json.dumps({'Channel':6,'Message':item}).encode()
    assert decode_event(raw)=={'type':'reaction','kind':'emote','item':int(item)}
    assert decode(raw) is None
    assert decode_event(encode('야옹 야옹'))['kind']=='meow'
    assert decode_event(encode('야옹 야옹 해주세요'))['type']=='message'


@pytest.mark.parametrize('item', [0, 927, True, None, '', '0', '-1', '+1', '01', ' 927', '9.0', '９２７', '2147483648', '9'*4000])
def test_invalid_item_packets_are_rejected(item):
    with pytest.raises(InvalidMessage):
        decode_event(json.dumps({'Channel':6,'Message':item}).encode())


def test_each_repeat_is_transient_with_no_history_receipts_unread_or_revision(service):
    connect(service);before=service.view();revision=service.revision
    event=reaction(service)
    service.receive_reaction(event);service.receive_reaction(event)
    for _ in range(5):service.receive_reaction(reaction(service))
    result=service.take_reactions(service.context()['lobby'], True)
    assert len(result)==6 and len({row['id'] for row in result})==6
    assert not service.take_reactions(service.context()['lobby'],True)
    assert service.view()==before and service.revision==revision
    assert service.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    assert service.store.db.execute('SELECT count(*) FROM receipts').fetchone()[0]==0


@pytest.mark.parametrize('change', ['hidden','privacy','departed','generation','expired','future','stale','unverified'])
def test_pending_reactions_recheck_boundaries_before_delivery(service, change):
    connect(service);service.receive_reaction(reaction(service))
    if change=='hidden':service.update(dict(service.state,hidden={'fixture-peer':True}))
    if change=='privacy':service.update(dict(service.state,privacy_ready=False))
    if change=='departed':service.update(dict(service.state,profiles={}))
    if change=='generation':service.update(dict(service.state,generation='new'))
    if change in ('expired','future','stale'):service.clock=lambda: {'expired':101.2,'future':99,'stale':103}[change]
    if change=='unverified':service.update(dict(service.state,lobby_verified=False))
    assert not service.take_reactions(service.context()['lobby'],True)


def test_overload_drops_without_backlog_and_nonlive_view_discards(service):
    connect(service)
    for _ in range(100):service.receive_reaction(reaction(service))
    assert len(service.reactions)==MAX_REACTIONS
    assert not service.take_reactions('archive',True)
    assert not service.take_reactions(service.context()['lobby'],True)
    service.receive_reaction(reaction(service))
    assert not service.take_reactions(service.context()['lobby'],False)


def test_overload_keeps_newest_at_both_asset_and_delivery_boundaries(service):
    connect(service)
    loader=ReactionAssets(clock=lambda:100)
    events=[reaction(service) for _ in range(100)]
    for event in events:
        loader.add(event)
        service.receive_reaction(event)
    expected=[event['id'] for event in events[-MAX_REACTIONS:]]
    ready=loader.ready(service.state,NS(),NS())
    assert [event['id'] for event in ready]==expected
    assert not loader.pending
    # Invalid input and duplicates must not evict valid pending reactions.
    service.receive_reaction(events[-1])
    service.receive_reaction(reaction(service,avatar=None))
    service.receive_reaction(reaction(service,observed=98))
    assert [event['id'] for event in service.take_reactions(service.context()['lobby'],True)]==expected
    assert not service.take_reactions(service.context()['lobby'],True)
    assert service.store.db.execute('SELECT count(*) FROM messages').fetchone()[0]==0


def test_asset_loading_waits_briefly_rechecks_hide_and_uses_real_item_name(service):
    connect(service);calls=[];loader=ReactionAssets(clock=lambda:100)
    steam=NS(definition=lambda item,prop: {'tags':'quality:rare;itemslot:emote','name':'Fixture Emote'}[prop])
    assets=NS(get_emote=lambda name:calls.append(name))
    event=reaction(service,kind='emote',item=927)
    loader.add(event)
    assert loader.ready(service.state,steam,assets)==[]
    assert calls==['Fixture Emote']
    assets.get_emote=lambda name:PNG
    ready=loader.ready(service.state,steam,assets)
    assert ready[0]['avatar']==PNG and ready[0]['image']==PNG
    loader.add(event)
    assert not loader.ready(dict(service.state,hidden={'fixture-peer':True}),steam,assets)
    loader.add(dict(event,observed=98))
    assert not loader.ready(service.state,steam,assets)
    loader.add(event);steam.definition=lambda *args:'itemslot:hat'
    assert not loader.ready(service.state,steam,assets)


def test_assets_are_required_and_unknowns_never_become_placeholder_cats(service):
    connect(service)
    for changes in ({'avatar':None}, {'kind':'emote','image':None}, {'kind':'text'}, {'text':'ordinary chat'}):
        service.receive_reaction(reaction(service,**changes))
    assert not service.reactions
