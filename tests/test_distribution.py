import importlib.util
import hashlib
import io
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("filename,reason", [
    ("fmod.dll", "proprietary_fmod"), ("FMOD64.dll", "proprietary_fmod"),
    ("Qt6Graphs.dll", "unused_qt_gpl_module"),
    ("Qt6Quick3DUtils.dll", "unused_qt_gpl_module"),
    ("steam_api64.dll", "game_file"),
])
def test_audit_reports_blocked_components(tmp_path, filename, reason):
    (tmp_path / filename).write_bytes(b"inert fixture, not executable")
    report = tool("audit_distribution").inspect_bundle(tmp_path)
    assert report["known_blockers"] == [{"path": filename, "reason": reason}]
    assert len(report["native_files"][0]["sha256"]) == 64


def test_required_qt_modules_are_not_labelled_gpl_only(tmp_path):
    for name in ("Qt6Core.dll", "Qt6WebEngineCore.dll", "Qt6Pdf.dll", "Qt6Widgets.dll"):
        (tmp_path / name).write_bytes(b"inert")
    assert tool("audit_distribution").inspect_bundle(tmp_path)["known_blockers"] == []


@pytest.mark.parametrize("version", ["1.2", "1.2.3;code", "65536.0.0", "1.2.3.dev-1"])
def test_version_rejects_invalid_resources(version):
    with pytest.raises(ValueError):
        tool("windows_version").numeric_version(version)


def test_product_version_is_consistent(tmp_path):
    tool("windows_version").write_resources(tmp_path, "0.1.0.dev6")
    for name in ("BongoCatChat.txt", "BongoCatChatApp.txt", "FeatureProbe.Version.cs", "MemoryScan.Version.cs"):
        source = (tmp_path / name).read_text()
        assert "Bongo Cat Chat" in source and "0.1.0.dev6" in source
    assert 'AssemblyFileVersion("0.1.0.6")' in (tmp_path / "FeatureProbe.Version.cs").read_text()


def test_texture_decode_without_fmod():
    # A clean process avoids any already-imported UnityPy/FMOD masking the error.
    code = '''
import importlib.abc, runpy, sys
class NoAudio(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('fmod_toolkit', 'pyfmodex'):
            raise AssertionError('Audio dependency imported: ' + fullname)
sys.meta_path.insert(0, NoAudio())
runpy.run_path('packaging/hooks/disable_unity_audio.py')
import UnityPy
from UnityPy.export import Texture2DConverter, AudioClipConverter
from UnityPy.enums import TextureFormat, BuildTarget
pixel = bytes((20, 40, 60, 255))
image = Texture2DConverter.parse_image_data(pixel, 1, 1, TextureFormat.RGBA32,
                                           (2022, 3, 1, 0), BuildTarget.StandaloneWindows64)
assert image.convert('RGBA').tobytes() == pixel
assert not any(n.startswith(('fmod_toolkit', 'pyfmodex')) for n in sys.modules)
try:
    AudioClipConverter.extract_audioclip_samples(None)
except NotImplementedError:
    pass
else:
    raise AssertionError('Audio exports must fail explicitly')
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_notice_collection_keeps_licences_and_excludes_unused_fmod(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "tools/collect_license_notices.py"),
                             "--output", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "LICENSE.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()
    text = (tmp_path / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text
    assert "Mono.Cecil 0.11.6" in text and "CPython 3.13." in text
    assert "fmod_toolkit 0.1.3" not in text and "pyfmodex 0.7.2" not in text
    assert 'SOURCES.md' in text and 'OpenSSL' in text and 'Mesa 11.2.2' in text
    assert 'PyWinRT-3.2.1-LICENSE.txt' in text and '2021-2025 David Lechner' in text
    assert (tmp_path / 'SOURCES.md').is_file()
    assert (tmp_path / 'PRIVACY.en.md').read_bytes() == (ROOT / 'docs/privacy-policy.en.md').read_bytes()
    chromium = (tmp_path / 'CHROMIUM-LICENSES.html').read_text(encoding='utf-8')
    assert 'Chromium' in chromium and 'Copyright' in chromium and 'ffmpeg' in chromium


@pytest.mark.parametrize('mirror_payload', [b'', b'<html>bad mirror</html>', b'x' * 64, OSError('offline')])
def test_source_download_uses_official_url_after_bad_mirror(tmp_path, monkeypatch, mirror_payload):
    module = tool('prepare_source_notices')
    payload = b'verified fixture source'
    row = {'file': 'fixture.tar.xz', 'url': 'https://download.qt.io/fixture.tar.xz',
           'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    calls = []
    def download(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            if isinstance(mirror_payload, OSError):
                raise mirror_payload
            return io.BytesIO(mirror_payload)
        return io.BytesIO(payload)
    monkeypatch.setattr(module.urllib.request, 'urlopen', download)
    path = module.fetch(row, tmp_path)
    assert calls == ['https://qt.mirror.constant.com/fixture.tar.xz', row['url']]
    assert path.read_bytes() == payload
    assert not list(tmp_path.glob('*.partial'))


def test_source_download_rejects_both_bad_endpoints(tmp_path, monkeypatch):
    module = tool('prepare_source_notices')
    payload = b'verified'
    row = {'file': 'fixture.tar.xz', 'url': 'https://download.qt.io/fixture.tar.xz',
           'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    calls = []
    def download(url, **kwargs):
        calls.append(url)
        return io.BytesIO(b'corrupt!')  # Correct size, wrong hash on both endpoints.
    monkeypatch.setattr(module.urllib.request, 'urlopen', download)
    with pytest.raises(ValueError, match='checksum mismatch'):
        module.fetch(row, tmp_path)
    assert len(calls) == 2
    assert not (tmp_path / row['file']).exists()
    assert not list(tmp_path.glob('*.partial'))
