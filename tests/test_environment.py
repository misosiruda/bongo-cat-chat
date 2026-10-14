"""Complete build tuples, editable Steam metadata, and fail-closed catalog loading."""
import hashlib
import json

import pytest

from bongo_chat import environment as env


@pytest.fixture
def game_files(tmp_path, monkeypatch):
    root = tmp_path / 'steamapps/common/BongoCat'
    builds = []
    for build in ('100', '200'):
        hashes = {name: hashlib.sha256((build + name).encode()).hexdigest() for name in env.BUILD_FILES}
        builds.append({'build': build, 'sha256': hashes})
    path = tmp_path / 'supported-build.json'
    path.write_text(json.dumps({'schema': 1, 'builds': builds}))
    monkeypatch.setattr(env, 'SUPPORT_PATH', path)
    for name in env.BUILD_FILES:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(('100' + name).encode())
    manifest = root.parent.parent / 'appmanifest_3419430.acf'
    manifest.write_text('"AppState" { "appid" "3419430" "buildid" "200" }')
    return root, path, manifest


def test_known_complete_tuples_ignore_display_build_id(game_files):
    root, _, _ = game_files
    assert env.installed_build(root) == '200'
    assert env.verify_build(root) == '100'
    for name in env.BUILD_FILES:
        (root / name).write_bytes(('200' + name).encode())
    assert env.verify_build(root) == '200'


@pytest.mark.parametrize('change', ['mixed', 'missing', 'modified'])
def test_known_build_number_cannot_approve_changed_or_mixed_files(game_files, change):
    root, _, _ = game_files
    file = root / env.BUILD_FILES[0]
    if change == 'missing':
        file.unlink()
    else:
        file.write_bytes(('200' + env.BUILD_FILES[0]).encode() if change == 'mixed' else b'unverified patch')
    with pytest.raises(env.UnsupportedGameBuild) as result:
        env.verify_build(root)
    assert result.value.build == '200'
    assert len(result.value.fingerprint) == 64
    assert str(result.value) == 'unsupported_game_build'


@pytest.mark.parametrize('catalog', [
    {}, {'schema': 1, 'builds': []},
    {'schema': 1, 'builds': [{'build': '100', 'sha256': {}}]},
    {'schema': 1, 'builds': [None]},
    {'schema': 2, 'builds': []},
])
def test_bad_catalog_never_allows_an_empty_match(game_files, catalog):
    root, path, _ = game_files
    path.write_text(json.dumps(catalog))
    with pytest.raises(RuntimeError, match='unsupported_build_catalog'):
        env.verify_build(root)


@pytest.mark.parametrize('raw', [b'not a manifest', b'"appid" "3419430" "buildid" "<markup>"',
    b'"appid" "999" "buildid" "200"', b'"appid" "3419430" "buildid" "1" "buildid" "2"',
    b'x' * 65537, b'\xff'], ids=['missing', 'markup', 'other_app', 'duplicate', 'oversize', 'encoding'])
def test_bad_diagnostic_manifest_never_blocks_known_hash_match(game_files, raw):
    root, _, manifest = game_files
    manifest.write_bytes(raw)
    assert env.installed_build(root) == ''
    assert env.verify_build(root) == '100'


def test_real_catalog_is_complete_and_has_no_ambiguous_tuple():
    builds = env.supported_builds()
    tuples = {tuple(row['sha256'][name] for name in env.BUILD_FILES) for row in builds}
    assert len(tuples) == len(builds)
