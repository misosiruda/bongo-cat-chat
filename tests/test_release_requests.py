"""Exercise the release request CLI with a fake gh; no remote request is made."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def request(tmp_path, arguments):
    shell = shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell 7 is required')
    calls = tmp_path / 'calls.json'
    runner = tmp_path / 'request-test.ps1'
    script = str(ROOT / 'tools/request-release.ps1').replace("'", "''")
    destination = str(calls).replace("'", "''")
    # Named parameters are fixed by each test; values are safely quoted.
    invocation = []
    for arg in arguments:
        invocation.append(arg if arg in {'-Action', '-SourceSha', '-Version', '-CandidateTag', '-AllowUnsignedWindows', '-Publish'} else "'" + arg.replace("'", "''") + "'")
    runner.write_text(f"$ErrorActionPreference = 'Stop'\nfunction gh {{ $args | ConvertTo-Json -Compress | Set-Content -LiteralPath '{destination}'; $global:LASTEXITCODE = 0 }}\n& '{script}' {' '.join(invocation)}\n", encoding='utf-8-sig')
    result = subprocess.run([shell, '-NoProfile', '-File', str(runner)], capture_output=True)
    return result, json.loads(calls.read_text(encoding='utf-8-sig')) if calls.exists() else None


def test_request_requires_explicit_unsigned_acknowledgement(tmp_path):
    result, calls = request(tmp_path, ['-SourceSha', 'a' * 40, '-Version', '0.1.0.dev12'])
    assert result.returncode != 0
    assert calls is None


def test_request_targets_separate_repository_without_key(tmp_path):
    result, calls = request(tmp_path, ['-SourceSha', 'a' * 40, '-Version', '0.1.0.dev12', '-AllowUnsignedWindows'])
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert calls[:3] == ['workflow', 'run', 'release.yml']
    assert calls[calls.index('--repo') + 1] == 'misosiruda/bongo-cat-chat-release'
    assert 'source_sha=' + 'a' * 40 in calls


@pytest.mark.parametrize('publish', [False, True])
def test_publication_defaults_to_dry_run_and_keeps_original_feed(tmp_path, publish):
    args = ['-Action', 'Publish', '-CandidateTag', 'approved-v0.1.0.dev12-123-1']
    result, calls = request(tmp_path, args + (['-Publish'] if publish else []))
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert calls[calls.index('--repo') + 1] == 'misosiruda/bongo-cat-chat'
    assert ('dry_run=false' if publish else 'dry_run=true') in calls


@pytest.mark.parametrize('args', [
    ['-SourceSha', 'main', '-Version', '0.1.0.dev12', '-AllowUnsignedWindows'],
    ['-Action', 'Publish', '-CandidateTag', 'approved-v1.0.0-1-1; Write-Output unsafe'],
])
def test_invalid_request_never_invokes_github(tmp_path, args):
    result, calls = request(tmp_path, args)
    assert result.returncode != 0
    assert calls is None
