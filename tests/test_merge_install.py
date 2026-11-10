"""Distribution preparation tests; no live process discovery or injection."""
import hashlib
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from bongo_chat.merge_install import validate_assets,compile_helper,prepare_session,HELPER
from bongo_chat import merge_install

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def reconnect_session(tmp_path, monkeypatch):
    """An existing bridge with delayed telemetry; no game process is opened."""
    game = SimpleNamespace(pid=123, root=tmp_path/'game')
    session = tmp_path/'.bongo-cat-chat'/'merge-bridge'/'123-456'
    session.mkdir(parents=True)
    config = dict(mode='interactive', source_sha256='fixture-source', epoch='e'*32, pid=123, protocol=1)
    (session/'session.json').write_text(json.dumps(config))
    (session/'attach-result.json').write_text(json.dumps(dict(status=1, stage=7, managed_exception=False)))
    calls, elapsed = [], [0.0]
    class Channel:
        def __init__(self, path):
            assert path == session
            self.session, self.config = session, config
            self.reads = 0
            self.closed = False
            self.ready_after = 2
            self.armed = False
            self.terminal = False
            self.target_changed = False
            self.read_error = None
            self.request_error = None
        def verify_target(self, value):
            if self.target_changed:
                raise RuntimeError('target_changed')
        def snapshot(self):
            self.reads += 1
            if self.read_error:
                raise self.read_error
            if self.reads <= self.ready_after:
                raise FileNotFoundError('waiting for first render')
            return dict(reason='closed' if self.terminal else '', chest=dict(armed=self.armed))
        def request(self, op):
            calls.append(op)
            if op == self.request_error:
                raise RuntimeError('result_unverified')
        def close(self):
            self.closed = True
    channel = Channel(session)
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setattr(merge_install, 'running_game', lambda: game)
    monkeypatch.setattr(merge_install, 'validate_assets', lambda *args: (tmp_path, config))
    monkeypatch.setattr(merge_install, 'kernel', lambda: SimpleNamespace(OpenProcess=lambda *args: 1, CloseHandle=lambda h: calls.append('close_handle')))
    monkeypatch.setattr(merge_install, 'start_ticks', lambda *args: 456)
    monkeypatch.setattr(merge_install, 'BridgeChannel', lambda path: channel)
    monkeypatch.setattr('bongo_chat.merge_connection.InteractiveAdapter', lambda **kwargs: kwargs['channel'])
    monkeypatch.setattr(merge_install, 'time', SimpleNamespace(monotonic=lambda: elapsed[0], sleep=lambda n: elapsed.__setitem__(0, elapsed[0]+n)))
    def forbidden(*args, **kwargs):
        pytest.fail('reconnection must not read game memory, compile or attach another module')
    for name in ('Reader', 'execute', 'prepare_session', 'private_directory'):
        monkeypatch.setattr(merge_install, name, forbidden)
    return channel, calls


@pytest.mark.parametrize('armed', [False, True])
def test_reconnect_waits_for_late_response_without_reattaching_or_consuming(reconnect_session, armed):
    channel, calls = reconnect_session
    channel.armed = armed
    assert merge_install.connect() is channel
    assert channel.reads == 3 and not channel.closed
    assert calls == (['chest_stop'] if armed else []) + ['snapshot', 'close_handle']


def test_reconnect_timeout_retains_evidence_and_can_read_same_session_later(reconnect_session):
    channel, calls = reconnect_session
    channel.ready_after = 1000
    before = {p.name: p.read_bytes() for p in channel.session.iterdir()}
    with pytest.raises(RuntimeError, match='^bridge_response_pending$'):
        merge_install.connect()
    assert channel.closed and calls == ['close_handle']
    assert {p.name: p.read_bytes() for p in channel.session.iterdir()} == before
    # A new manual Connect reads the same module after the game begins rendering.
    channel.closed = False
    channel.ready_after = 0
    assert merge_install.connect() is channel
    assert calls == ['close_handle', 'snapshot', 'close_handle']


@pytest.mark.parametrize('result', [None, dict(status=2, stage=7, managed_exception=True), dict(status=0, stage=3, managed_exception=False)])
def test_unconfirmed_attachment_is_not_reported_as_only_delayed(reconnect_session, result):
    channel, calls = reconnect_session
    channel.ready_after = 1000
    path = channel.session/'attach-result.json'
    if result is None:
        path.unlink()
    else:
        path.write_text(json.dumps(result))
    expected = 'bridge_initialization_failed' if result and result.get('status') == 2 else 'attach_not_confirmed_no_retry'
    with pytest.raises(RuntimeError, match='^'+expected+'$'):
        merge_install.connect()
    assert channel.closed and calls == ['close_handle']


@pytest.mark.parametrize('error,expected', [
    (PermissionError('private path'), 'bridge_storage_access_denied'),
    (OSError('read failure'), 'bridge_storage_failed'),
    (ValueError('invalid JSON'), 'bridge_session_invalid'),
])
def test_attachment_record_read_error_does_not_become_a_restart_request(reconnect_session, monkeypatch, error, expected):
    channel, calls = reconnect_session
    original = merge_install.read_json
    def read(path):
        if path.name == 'attach-result.json':raise error
        return original(path)
    monkeypatch.setattr(merge_install, 'read_json', read)
    with pytest.raises(RuntimeError, match='^'+expected+'$'):
        merge_install.connect()
    assert channel.closed and calls == ['close_handle']
    assert (channel.session/'attach-result.json').is_file()


@pytest.mark.parametrize('reason,expected', [
    ('closed', 'bridge_session_closed'), ('stale_closed', 'bridge_session_closed'),
    ('source_changed', 'bridge_session_incompatible'), ('target_changed', 'bridge_target_changed'),
    ('missing_config', 'bridge_session_invalid'), ('malformed_config', 'bridge_session_invalid'),
])
def test_reconnect_keeps_terminal_session_guards(reconnect_session, reason, expected):
    channel, calls = reconnect_session
    if reason == 'closed':
        channel.ready_after = 0
        channel.terminal = True
    elif reason == 'stale_closed':
        (channel.session/'snapshot.json').write_text(json.dumps(dict(channel.config, reason='closed')))
    elif reason == 'source_changed':
        (channel.session/'session.json').write_text(json.dumps(dict(channel.config, source_sha256='old-source')))
    elif reason == 'target_changed':
        channel.target_changed = True
    elif reason == 'missing_config':
        (channel.session/'session.json').unlink()
    else:
        (channel.session/'session.json').write_text('{')
    with pytest.raises(RuntimeError, match='^'+expected+'$'):
        merge_install.connect()
    assert calls == ['close_handle']


@pytest.mark.parametrize('error,expected', [
    (PermissionError('private path'), 'bridge_storage_access_denied'),
    (OSError('sharing conflict'), 'bridge_response_unreadable'),
    (ValueError('invalid JSON'), 'bridge_response_invalid'),
    (ValueError('bridge_snapshot_mismatch'), 'bridge_response_invalid'),
    (KeyError('private field'), 'bridge_response_invalid'),
    (ValueError('observation_stale'), 'bridge_response_pending'),
])
def test_response_failures_are_distinguished_without_reattaching(reconnect_session, error, expected):
    channel, calls = reconnect_session
    channel.read_error = error
    before = {p.name:p.read_bytes() for p in channel.session.iterdir()}
    with pytest.raises(RuntimeError, match='^'+expected+'$'):
        merge_install.connect()
    assert channel.closed and calls == ['close_handle']
    assert {p.name:p.read_bytes() for p in channel.session.iterdir()} == before


@pytest.mark.parametrize('operation,expected', [('snapshot', 'bridge_reconnect_failed'), ('chest_stop', 'bridge_stop_unconfirmed')])
def test_reconnection_requests_are_not_resent_when_the_reply_is_lost(reconnect_session, operation, expected):
    channel, calls = reconnect_session
    channel.armed = operation == 'chest_stop'
    channel.request_error = operation
    with pytest.raises(RuntimeError, match='^'+expected+'$'):
        merge_install.connect()
    assert calls == [operation, 'close_handle'] and channel.closed


@pytest.mark.parametrize('error,expected', [
    (PermissionError(errno.EACCES, 'private path'), 'bridge_storage_access_denied'),
    (OSError(errno.ENOSPC, 'private path'), 'bridge_storage_full'),
    (FileExistsError(errno.EEXIST, 'private path'), 'bridge_storage_conflict'),
    (OSError(errno.EIO, 'private path'), 'bridge_storage_failed'),
])
def test_session_write_failure_has_safe_actionable_reason_and_preserves_evidence(tmp_path, monkeypatch, error, expected):
    path = tmp_path/'attach-result.json'
    path.write_bytes(b'preserved evidence')
    def fail(*args, **kwargs):raise error
    monkeypatch.setattr(Path, 'write_text', fail)
    with pytest.raises(RuntimeError, match='^'+expected+'$'):
        merge_install.write_session_json(path, {'status':1})
    assert path.read_bytes() == b'preserved evidence'


def test_linked_parent_is_an_unsupported_path_not_a_restart_request(tmp_path, monkeypatch):
    linked = tmp_path/'linked'
    linked.mkdir()
    monkeypatch.setattr(Path, 'is_junction', lambda path: path == linked)
    with pytest.raises(RuntimeError, match='^bridge_path_unsupported$'):
        merge_install.no_links(linked/'new-session')
    assert list(linked.iterdir()) == []


@pytest.mark.skipif(os.name != 'nt', reason='Windows directory ACLs')
def test_directory_creation_reports_existing_path_and_other_os_failures(tmp_path):
    session = tmp_path/'session'
    merge_install.private_directory(session)
    marker = session/'ledger.json'
    marker.write_bytes(b'preserve')
    with pytest.raises(RuntimeError, match='^bridge_storage_conflict$'):
        merge_install.private_directory(session)
    with pytest.raises(RuntimeError, match='^bridge_storage_failed$'):
        merge_install.private_directory(tmp_path/'missing-parent'/'session')
    assert marker.read_bytes() == b'preserve'


@pytest.mark.parametrize('mode,expected', [
    ('empty', None), ('cycle', 'bridge_module_scan_failed'), ('unreadable', 'bridge_module_scan_failed'),
    ('active', 'prior_bridge_active'), ('missing_tables', 'bridge_module_scan_failed'),
    ('uninitialized', 'bridge_module_scan_failed'),
])
def test_module_scan_does_not_confuse_unreadable_metadata_with_a_loaded_bridge(monkeypatch, mode, expected):
    class Catalog:
        base = 1000
        def __init__(self, reader):pass
        def images(self):
            if mode == 'unreadable':raise ValueError('private memory diagnostic')
        def klass(self, *args):return 100
        def vtables(self, *args):return [] if mode == 'missing_tables' else [200]
    class Reader:
        def pointer(self, address):
            return {1000+0x740f90:0 if mode == 'empty' else 1, 1:2, 2+0x60:3,
                    3+0x30:4, 9:1 if mode == 'cycle' else 0, 200+0x48:300}.get(address, 0)
        def cstring(self, address):return 'Unrelated' if mode == 'cycle' else HELPER[:-4]
        def i32(self, address):return 0
        def exact(self, address, size):
            return bytes([0 if mode == 'uninitialized' else 4]) if address == 200+0x30 else b'\0'
    monkeypatch.setattr(merge_install, 'MonoCatalog', Catalog)
    monkeypatch.setattr(merge_install, 'fields', lambda *args: dict(installed=0, stopped=1, unknown=2, spent=4))
    if expected:
        with pytest.raises(RuntimeError, match='^'+expected+'$'):
            merge_install.check_prior_modules(Reader())
    else:
        merge_install.check_prior_modules(Reader())


@pytest.mark.parametrize('outcome,expected', [
    ('ready', None), ('late', 'bridge_response_pending'),
    ('managed_failure', 'bridge_initialization_failed'), ('native_failure', 'attach_not_confirmed_no_retry'),
    ('type_failure', 'bridge_dependency_load_failed'),
    ('native_os_failure', 'attach_not_confirmed_no_retry'), ('load_failure', 'attach_not_confirmed_no_retry'),
])
def test_initial_attach_classification_never_reloads_an_uncertain_module(tmp_path, monkeypatch, outcome, expected):
    """Execute the product flow with synthetic exports and a fake bootstrap only."""
    calls, elapsed, channels = [], [0.0], []
    game = SimpleNamespace(root=tmp_path/'game', pid=123, alive=lambda:True)
    contract = dict(source_sha256='fixture-source')
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setattr(merge_install, 'running_game', lambda:game)
    monkeypatch.setattr(merge_install, 'validate_assets', lambda *args:(tmp_path, contract))
    monkeypatch.setattr(merge_install, 'validate_game_files', lambda *args:dict(modules={}))
    monkeypatch.setattr(merge_install, 'kernel', lambda:SimpleNamespace(OpenProcess=lambda *args:1, CloseHandle=lambda h:None))
    monkeypatch.setattr(merge_install, 'start_ticks', lambda *args:456)
    monkeypatch.setattr(merge_install, 'private_directory', lambda path:path.mkdir())
    monkeypatch.setattr(merge_install, 'check_prior_modules', lambda *args:None)
    monkeypatch.setattr(merge_install, 'Reader', lambda game:SimpleNamespace(module=lambda name:4096, exact=lambda *args:b'x'*24, close=lambda:None))
    class PE:
        FILE_HEADER = SimpleNamespace(Machine=0x8664)
        DIRECTORY_ENTRY_EXPORT = SimpleNamespace(symbols=[SimpleNamespace(name=name.encode(), forwarder=None, address=i)
            for i,name in enumerate((*merge_install.EXPORTS, merge_install.ERROR_EXPORT, *merge_install.DIAGNOSTIC_EXPORTS))])
        def __init__(self, path):pass
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def get_data(self, *args):return b'x'*24
    monkeypatch.setattr(merge_install.pefile, 'PE', PE)
    def prepare(game, assets, session, compatibility):
        path = session/HELPER
        path.write_bytes(b'synthetic module never loaded')
        return path
    monkeypatch.setattr(merge_install, 'prepare_session', prepare)
    def attach(*args):
        calls.append('attach')
        if outcome == 'native_failure':raise RuntimeError('bootstrap_outcome_unknown_no_retry')
        if outcome == 'native_os_failure':
            error = PermissionError('C:/private/user and secret-token')
            error.winerror = 5
            raise error
        if outcome == 'load_failure':
            return dict(status=0, stage=3, exception=0, load_error=2, load_message='C:/private/user')
        failed = outcome in {'managed_failure', 'type_failure'}
        return dict(status=2 if failed else 1, stage=7, exception=1 if failed else 0,
                    **(dict(managed_exception_types=['System.InvalidOperationException',
                                'System.TypeLoadException' if outcome == 'type_failure' else 'System.IO.IOException'],
                            initialization_step='read_session') if failed else {}))
    monkeypatch.setattr(merge_install, 'execute', attach)
    def make_channel(path):
        def snapshot():
            if outcome != 'ready':raise FileNotFoundError('no game response')
            return dict(reason='ready', chest=dict(armed=False))
        channel = SimpleNamespace(session=path, config=merge_install.read_json(path/'session.json'),
                                  verify_target=lambda config:None, snapshot=snapshot,
                                  close=lambda:calls.append('close_channel'))
        channels.append(channel)
        return channel
    monkeypatch.setattr(merge_install, 'BridgeChannel', make_channel)
    monkeypatch.setattr('bongo_chat.merge_connection.InteractiveAdapter', lambda **kwargs:kwargs['channel'])
    monkeypatch.setattr(merge_install, 'time', SimpleNamespace(monotonic=lambda:elapsed[0], time=lambda:1234.0,
        sleep=lambda n:elapsed.__setitem__(0, elapsed[0]+n)))
    if expected:
        with pytest.raises(RuntimeError, match='^'+expected+'$') as failed:
            merge_install.connect()
        diagnostic = failed.value.connection_diagnostics
        assert diagnostic['source'] == 'new'
        assert not any(word in json.dumps(diagnostic) for word in ('private', 'secret', 'load_message'))
        if outcome == 'native_failure':
            assert diagnostic['native_error'] == 'bootstrap_outcome_unknown_no_retry'
        elif outcome == 'native_os_failure':
            assert diagnostic['native_error'] == 'native_os_error' and diagnostic['winerror'] == 5
        elif outcome in {'managed_failure', 'type_failure'}:
            assert diagnostic['status'] == 2 and diagnostic['stage'] == 7 and diagnostic['managed_exception'] is True
            assert diagnostic['initialization_step'] == 'read_session'
            assert diagnostic['managed_exception_types'] == ['System.InvalidOperationException',
                'System.TypeLoadException' if outcome == 'type_failure' else 'System.IO.IOException']
        elif outcome == 'load_failure':
            assert diagnostic['status'] == 0 and diagnostic['stage'] == 3 and diagnostic['load_error'] == 2
        session = tmp_path/'.bongo-cat-chat'/'merge-bridge'/'123-456'
        before = {p.name:p.read_bytes() for p in session.iterdir()}
        assert 'attach-attempt.json' in before
        with pytest.raises(RuntimeError, match='^'+expected+'$') as reused:
            merge_install.connect()
        assert reused.value.connection_diagnostics['source'] == 'existing'
        assert reused.value.connection_diagnostics['attach_record'] == ('missing' if outcome in {'native_failure', 'native_os_failure'} else 'present')
        if outcome in {'managed_failure', 'type_failure'}:
            assert reused.value.connection_diagnostics['initialization_step'] == diagnostic['initialization_step']
            assert reused.value.connection_diagnostics['managed_exception_types'] == diagnostic['managed_exception_types']
        assert {p.name:p.read_bytes() for p in session.iterdir()} == before
    else:
        assert merge_install.connect() is channels[0]
    assert calls.count('attach') == 1
    assert not list(tmp_path.rglob('request.json'))


@pytest.fixture
def assets(tmp_path, monkeypatch):
    folder=tmp_path/'assets';folder.mkdir()
    game=tmp_path/'game';game.mkdir()
    contract=json.loads((ROOT/'tools/merge_bridge/local-contract.json').read_text())
    profile=contract['profiles'][0]
    for name in set(profile['files']) | {'BongoCat_Data/Managed/Assembly-CSharp.dll','BongoCat_Data/Managed/System.Core.dll'}:
        path=game/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('synthetic '+name).encode())
        if name in profile['files']:profile['files'][name]=[hashlib.sha256(path.read_bytes()).hexdigest()]
    profile['files']['BongoCat_Data/Managed/BongoAutoChest.dll'].append(None)
    for name,key in [('Bridge.cs','source_sha256'),('MergePrepare.exe','prepare_sha256'),('Mono.Cecil.dll','cecil_sha256'),
                     ('FeatureProbe.exe','probe_sha256'),('feature-spec.json','spec_sha256')]:
        content=json.dumps(contract['probe']).encode() if name=='feature-spec.json' else ('synthetic '+name).encode()
        (folder/name).write_bytes(content);contract[key]=hashlib.sha256(content).hexdigest()
    (folder/'contract.json').write_text(json.dumps(contract))
    def probe(command, **kwargs):
        assert command[0]==str(folder/'FeatureProbe.exe') and kwargs['timeout']==20
        modules={p.name:'11111111-2222-3333-4444-555555555555' for p in (game/'BongoCat_Data/Managed').glob('*.dll')}
        return SimpleNamespace(returncode=0,stdout=json.dumps({'features':profile['features'],'modules':modules}).encode())
    monkeypatch.setattr(subprocess,'run',probe)
    return SimpleNamespace(root=game),folder,contract


@pytest.mark.parametrize('name',['Bridge.cs','MergePrepare.exe','Mono.Cecil.dll','FeatureProbe.exe','feature-spec.json'])
def test_payload_and_game_metadata_are_verified_before_compilation(assets,name):
    game,folder,contract=assets
    assert validate_assets(game,folder)==(folder,contract)
    (folder/name).write_text('changed')
    with pytest.raises(RuntimeError,match='bridge_binary_changed'):validate_assets(game,folder)


@pytest.mark.parametrize('name',['Assembly-CSharp.dll','System.Core.dll'])
def test_unrelated_binary_change_with_same_features_is_allowed(assets,name):
    game,folder,_=assets
    (game.root/'BongoCat_Data/Managed'/name).write_bytes(b'different metadata, same functional contract')
    validate_assets(game,folder)


def test_native_and_dependency_change_is_refused(assets):
    game,folder,_=assets
    (game.root/'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll').write_bytes(b'unknown native runtime')
    with pytest.raises(RuntimeError,match='unsupported_game_files'):validate_assets(game,folder)


@pytest.mark.parametrize('profile_index', [0, 1])
def test_reviewed_automation_profiles_keep_exact_feature_and_dependency_binding(assets, monkeypatch, profile_index):
    game, folder, contract = assets
    # Exercise both supported feature sets through the product validator with
    # synthetic files; no installed game or process is needed.
    profile = contract['profiles'][profile_index]
    profile['files'] = json.loads(json.dumps(contract['profiles'][0]['files']))
    (folder/'contract.json').write_text(json.dumps(contract))
    probe = subprocess.run
    features = dict(profile['features'])
    def observed(*args, **kwargs):
        value = probe(*args, **kwargs)
        result = json.loads(value.stdout)
        result['features'] = features
        value.stdout = json.dumps(result).encode()
        return value
    monkeypatch.setattr(subprocess, 'run', observed)
    assert validate_assets(game, folder) == (folder, contract)
    for feature in ('chest', 'merge', 'inventory'):
        original = features[feature]
        features[feature] = '0'*64
        with pytest.raises(RuntimeError, match='^unsupported_automation_features$'):
            validate_assets(game, folder)
        features[feature] = original
    # An approved fingerprint cannot borrow another profile's dependency pins.
    profile['files']['BongoCat.exe'] = ['0'*64]
    (folder/'contract.json').write_text(json.dumps(contract))
    with pytest.raises(RuntimeError, match='^unsupported_(automation_features|game_files)$'):
        validate_assets(game, folder)


@pytest.mark.parametrize('fault,expected', [
    ('missing', 'bridge_dependency_missing'),
    ('changed', 'bridge_dependency_incompatible'),
    ('unreadable', 'bridge_dependency_unreadable'),
])
def test_json_dependency_is_checked_before_process_access_and_can_be_repaired(assets, monkeypatch, tmp_path, fault, expected):
    game, folder, contract = assets
    dependency = game.root/'BongoCat_Data/Managed/System.Numerics.dll'
    original = dependency.read_bytes()
    ledger = tmp_path/'profile/.bongo-cat-chat/merge-bridge/existing/ledger.json'
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b'preserve existing unresolved result')
    monkeypatch.setenv('USERPROFILE', str(tmp_path/'profile'))
    monkeypatch.setattr(merge_install, 'running_game', lambda:game)
    monkeypatch.setattr(merge_install, 'asset_directory', lambda:folder)
    def forbidden(*args):pytest.fail('dependency failure must precede process access, compilation and attachment')
    for name in ('kernel', 'compile_helper', 'execute'):
        monkeypatch.setattr(merge_install, name, forbidden)
    if fault == 'missing':dependency.unlink()
    elif fault == 'changed':dependency.write_bytes(b'unsupported or damaged dependency')
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path == dependency and fault == 'unreadable':raise PermissionError('C:/private-user')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    for _ in range(2):
        with pytest.raises(RuntimeError, match='^'+expected+'$') as failure:
            merge_install.connect()
        assert failure.value.connection_diagnostics == {'phase':'validate_assets'}
    assert ledger.read_bytes() == b'preserve existing unresolved result'
    assert not list((tmp_path/'profile').rglob('attach-attempt.json'))
    monkeypatch.setattr(Path, 'open', original_open)
    dependency.write_bytes(original)  # Synthetic fixture only; product does not repair game files.
    assert validate_assets(game, folder) == (folder, contract)


def test_contract_cannot_omit_required_json_dependency(assets):
    game, folder, contract = assets
    contract['probe']['pinned_assemblies'].remove('System.Numerics.dll')
    contract['profiles'][0]['files'].pop('BongoCat_Data/Managed/System.Numerics.dll')
    (folder/'contract.json').write_text(json.dumps(contract))
    with pytest.raises(RuntimeError, match='^bridge_assets_missing$'):
        validate_assets(game, folder)


def test_unknown_feature_is_rejected_before_opening_the_game(assets,monkeypatch):
    from bongo_chat import merge_install
    game,folder,_=assets
    probe=subprocess.run
    def changed(*args,**kwargs):
        value=probe(*args,**kwargs);result=json.loads(value.stdout);result['features']['chest']='0'*64
        value.stdout=json.dumps(result).encode();return value
    monkeypatch.setattr(subprocess,'run',changed)
    monkeypatch.setattr(merge_install,'running_game',lambda:game)
    monkeypatch.setattr(merge_install,'asset_directory',lambda:folder)
    def forbidden():pytest.fail('must not open or modify a game process')
    monkeypatch.setattr(merge_install,'kernel',forbidden)
    with pytest.raises(RuntimeError,match='unsupported_automation_features'):merge_install.connect()


@pytest.mark.parametrize('feature',['merge','chest','inventory'])
def test_changed_functional_contract_is_refused(assets,monkeypatch,feature):
    game,folder,_=assets
    probe=subprocess.run
    def changed(*args,**kwargs):
        value=probe(*args,**kwargs);result=json.loads(value.stdout);result['features'][feature]='0'*64
        value.stdout=json.dumps(result).encode();return value
    monkeypatch.setattr(subprocess,'run',changed)
    with pytest.raises(RuntimeError,match='unsupported_automation_features'):validate_assets(game,folder)


@pytest.mark.parametrize('change',['empty','missing_feature','no_pins','cross_profile','traversal','legacy_schema'])
def test_malformed_contract_fails_closed(assets,change):
    game,folder,contract=assets
    if change=='empty':contract['profiles']=[]
    if change=='missing_feature':contract['probe']['features'].pop('chest')
    if change=='no_pins':contract['probe']['pinned_assemblies']=[]
    if change=='cross_profile':contract['profiles'][0]['files'].pop('BongoCat.exe')
    if change=='traversal':contract['probe']['pinned_assemblies'][0]='../untrusted.dll'
    if change=='legacy_schema':contract['schema']=5
    (folder/'contract.json').write_text(json.dumps(contract))
    with pytest.raises(RuntimeError,match='bridge_assets_missing'):validate_assets(game,folder)


@pytest.mark.parametrize('change',['timeout','malformed','missing_module','unknown_feature','large'])
def test_probe_failure_never_approves_compatibility(assets,monkeypatch,change):
    game,folder,_=assets;probe=subprocess.run
    def failed(*args,**kwargs):
        if change=='timeout':raise subprocess.TimeoutExpired(args[0],20)
        value=probe(*args,**kwargs);result=json.loads(value.stdout)
        if change=='missing_module':result['modules'].pop('System.Core.dll')
        if change=='unknown_feature':result['features']['unknown']='0'*64
        value.stdout=b'{' if change=='malformed' else b'x'*16385 if change=='large' else json.dumps(result).encode()
        return value
    monkeypatch.setattr(subprocess,'run',failed)
    with pytest.raises(RuntimeError,match='automation_probe_failed'):validate_assets(game,folder)


@pytest.mark.parametrize('name', ['Assembly-CSharp.dll', 'System.Numerics.dll'])
def test_changed_file_during_probe_is_refused_even_with_same_features(assets,monkeypatch,name):
    game,folder,_=assets;probe=subprocess.run
    def changed(*args,**kwargs):
        value=probe(*args,**kwargs)
        (game.root/'BongoCat_Data/Managed'/name).write_bytes(b'changed while probing')
        return value
    monkeypatch.setattr(subprocess,'run',changed)
    with pytest.raises(RuntimeError,match='automation_files_changed'):validate_assets(game,folder)


def test_legacy_absence_is_allowed_but_unknown_legacy_is_refused(assets):
    game,folder,_=assets;legacy=game.root/'BongoCat_Data/Managed/BongoAutoChest.dll'
    legacy.unlink();validate_assets(game,folder)
    legacy.write_bytes(b'unknown helper')
    with pytest.raises(RuntimeError,match='unsupported_game_files'):validate_assets(game,folder)


def test_missing_game_file_has_safe_actionable_error(assets):
    game,folder,_=assets
    (game.root/'BongoCat_Data/Managed/Assembly-CSharp.dll').unlink()
    with pytest.raises(RuntimeError,match='merge_game_files_missing'):validate_assets(game,folder)


def test_compilation_uses_fixed_commands_and_stops_before_validation_on_failure(assets,tmp_path,monkeypatch):
    game,folder,_=assets
    system=tmp_path/'system';compiler=system/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    compiler.parent.mkdir(parents=True);compiler.write_bytes(b'never executed')
    monkeypatch.setenv('SystemRoot',str(system))
    calls=[]
    monkeypatch.setattr(subprocess,'run',lambda command,**kwargs:calls.append((command,kwargs)))
    session=tmp_path/'session';session.mkdir()
    assert compile_helper(game,folder,session)==session/HELPER
    assert len(calls)==2 and calls[0][0][0]==str(compiler) and calls[1][0][0]==str(folder/'MergePrepare.exe')
    assert calls[0][0][-1]==str(folder/'Bridge.cs') and all(c[1]['timeout']==30 for c in calls)
    calls.clear()
    def failure(command,**kwargs):calls.append(command);raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(subprocess,'run',failure)
    with pytest.raises(RuntimeError,match='merge_prepare_failed'):compile_helper(game,folder,session)
    assert len(calls)==1


def test_missing_windows_compiler_is_reported_without_execution(assets,tmp_path,monkeypatch):
    game,folder,_=assets;monkeypatch.setenv('SystemRoot',str(tmp_path/'missing'))
    with pytest.raises(RuntimeError,match='merge_compiler_missing'):compile_helper(game,folder,tmp_path)


def test_failed_preparation_can_be_retried_without_restarting_game(assets,tmp_path,monkeypatch):
    game,folder,_=assets
    session=tmp_path/'session';session.mkdir()
    def failure(*args):
        (session/HELPER).write_bytes(b'partial compilation')
        raise RuntimeError('merge_prepare_failed')
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',failure)
    with pytest.raises(RuntimeError,match='merge_prepare_failed'):prepare_session(game,folder,session)
    assert not session.exists()
    session.mkdir()
    def success(*args):
        (session/HELPER).write_bytes(b'synthetic complete helper')
        return session/HELPER
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',success)
    assert prepare_session(game,folder,session).read_bytes()==b'synthetic complete helper'


@pytest.mark.parametrize('evidence',['attach-attempt.json','session.json','ledger.json','unrelated.txt'])
def test_preparation_failure_preserves_attachment_evidence_and_unknown_files(assets,tmp_path,monkeypatch,evidence):
    game,folder,_=assets
    session=tmp_path/'session';session.mkdir()
    (session/evidence).write_bytes(b'preserve exactly')
    (session/HELPER).write_bytes(b'preserve helper')
    def failure(*args):raise RuntimeError('merge_prepare_failed')
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',failure)
    with pytest.raises(RuntimeError,match='merge_prepare_failed'):prepare_session(game,folder,session)
    assert (session/evidence).read_bytes()==b'preserve exactly'
    assert (session/HELPER).read_bytes()==b'preserve helper'


def test_changed_metadata_after_compilation_cleans_only_unattached_preparation(assets,tmp_path,monkeypatch):
    game,folder,_=assets
    session=tmp_path/'session';session.mkdir()
    def compile_changed(*args):
        (session/HELPER).write_bytes(b'synthetic helper')
        (game.root/'BongoCat_Data/Managed/Assembly-CSharp.dll').write_bytes(b'changed')
        return session/HELPER
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',compile_changed)
    with pytest.raises(RuntimeError,match='automation_files_changed'):prepare_session(game,folder,session)
    assert not session.exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows C# runtime')
def test_csharp_bridge_consumes_synthetic_items_only():
    shell=shutil.which('pwsh')
    if not shell:pytest.skip('PowerShell 7 fixture runner')
    result=subprocess.run([shell,'-NoProfile','-File',str(ROOT/'tools/merge_bridge/test-bridge.ps1')],
        capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace')
    assert b'Interactive bridge fixture:' in result.stdout and b'synthetic exchanges=3' in result.stdout
    assert b'Chest fixture:' in result.stdout and b'synthetic requests only.' in result.stdout
