"""Verify an unsigned review bundle and run its offline, isolated renderer."""
import argparse
import hashlib
import json
import marshal
import os
from pathlib import Path
import subprocess
import sys

import pefile
from PyInstaller.archive.readers import CArchiveReader

from audit_distribution import ROOT, inspect_bundle


def verify_winrt(app):
    """Import bundled projections in an isolated interpreter, without OS delivery.

    Pure dependencies normally come from the embedded PYZ. Load its actual
    typing_extensions code, so developer site-packages cannot hide omissions.
    """
    pyz = CArchiveReader(str(app / 'BongoCatChatApp.exe')).open_embedded_archive('PYZ.pyz')
    dependency = marshal.dumps(pyz.extract('typing_extensions'))
    code = '''
import marshal, sys, types
sys.path.insert(0, sys.argv[1])
module = types.ModuleType('typing_extensions')
module.__file__ = 'bundled:typing_extensions'
sys.modules[module.__name__] = module
exec(marshal.loads(sys.stdin.buffer.read()), module.__dict__)
from winrt.runtime import init_apartment, ApartmentType
init_apartment(ApartmentType.SINGLE_THREADED)
from winrt.windows.data.xml.dom import XmlDocument
from winrt.windows.ui.notifications import ToastNotification
import winrt._winrt
assert winrt._winrt.__file__.startswith(sys.argv[1])
document = XmlDocument()
document.load_xml('<toast><visual><binding template="ToastGeneric"><text>synthetic</text></binding></visual></toast>')
toast = ToastNotification(document)
toast.tag, toast.group = 'verification', 'verification'
assert toast.tag == 'verification'
'''
    result = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(app / '_internal')],
                            input=dependency, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Bundled WinRT import/serialization failed: ' + result.stderr.decode('utf-8', errors='replace'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    bundle, evidence = args.bundle.resolve(), args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    version = json.loads((bundle / '.bongo-cat-chat-install').read_text(encoding='utf-8-sig'))['active']
    app = bundle / 'versions' / version / 'BongoCatChatApp'
    verify_winrt(app)
    legal = app / '_internal/bongo_chat/legal'
    products = {}
    for target in (bundle / 'BongoCatChat.exe', app / 'BongoCatChatApp.exe',
                   app / '_internal/bongo_chat/compatibility/FeatureProbe.exe',
                   app / '_internal/bongo_chat/compatibility/MemoryScan.exe',
                   app / '_internal/bongo_chat/merge-assets/MergePrepare.exe'):
        with pefile.PE(str(target)) as executable:
            entries = {}
            for group in getattr(executable, 'FileInfo', []):
                for section in group:
                    for table in getattr(section, 'StringTable', []):
                        entries.update(table.entries)
            product = {key: entries.get(key.encode(), b'').decode('utf-8')
                       for key in ('ProductName', 'ProductVersion')}
        if product != {'ProductName': 'Bongo Cat Chat', 'ProductVersion': version}:
            raise ValueError(f'Incorrect signing metadata: {target.name}: {product}')
        products[str(target.relative_to(bundle))] = product
    # A developer's editable install must never supply stale UI/config assets.
    merge_assets=app/'_internal/bongo_chat/merge-assets'
    merge_contract=json.loads((merge_assets/'contract.json').read_text(encoding='utf-8-sig'))
    if merge_contract['schema'] != 2 or (merge_assets/'Bridge.cs').read_bytes() != (ROOT/'tools/merge_bridge/Bridge.cs').read_bytes():
        raise ValueError('Packaged merge source differs from this checkout')
    for name,key in [('Bridge.cs','source_sha256'),('MergePrepare.exe','prepare_sha256'),('Mono.Cecil.dll','cecil_sha256')]:
        if hashlib.sha256((merge_assets/name).read_bytes()).hexdigest()!=merge_contract[key]:
            raise ValueError('Packaged merge payload digest mismatch')
    for relative in ('ui/index.html', 'ui/app.js', 'ui/messenger.css', 'ui/translations.json', 'ui/app-icon.png',
                     'ui/app-icon.ico', 'ui/favicon.ico', 'update-config.json', 'feature-contract.json'):
        if (app / '_internal/bongo_chat' / relative).read_bytes() != (ROOT / 'src/bongo_chat' / relative).read_bytes():
            raise ValueError('Packaged resource differs from this checkout: ' + relative)
    expected = ['LICENSE.txt', 'PRIVACY.md', 'PRIVACY.en.md', 'THIRD-PARTY-NOTICES.txt', 'CHROMIUM-LICENSES.html', 'SOURCES.md', 'sources.lock.json']
    hashes = {}
    for name in expected:
        data = (legal / name).read_bytes()
        if len(data) < 100:
            raise ValueError('Missing or empty notice: ' + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
    if (legal / 'PRIVACY.en.md').read_bytes() != (ROOT / 'docs/privacy-policy.en.md').read_bytes():
        raise ValueError('Packaged English privacy notice differs from this checkout')
    manifest = json.loads((legal / 'sources.lock.json').read_text())
    if hashes['CHROMIUM-LICENSES.html'] != manifest['notices']['CHROMIUM-LICENSES.html']:
        raise ValueError('Chromium notice changed during packaging')
    audit = inspect_bundle(bundle)
    if audit['known_blockers']:
        raise ValueError(audit['known_blockers'])
    report = evidence / 'offline-smoke.json'
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu')
    completed = subprocess.run([str(app / 'BongoCatChatApp.exe'), '--offline', '--data-dir', str(evidence / 'synthetic-data'), '--smoke-report', str(report)],
                               env=environment, capture_output=True, timeout=90)
    smoke = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    if completed.returncode or not smoke.get('renderer') or smoke.get('console_errors') or smoke.get('steam_connected'):
        raise ValueError(f'Frozen offline smoke failed: {completed.returncode}, {smoke}')
    (evidence / 'bundle-validation.json').write_text(json.dumps({'version': version, 'products': products, 'notice_hashes': hashes, 'native_files': len(audit['native_files']), 'known_blockers': [], 'offline_renderer': smoke, 'bundled_winrt': True, 'authenticode': 'unsigned review candidate'}, indent=2), encoding='utf-8')
    print('Bundle notices, dependency guards and frozen offline renderer verified')


if __name__ == '__main__':
    main()
