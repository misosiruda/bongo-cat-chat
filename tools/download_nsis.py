"""Fetch the pinned official NSIS compiler without running an installer."""
import hashlib
from pathlib import Path
import sys
import urllib.request

SHA256 = 'ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8'
URLS = ['https://prdownloads.sourceforge.net/nsis/nsis-3.13.zip?download',
        'https://master.dl.sourceforge.net/project/nsis/NSIS%203/3.13/nsis-3.13.zip?viasf=1']


def main():
    path = Path(sys.argv[1])
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256:
        return
    for url in URLS:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(4 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != SHA256:
                continue
            path.write_bytes(data)
            return
        except OSError:
            continue
    raise ValueError('Unable to download the verified NSIS 3.13 archive')


if __name__ == '__main__':
    main()
