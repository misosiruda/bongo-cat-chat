"""Synthetic reaction packets/assets only. No lobby traffic or game resources."""
import json
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from bongo_chat.protocol import decode_event, decode, encode, InvalidMessage
from bongo_chat.reactions import ReactionAssets, MAX_REACTIONS
from test_core import service, store, state

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=='


def reaction(service, **changes):
    return dict(dict(type='reaction', kind='meow', text='야옹 야옹', avatar=PNG,
        id=str(uuid4()), sender='fixture-peer', context=service.context(), observed=100.0), **changes)


def connect(service):
    service.update(state(profiles={'fixture-peer': {'name': '합성 고양이', 'avatar': PNG}}))


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
