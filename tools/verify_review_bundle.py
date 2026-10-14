"""Verify an unsigned review bundle and run its offline, isolated renderer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pefile

from audit_distribution import ROOT, inspect_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    bundle, evidence = args.bundle.resolve(), args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    version = json.loads((bundle / '.bongo-cat-chat-install').read_text(encoding='utf-8-sig'))['active']
    app = bundle / 'versions' / version / 'BongoCatChatApp'
    legal = app / '_internal/bongo_chat/legal'
    products = {}
    for target in (bundle / 'BongoCatChat.exe', app / 'BongoCatChatApp.exe',
                   app / '_internal/bongo_chat/compatibility/FeatureProbe.exe',
                   app / '_internal/bongo_chat/compatibility/MemoryScan.exe'):
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
    for relative in ('ui/index.html', 'ui/app.js', 'ui/messenger.css', 'update-config.json', 'feature-contract.json'):
        if (app / '_internal/bongo_chat' / relative).read_bytes() != (ROOT / 'src/bongo_chat' / relative).read_bytes():
            raise ValueError('Packaged resource differs from this checkout: ' + relative)
    expected = ['LICENSE.txt', 'PRIVACY.md', 'THIRD-PARTY-NOTICES.txt', 'CHROMIUM-LICENSES.html', 'SOURCES.md', 'sources.lock.json']
    hashes = {}
    for name in expected:
        data = (legal / name).read_bytes()
        if len(data) < 100:
            raise ValueError('Missing or empty notice: ' + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
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
    (evidence / 'bundle-validation.json').write_text(json.dumps({'version': version, 'products': products, 'notice_hashes': hashes, 'native_files': len(audit['native_files']), 'known_blockers': [], 'offline_renderer': smoke, 'authenticode': 'unsigned review candidate'}, indent=2), encoding='utf-8')
    print('Bundle notices, dependency guards and frozen offline renderer verified')


if __name__ == '__main__':
    main()
