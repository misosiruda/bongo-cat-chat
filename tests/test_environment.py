"""Feature contracts accept unrelated updates and block unverified semantics."""
import hashlib
import json
import pytest
from bongo_chat import environment as env

FEATURES = {key: hashlib.sha256(key.encode()).hexdigest() for key in ('chat', 'privacy', 'lobby', 'profiles', 'reactions')}

@pytest.fixture
def game_files(tmp_path, monkeypatch):
    root = tmp_path / 'steamapps/common/BongoCat'
    native = {name: [hashlib.sha256(name.encode()).hexdigest()] for name in env.BUILD_FILES[1:3]}
    spec = {'schema': 1, 'assemblies': ['Assembly-CSharp.dll', 'Heathen.Steamworks.dll'],
            'features': {key: {} for key in FEATURES}, 'native': native, 'profiles': [FEATURES]}
    path = tmp_path / 'feature-contract.json'
    path.write_text(json.dumps(spec))
    monkeypatch.setattr(env, 'SUPPORT_PATH', path)
    monkeypatch.setattr(env, 'probe_features', lambda root, stop=None: dict(FEATURES))
    for name in env.BUILD_FILES:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(name.encode())
    manifest = root.parent.parent / 'appmanifest_3419430.acf'
    manifest.write_text('"AppState" { "appid" "3419430" "buildid" "200" }')
    return root, path, manifest

def test_unknown_build_and_changed_managed_files_are_allowed_when_features_match(game_files):
    root, _, manifest = game_files
    assert env.verify_build(root) == '200'
    (root / env.BUILD_FILES[0]).write_bytes(b'new unrelated code')
    (root / env.BUILD_FILES[3]).write_bytes(b'new unrelated cosmetic slot')
    manifest.write_text('"appid" "3419430" "buildid" "999"')
    assert env.verify_build(root) == '999'

@pytest.mark.parametrize('feature', list(FEATURES))
def test_changed_feature_is_blocked_even_with_a_familiar_build(game_files, monkeypatch, feature):
    root, _, _ = game_files
    monkeypatch.setattr(env, 'probe_features', lambda root, stop=None: dict(FEATURES, **{feature: '0' * 64}))
    with pytest.raises(env.UnsupportedGameBuild) as result:
        env.verify_build(root)
    assert result.value.build == '200' and len(result.value.fingerprint) == 64

@pytest.mark.parametrize('change', ['missing', 'native', 'probe_failure'])
def test_incomplete_or_unreadable_contract_cannot_be_accepted(game_files, monkeypatch, change):
    root, _, _ = game_files
    if change == 'missing':
        (root / env.BUILD_FILES[0]).unlink()
    elif change == 'native':
        (root / env.BUILD_FILES[2]).write_bytes(b'unknown native ABI')
    else:
        def fail(*_): raise ValueError('broken metadata')
        monkeypatch.setattr(env, 'probe_features', fail)
    with pytest.raises(env.UnsupportedGameBuild): env.verify_build(root)

@pytest.mark.parametrize('catalog', [{}, {'schema': 1, 'profiles': []}, {'schema': 1, 'profiles': [{}]}, {'schema': 2}])
def test_bad_contract_never_allows_empty_match(game_files, catalog):
    root, path, _ = game_files
    path.write_text(json.dumps(catalog))
    with pytest.raises(RuntimeError, match='unsupported_feature_contract'): env.verify_build(root)

@pytest.mark.parametrize('raw', [b'not a manifest', b'"appid" "3419430" "buildid" "<markup>"',
    b'"appid" "999" "buildid" "200"', b'"appid" "3419430" "buildid" "1" "buildid" "2"', b'x' * 65537, b'\xff'],
    ids=['missing', 'markup', 'other_app', 'duplicate', 'oversize', 'encoding'])
def test_bad_diagnostic_manifest_does_not_block_compatible_features(game_files, raw):
    root, _, manifest = game_files
    manifest.write_bytes(raw)
    assert env.installed_build(root) == '' and env.verify_build(root) == ''

def test_updates_during_verification_or_active_connection_require_recheck(game_files, monkeypatch):
    root, _, _ = game_files
    verified = env.verify_compatibility(root)
    (root / env.BUILD_FILES[0]).write_bytes(b'another unrelated update')
    with pytest.raises(RuntimeError, match='game_files_changed'): verified.check()
    def changing_probe(root, stop=None):
        (root / env.BUILD_FILES[0]).write_bytes(b'update while the probe is running')
        return dict(FEATURES)
    monkeypatch.setattr(env, 'probe_features', changing_probe)
    with pytest.raises(RuntimeError, match='game_files_changed'): env.verify_compatibility(root)

def test_real_contract_has_complete_feature_profiles():
    catalog = env.compatibility_contract()
    assert all(set(profile) == set(FEATURES) for profile in catalog['profiles'])


def test_game_discovery_reads_details_only_for_matching_name(tmp_path, monkeypatch):
    from contextlib import nullcontext
    calls = []
    class Process:
        pid = 123
        def __init__(self, name):
            self.info = {'name': name}
        def oneshot(self):
            return nullcontext()
        def exe(self):
            calls.append(self.info['name'])
            assert self.info['name'] == 'BongoCat.exe'
            return str(tmp_path / 'BongoCat.exe')
        def create_time(self):
            return 456
    def processes(attrs):
        assert attrs == ['name']
        return [Process('unrelated.exe'), Process(None), Process('BongoCat.exe')]
    monkeypatch.setattr(env.psutil, 'process_iter', processes)
    game = env.running_game()
    assert game.root == tmp_path and game.created == 456
    assert calls == ['BongoCat.exe']
