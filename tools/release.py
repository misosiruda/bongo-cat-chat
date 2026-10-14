"""Prepare signed update assets locally. This tool never publishes a release."""
import argparse
import base64
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from bongo_chat.updates import (ARCHIVE, MANIFEST, SIGNATURE, child, config, installation,
                               no_links, safe_member, verify_manifest, version)


def protect(raw, decrypt=False):
    """Windows user-scoped DPAPI, never machine-wide or interactive protection."""
    if os.name != 'nt':
        raise RuntimeError('Key storage requires Windows DPAPI')
    class Blob(c.Structure):
        _fields_ = [('size', w.DWORD), ('data', c.POINTER(c.c_ubyte))]
    buffer = (c.c_ubyte * len(raw)).from_buffer_copy(raw)
    incoming, outgoing = Blob(len(raw), buffer), Blob()
    crypt = c.WinDLL('crypt32', use_last_error=True)
    free = c.WinDLL('kernel32', use_last_error=True).LocalFree
    free.argtypes, free.restype = [c.c_void_p], c.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [c.POINTER(Blob), c.c_void_p, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
    function.restype = w.BOOL
    if not function(c.byref(incoming), None, None, None, None, 1, c.byref(outgoing)):
        raise c.WinError(c.get_last_error())
    try:
        return c.string_at(outgoing.data, outgoing.size)
    finally:
        free(outgoing.data)


def keygen(private_key, public_config):
    private_key, public_config = no_links(private_key), no_links(public_config)
    if private_key.exists():
        raise ValueError('Signing key exists; do not rotate it implicitly')
    settings = json.loads(public_config.read_text(encoding='utf-8'))
    if settings.get('public_key'):
        raise ValueError('Public key exists; do not rotate it implicitly')
    key = Ed25519PrivateKey.generate()
    private_key.parent.mkdir(parents=True, exist_ok=True)
    with private_key.open('xb') as stream:
        stream.write(protect(key.private_bytes_raw()))
    settings['public_key'] = base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii')
    public_config.write_text(json.dumps(settings, indent=2)+'\n', encoding='utf-8')
    print('Public key configured. Private key is protected for this Windows user; no release published.')


def pack(bundle, private_key, output):
    bundle, output = no_links(bundle), no_links(output)
    if output.is_relative_to(bundle):
        raise ValueError('Release assets must be outside the source bundle')
    settings = config()
    marker = installation(bundle)
    current = marker['active']
    version(current)
    key = Ed25519PrivateKey.from_private_bytes(protect(no_links(private_key).read_bytes(), decrypt=True))
    if base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii') != settings['public_key']:
        raise ValueError('Signing key does not match the pinned public key')
    output.mkdir(parents=True, exist_ok=True)
    if any(child(output, name).exists() for name in (ARCHIVE, MANIFEST, SIGNATURE)):
        raise ValueError('Release assets already exist; use a fresh output directory')
    app = child(bundle, 'versions', current, 'BongoCatChatApp')
    files = [(child(bundle, 'BongoCatChat.exe'), 'BongoCatChat.exe'),
             (child(bundle, 'uninstall.ps1'), 'uninstall.ps1')]
    files += [(no_links(path), 'BongoCatChatApp/' + path.relative_to(app).as_posix()) for path in app.rglob('*') if path.is_file()]
    with zipfile.ZipFile(output / ARCHIVE, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, name in files:
            safe_member(name)
            archive.write(path, name)
    with (output / ARCHIVE).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'schema': 1, 'repository': settings['repository'], 'version': current,
                'platform': 'windows-x64', 'archive': ARCHIVE, 'size': (output / ARCHIVE).stat().st_size,
                'sha256': digest, 'data_schema': 1, 'bootstrap_schema': 1}
    raw = json.dumps(manifest, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = key.sign(raw)
    verify_manifest(raw, signature, settings)
    (output / MANIFEST).write_bytes(raw)
    (output / SIGNATURE).write_bytes(signature)
    print(json.dumps({'version': current, 'bytes': manifest['size'], 'sha256': digest, 'published': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    generate = sub.add_parser('keygen')
    generate.add_argument('--private-key', type=Path, required=True)
    generate.add_argument('--public-config', type=Path, default=Path('src/bongo_chat/update-config.json'))
    package = sub.add_parser('pack')
    package.add_argument('--bundle', type=Path, required=True)
    package.add_argument('--private-key', type=Path, required=True)
    package.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'keygen':
        keygen(args.private_key, args.public_config)
    else:
        pack(args.bundle, args.private_key, args.output)


if __name__ == '__main__':
    main()
