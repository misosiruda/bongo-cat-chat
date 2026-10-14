"""Build gates and signing order; synthetic signatures are not Windows trust evidence."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows packaging')
REPO = Path(__file__).resolve().parents[1]
POWERSHELL = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
THUMBPRINT = 'A' * 40


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_script(path, *args, env=None):
    return subprocess.run([str(POWERSHELL), '-NoLogo', '-NoProfile', '-NonInteractive',
                           '-ExecutionPolicy', 'Bypass', '-File', str(path), *map(str, args)],
                          env=env, capture_output=True, timeout=60,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def ps(tmp_path, body):
    driver = tmp_path / 'driver.ps1'
    driver.write_text("$ErrorActionPreference = 'Stop'\n"
                      "[Console]::OutputEncoding = [Text.UTF8Encoding]::new()\n"
                      f". {quote(REPO / 'packaging/code-signing.ps1')}\n{body}\n", encoding='utf-8-sig')
    return run_script(driver)


@pytest.fixture
def settings(tmp_path):
    path = tmp_path / "개인 서명 '설정'.json"
    data = {'schema': 1, 'signToolPath': str(POWERSHELL),
            'certificateThumbprint': THUMBPRINT, 'certificateStoreLocation': 'CurrentUser',
            'timestampUrl': 'http://timestamp.example.test'}
    path.write_text(json.dumps(data), encoding='utf-8')
    return path, data


def make_bundle(root):
    bundle = root / 'bundle'
    app = bundle / 'versions/0.1.0.dev7/BongoCatChatApp'
    helper = app / '_internal/bongo_chat/compatibility/FeatureProbe.exe'
    helper.parent.mkdir(parents=True)
    targets = [bundle / 'BongoCatChat.exe', app / 'BongoCatChatApp.exe', helper]
    for target in targets:
        target.write_bytes(b'inert executable fixture')
    (bundle / '.bongo-cat-chat-install').write_text(json.dumps(
        {'schema': 2, 'active': '0.1.0.dev7', 'previous': None}))
    for name in ('install.ps1', 'uninstall.ps1'):
        shutil.copyfile(REPO / 'packaging' / name, bundle / name)
    (app / '_internal/vendor.dll').write_bytes(b'third-party sentinel')
    return bundle, targets


@pytest.mark.parametrize('arguments', ['', "-SigningConfig 'unused' -AllowUnsigned"])
def test_signing_policy_must_be_explicit(tmp_path, arguments):
    result = ps(tmp_path, f'Get-CodeSigningSettings {arguments}')
    assert result.returncode != 0


def test_unsigned_mode_has_an_explicit_warning(tmp_path):
    result = ps(tmp_path, 'Get-CodeSigningSettings -AllowUnsigned')
    assert result.returncode == 0
    assert b'UNSIGNED DEVELOPMENT BUILD' in result.stdout


@pytest.mark.parametrize(('script', 'arguments'), [
    ('build.ps1', ()),
    ('build-setup.ps1', ('-Bundle', 'missing-bundle', '-NsisPath', 'missing-nsis')),
])
def test_build_entrypoints_reject_implicit_unsigned_output(script, arguments):
    result = run_script(REPO / 'packaging' / script, *arguments)
    assert result.returncode != 0
    assert b'Windows signing is required' in result.stderr


def test_release_cli_requires_explicit_signing_policy(tmp_path):
    output = tmp_path / 'release'
    result = subprocess.run([sys.executable, str(REPO / 'tools/release.py'), 'pack',
                             '--bundle', str(tmp_path / 'missing-bundle'),
                             '--private-key', str(tmp_path / 'missing-key'), '--output', str(output)],
                            capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 2
    assert b'--signing-config' in result.stderr and b'--allow-unsigned' in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(('field', 'value'), [
    ('schema', 2), ('certificateThumbprint', 'any'),
    ('certificateStoreLocation', 'Root'), ('timestampUrl', 'file:///tmp/stamp'),
    ('timestampUrl', 'https://user:password@example.test'),
    ('timestampUrl', 'https://example.test/#fragment'), ('timestampUrl', ''),
    ('signToolPath', 'relative.exe'), ('signToolPath', 'C:/missing-sign-tool.exe'),
    ('password', 'must-not-be-a-setting'),
])
def test_bad_signing_settings_fail_before_signing(tmp_path, settings, field, value):
    path, data = settings
    data[field] = value
    path.write_text(json.dumps(data), encoding='utf-8')
    result = ps(tmp_path, f'Get-CodeSigningSettings -SigningConfig {quote(path)}')
    assert result.returncode != 0


@pytest.mark.parametrize('store', ['CurrentUser', 'LocalMachine'])
def test_sign_then_verify_uses_exact_certificate_and_sha256_timestamp(tmp_path, settings, store):
    path, data = settings
    data['certificateStoreLocation'] = store
    path.write_text(json.dumps(data))
    target = tmp_path / '한글 실행 파일.exe'
    target.write_bytes(b'inert')
    result = ps(tmp_path, f'''
$settings = Get-CodeSigningSettings -SigningConfig {quote(path)}
$script:calls = @()
function Invoke-CodeSigningTool {{
    param($Settings, [string[]]$Arguments)
    $script:calls += ,$Arguments
}}
function Get-AuthenticodeSignature {{
    param($LiteralPath)
    [pscustomobject]@{{Status='Valid'; SignatureType='Authenticode';
        SignerCertificate=@{{Thumbprint='{THUMBPRINT}'}}; TimeStamperCertificate=@{{Subject='fixture'}}}}
}}
Set-WindowsSignature -Settings $settings -Path {quote(target)}
ConvertTo-Json -InputObject $script:calls -Compress
''')
    assert result.returncode == 0, result.stderr
    sign, verify = json.loads(result.stdout)
    assert sign[:7] == ['sign', '/fd', 'SHA256', '/tr', data['timestampUrl'], '/td', 'SHA256']
    assert sign[sign.index('/sha1') + 1] == THUMBPRINT
    assert ('/sm' in sign) == (store == 'LocalMachine')
    assert sign[-1] == str(target)
    assert verify == ['verify', '/pa', '/all', '/tw', str(target)]


@pytest.mark.parametrize('exit_code', [1, 2])
def test_sign_tool_errors_and_warnings_are_fatal(tmp_path, settings, exit_code):
    path, _ = settings
    result = ps(tmp_path, f'''
$settings = Get-CodeSigningSettings -SigningConfig {quote(path)}
Invoke-CodeSigningTool -Settings $settings -Arguments @('-NoProfile', '-NonInteractive', '-Command', 'exit {exit_code}')
''')
    assert result.returncode != 0
    assert f'exit {exit_code}'.encode() in result.stderr


@pytest.mark.parametrize(('status', 'kind', 'thumbprint', 'timestamp'), [
    ('NotSigned', 'None', THUMBPRINT, '$null'),
    ('HashMismatch', 'Authenticode', THUMBPRINT, "@{Subject='fixture'}"),
    ('Valid', 'Catalog', THUMBPRINT, "@{Subject='fixture'}"),
    ('Valid', 'Authenticode', 'B' * 40, "@{Subject='fixture'}"),
    ('Valid', 'Authenticode', THUMBPRINT, '$null'),
])
def test_missing_tampered_wrong_publisher_and_untimestamped_signatures_are_rejected(
        tmp_path, settings, status, kind, thumbprint, timestamp):
    path, _ = settings
    target = tmp_path / 'inert.exe'
    target.write_bytes(b'inert')
    result = ps(tmp_path, f'''
$settings = Get-CodeSigningSettings -SigningConfig {quote(path)}
function Get-AuthenticodeSignature {{
    param($LiteralPath)
    [pscustomobject]@{{Status='{status}'; SignatureType='{kind}';
        SignerCertificate=@{{Thumbprint='{thumbprint}'}}; TimeStamperCertificate={timestamp}}}
}}
Assert-WindowsSignature -Settings $settings -Path {quote(target)}
''')
    assert result.returncode != 0


def test_bundle_preflight_and_ownership(tmp_path):
    bundle, targets = make_bundle(tmp_path)
    body = f'''
$script:targets = @()
function Set-WindowsSignature {{ param($Settings, $Path); $script:targets += $Path }}
Invoke-BundleSigning -Settings @{{}} -Bundle {quote(bundle)}
ConvertTo-Json -InputObject $script:targets -Compress
'''
    result = ps(tmp_path, body)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == list(map(str, targets))
    assert (targets[1].parent / '_internal/vendor.dll').read_bytes() == b'third-party sentinel'
    targets[-1].unlink()
    result = ps(tmp_path, body)
    assert result.returncode != 0
    assert not result.stdout  # no earlier target is signed before all paths are checked


def test_real_unsigned_bundle_fails_verification(tmp_path, settings):
    bundle, _ = make_bundle(tmp_path)
    result = run_script(REPO / 'packaging/sign-bundle.ps1', '-Bundle', bundle,
                        '-SigningConfig', settings[0], '-VerifyOnly')
    assert result.returncode != 0
    assert b'Missing or invalid embedded Windows signature' in result.stderr


@pytest.fixture
def release_tool():
    spec = importlib.util.spec_from_file_location('release_signing_test', REPO / 'tools/release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_verifies_windows_signature_before_keys_or_output(tmp_path, release_tool, monkeypatch):
    bundle, _ = make_bundle(tmp_path)
    output = tmp_path / 'release'
    def reject(*args):
        raise RuntimeError('unsigned bundle')
    monkeypatch.setattr(release_tool, 'verify_windows_signatures', reject)
    with pytest.raises(RuntimeError, match='unsigned bundle'):
        release_tool.pack(bundle, tmp_path / 'key-that-must-not-be-read', output,
                          signing_config=tmp_path / 'signing.json')
    assert not output.exists()
    with pytest.raises(ValueError, match='explicitly'):
        release_tool.pack(bundle, tmp_path / 'missing-key', output)


@pytest.mark.parametrize('unsigned', [False, True])
def test_update_archive_hash_and_ed25519_cover_final_binary_bytes(tmp_path, release_tool, monkeypatch, unsigned):
    bundle, targets = make_bundle(tmp_path)
    output = tmp_path / 'release'
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / 'synthetic-test-key'
    key_path.write_bytes(key.private_bytes_raw())
    monkeypatch.setattr(release_tool, 'protect', lambda raw, **kwargs: raw)
    monkeypatch.setattr(release_tool, 'config', lambda: {
        'repository': 'fixture-owner/fixture-releases',
        'public_key': base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii')})
    targets[0].write_bytes(b'final executable bytes after synthetic signing')
    checked = []
    monkeypatch.setattr(release_tool, 'verify_windows_signatures', lambda *args: checked.append(args))
    release_tool.pack(bundle, key_path, output, signing_config=None if unsigned else tmp_path / 'signing.json',
                      allow_unsigned=unsigned)
    assert len(checked) == int(not unsigned)
    raw = (output / release_tool.MANIFEST).read_bytes()
    manifest = json.loads(raw)
    zipped = output / release_tool.ARCHIVE
    assert hashlib.sha256(zipped.read_bytes()).hexdigest() == manifest['sha256']
    key.public_key().verify((output / release_tool.SIGNATURE).read_bytes(), raw)
    with zipfile.ZipFile(zipped) as archive:
        assert archive.read('BongoCatChat.exe') == targets[0].read_bytes()


@pytest.fixture
def nsis_project(tmp_path):
    nsis = os.environ.get('BONGO_TEST_NSIS_PATH')
    if not nsis:
        pytest.skip('Set BONGO_TEST_NSIS_PATH for actual NSIS compiler integration')
    project = tmp_path / '한글 빌드 폴더'
    shutil.copytree(REPO / 'packaging', project / 'packaging')
    (project / 'docs').mkdir()
    shutil.copy2(REPO / 'docs/privacy-policy.md', project / 'docs/privacy-policy.md')
    bundle, _ = make_bundle(project / 'dist')
    return project, bundle, Path(nsis)


def test_nsis_unsigned_opt_in_and_final_hash(nsis_project):
    project, bundle, nsis = nsis_project
    args = ('-Bundle', bundle, '-NsisPath', nsis, '-AllowUnsigned')
    script = project / 'packaging/build-setup.ps1'
    result = run_script(script, *args)
    assert result.returncode == 0, result.stdout + result.stderr
    setup = project / 'dist/setup/BongoCatChat-0.1.0.dev7-windows-x64-Setup.exe'
    before = setup.read_bytes()
    checksum = setup.with_suffix('.exe.sha256').read_text().strip()
    assert checksum == f'{hashlib.sha256(before).hexdigest()}  {setup.name}'
    assert not list(setup.parent.glob('.setup-*'))
    assert run_script(script, *args).returncode != 0
    assert setup.read_bytes() == before


@pytest.mark.parametrize('failure', ['none', 'uninstaller', 'setup'])
def test_nsis_runs_uninstaller_hook_and_publishes_only_after_setup_signing(nsis_project, settings, failure):
    project, bundle, nsis = nsis_project
    config_path, _ = settings
    log = project / 'hook.txt'
    # Test doubles only in this isolated project: no certificate or trust store changes.
    library = project / 'packaging/code-signing.ps1'
    with library.open('a', encoding='utf-8') as stream:
        stream.write(f'''
function Invoke-BundleSigning {{ param($Settings, $Bundle, [switch]$VerifyOnly) }}
function Set-WindowsSignature {{
    param($Settings, $Path)
    if ('{failure}' -eq 'setup') {{ throw 'synthetic setup signing failure' }}
    Add-Content -LiteralPath $Path -Value 'synthetic signature bytes' -Encoding ascii
}}
''')
    hook = project / 'packaging/sign-file.ps1'
    hook.write_text(f'''
param([string]$Path)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Path)) {{ throw 'uninstaller missing' }}
if ($env:BONGO_CODE_SIGNING_CONFIG -ne {quote(config_path)}) {{ throw 'config path changed' }}
[IO.File]::WriteAllText({quote(log)}, $Path)
exit $(if ('{failure}' -eq 'uninstaller') {{ 1 }} else {{ 0 }})
''', encoding='utf-8-sig')
    result = run_script(project / 'packaging/build-setup.ps1', '-Bundle', bundle, '-NsisPath', nsis,
                        '-SigningConfig', config_path)
    assert log.exists(), result.stdout + result.stderr
    output = project / 'dist/setup'
    assert not list(output.glob('.setup-*'))
    if failure == 'none':
        assert result.returncode == 0, result.stdout + result.stderr
        setup, = output.glob('*Setup.exe')
        assert b'synthetic signature bytes' in setup.read_bytes()
        assert setup.with_suffix('.exe.sha256').read_text().split()[0] == hashlib.sha256(setup.read_bytes()).hexdigest()
    else:
        assert result.returncode != 0
        assert not list(output.iterdir())
