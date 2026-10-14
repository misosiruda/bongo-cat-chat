"""Verify corresponding-source archives and extract their upstream notices.

Archives are retained for release publication. Nothing is executed or extracted
as a filesystem tree. The notices deliberately include a superset of upstream
build/test/platform components; this is not a claim that every component ships.
"""
import argparse
import concurrent.futures
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'packaging/licenses/sources.lock.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(row, cache):
    path = cache / row['file']
    if path.name != row['file']:
        raise ValueError('Invalid archive filename')
    if path.is_file() and digest(path) == row['sha256']:
        return path
    temporary = path.with_suffix(path.suffix + '.partial')
    # The mirror is listed by download.qt.io; the official SHA-256 is enforced.
    urls = [row['url']]
    if row['url'].startswith('https://download.qt.io/'):
        urls.insert(0, row['url'].replace('https://download.qt.io/', 'https://qt.mirror.constant.com/'))
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as stream:
                while block := response.read(1024 * 1024):
                    stream.write(block)
                    if stream.tell() > row['bytes']:
                        raise ValueError('Archive exceeds locked size')
            if temporary.stat().st_size != row['bytes'] or digest(temporary) != row['sha256']:
                raise ValueError('Archive checksum mismatch: ' + row['file'])
            temporary.replace(path)
            return path
        except OSError:
            if url == urls[-1]:
                raise
        finally:
            temporary.unlink(missing_ok=True)


def notices(row, cache):
    path = cache / row['file']
    if not path.is_file() or digest(path) != row['sha256']:
        raise ValueError('Download and verify corresponding source first: ' + row['file'])
    sections = [f"SOURCE: {row['url']}\nSHA-256: {row['sha256']}\n"]
    count = 0
    with tarfile.open(path, mode='r|*') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            selected = (re.search(r'(^|[-_.])(licen[cs]e|copying|copyright|notice|unlicense|patents|ftl)($|[-_.])', name.name, re.I)
                        or 'LICENSES' in name.parts or name.name in {'qt_attribution.json', 'README.chromium', 'bufferprocs_py37.h'})
            if not selected or not member.isfile():
                continue
            if member.size > 4 * 1024 * 1024:
                raise ValueError('Unexpectedly large notice: ' + member.name)
            data = archive.extractfile(member).read()
            if b'\0' in data:
                continue
            sections.extend([f"\n--- {member.name} ---\n", data.decode('utf-8', errors='replace')])
            count += 1
    if not count:
        raise ValueError('No licence notices found in ' + row['file'])
    return '\n'.join(sections)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--generate', action='store_true')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(LOCK.read_text())
    rows = manifest['archives']
    if args.download:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda row: fetch(row, args.cache), rows))
    if args.generate:
        qt, chromium = [], []
        for row in rows:
            result = notices(row, args.cache)
            (chromium if 'qtwebengine' in row['file'] else qt).append(result)
        destination = ROOT / 'packaging/licenses'
        (destination / 'QT-NOTICES.txt').write_text('\n\n'.join(qt), encoding='utf-8')
        content = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Qt WebEngine and Chromium notices</title><body><h1>Qt WebEngine and Chromium notices</h1><p>Upstream source notices, including build and platform components. See SOURCES.md for scope.</p><pre>' + html.escape('\n\n'.join(chromium)) + '</pre></body></html>'
        (destination / 'CHROMIUM-LICENSES.html').write_text(content, encoding='utf-8')
        manifest['notices'] = {name: digest(destination / name) for name in ('QT-NOTICES.txt', 'CHROMIUM-LICENSES.html')}
        LOCK.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    for row in rows:
        if digest(args.cache / row['file']) != row['sha256']:
            raise ValueError('Source archive changed')
    print(f"Verified {len(rows)} source archives; retained in {args.cache}")


if __name__ == '__main__':
    main()
