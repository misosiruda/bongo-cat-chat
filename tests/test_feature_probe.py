"""Compile independent synthetic assemblies; never patch/copy a game binary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows metadata helper')

def run(args):
    return subprocess.run([str(a) for a in args], capture_output=True, timeout=30, creationflags=FLAGS)

@pytest.fixture(scope='module')
def fixture_tools(tmp_path_factory):
    directory = tmp_path_factory.mktemp('feature-assemblies')
    prepared = run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ROOT / 'tools/prepare-compatibility.ps1'])
    assert prepared.returncode == 0, prepared.stdout.decode(errors='replace')
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    helper = ROOT / 'artifacts/compatibility'
    generator = helper / 'FixtureAssembly.exe'
    built = run([compiler, '/nologo', '/target:exe', f'/out:{generator}', f'/reference:{helper / "Mono.Cecil.dll"}', ROOT / 'tests/fixtures/FeatureAssembly.cs'])
    assert built.returncode == 0, built.stdout.decode(errors='replace')
    spec = {'schema': 1, 'assemblies': ['Fixture.dll'], 'features': {
        'privacy': {'methods': ['Fixture|Demo.Core|GetHidden'], 'fields': ['Fixture|Demo.Core|Hidden'],
                    'writers': ['Fixture|Demo.Core|Hidden']},
        'chat': {'methods': ['Fixture|Demo.Core|Send'], 'packets': ['Fixture|Demo.Packet'],
                 'route': 'Fixture|Demo.Core|Route', 'channel': 3}}}
    contract = directory / 'contract.json'
    contract.write_text(json.dumps(spec))
    def build(mode):
        path = directory / mode
        path.mkdir(exist_ok=True)
        binary = path / 'Fixture.dll'
        generated = run([generator, binary, mode])
        assert generated.returncode == 0
        return path, hashlib.sha256(binary.read_bytes()).hexdigest()
    def inspect(path):
        result = run([helper / 'FeatureProbe.exe', path, contract])
        return result.returncode, json.loads(result.stdout)
    baseline, digest = build('baseline')
    code, features = inspect(baseline)
    assert code == 0
    return build, inspect, digest, features

@pytest.mark.parametrize('mode', ['unrelated', 'metadata', 'other_channel', 'rebuild'])
def test_changed_binary_with_unchanged_features_remains_compatible(fixture_tools, mode):
    build, inspect, digest, baseline = fixture_tools
    path, changed_digest = build(mode)
    assert changed_digest != digest
    code, features = inspect(path)
    assert code == 0 and features == baseline

@pytest.mark.parametrize('mode,affected', [('privacy', 'privacy'), ('field_type', 'privacy'), ('writer', 'privacy'),
    ('channel', 'chat'), ('route', 'chat'), ('routing', 'chat'), ('packet', 'chat')])
def test_feature_changes_and_transitive_helpers_require_review(fixture_tools, mode, affected):
    build, inspect, _, baseline = fixture_tools
    path, _ = build(mode)
    code, features = inspect(path)
    assert code == 0 and features[affected] != baseline[affected]

def test_missing_field_and_malformed_binary_fail_closed(fixture_tools):
    build, inspect, _, _ = fixture_tools
    path, _ = build('missing')
    assert inspect(path) == (2, {'error': 'feature_probe_failed'})
    (path / 'Fixture.dll').write_bytes(b'synthetic invalid executable')
    assert inspect(path) == (2, {'error': 'feature_probe_failed'})
