"""Synthetic profile permissions and worker snapshots; no native Steam calls."""
import pytest

from bongo_chat.profiles import steam_profile_uri
from bongo_chat.service import ChatService
from bongo_chat.store import Store
from bongo_chat.worker import LiveConnection, unavailable
from test_core import FakeGame, FakeMemory, FakeSteam, state


# Invented uint64 strings, including distinct values that round to the same JS Number.
SELF = '76561190000000000'
PEER = '76561190000000001'
SECOND = '76561190000000002'


def profile_state(**changes):
    return state(**dict(dict(account=SELF, members=[SELF, PEER, SECOND], hidden={PEER: False, SECOND: None}, hidden_ok=False,
                            privacy_ready=True, send_enabled=False,
                            profiles={SELF: {'name': '시험 계정'}, PEER: {'name': '동일 이름'},
                                      SECOND: {'name': '동일 이름'}}), **changes))


@pytest.fixture
def profile_service(tmp_path):
    store = Store(tmp_path / 'profiles.sqlite3')
    service = ChatService(store, clock=lambda: 100)
    service.update(profile_state())
    yield service
    store.close()


@pytest.mark.parametrize('uid', [PEER, SECOND, '18446744073709551615'])
def test_fixed_uri_preserves_every_decimal_digit(uid):
    assert steam_profile_uri(uid) == 'steam://url/SteamIDPage/' + uid


@pytest.mark.parametrize('uid', [None, True, 76561190000000001, 1.2, {}, [], '', '0', '01', '-1', '+1',
    ' 76561190000000001', '76561190000000001 ', '76561190000000001\n', '1e17',
    '７６５６１１９０００００００００１', '١٢٣', '18446744073709551616', '9' * 100,
    'steam://url/SteamIDPage/76561190000000001', '1/2', '1\\2', '1?x', '1#x', '1\x00', '1;calc'])
def test_malformed_ids_are_rejected(uid):
    with pytest.raises(ValueError, match='invalid_steam_id'):
        steam_profile_uri(uid)


def test_read_only_and_partial_privacy_allow_the_confirmed_peer(profile_service):
    service = profile_service
    assert not service.can_send() and not service.state['hidden_ok']
    assert service.profile_uri(PEER, service.context()).endswith('/' + PEER)
    assert service.view()['profile_targets'] == [PEER, SECOND]
    assert SECOND in service.view()['profiles']
    # A storage failure does not turn a read-only profile action into a send action.
    service.storage_error = True
    assert service.profile_uri(PEER, service.context()).endswith('/' + PEER)


@pytest.mark.parametrize('uid', [SELF, '76561190000000003'])
def test_self_unconfirmed_and_absent_peers_are_rejected(profile_service, uid):
    with pytest.raises(ValueError, match='steam_profile_unavailable'):
        profile_service.profile_uri(uid, profile_service.context())


@pytest.mark.parametrize('changes', [dict(connected=False), dict(lobby_verified=False),
    dict(members=[]),
    dict(profiles={}), dict(account=''), dict(lobby=''), dict(generation='')])
def test_ineligible_states_remove_actions_and_reject_requests(profile_service, changes):
    service = profile_service
    service.update(profile_state(**changes))
    assert service.view()['profile_targets'] == []
    with pytest.raises(ValueError, match='steam_profile_unavailable'):
        service.profile_uri(PEER, service.context())


@pytest.mark.parametrize('field', ['account', 'lobby', 'generation'])
def test_old_context_is_not_retargeted(profile_service, field):
    service = profile_service
    old = service.context()
    service.update(profile_state(**{field: 'new-' + field}))
    with pytest.raises(ValueError, match='steam_profile_unavailable'):
        service.profile_uri(PEER, old)


def test_stale_offline_and_archived_views_have_no_targets(profile_service):
    service = profile_service
    assert service.view(lobby='archived-room')['profile_targets'] == []
    service.clock = lambda: 102.5
    assert service.view()['profile_targets'] == []
    with pytest.raises(ValueError, match='steam_profile_unavailable'):
        service.profile_uri(PEER, service.context())
    service.update(unavailable('offline'))
    assert service.view()['profile_targets'] == []


def test_worker_removes_departed_but_keeps_hidden_peers_before_profile_cache_refresh(monkeypatch):
    members = {'fixture-self', 'fixture-peer'}
    steam, memory = FakeSteam(), FakeMemory()
    steam.members = lambda lobby: set(members)
    live = LiveConnection(FakeGame(), memory, steam)
    monkeypatch.setattr('bongo_chat.worker.time.monotonic', lambda: 100)
    first, _, _ = live.snapshot()
    assert 'fixture-peer' in first['profiles']
    members.remove('fixture-peer')
    left, _, _ = live.snapshot()
    assert 'fixture-peer' in live.profiles  # Deliberately retained one-second cache.
    assert 'fixture-peer' not in left['profiles']
    members.add('fixture-peer')
    memory.hidden = lambda: {'fixture-peer': True}
    hidden, _, _ = live.snapshot()
    assert 'fixture-peer' in hidden['profiles']
    memory.hidden = lambda: {}
    unknown, _, _ = live.snapshot()
    assert 'fixture-peer' in unknown['profiles']
