"""Signed GitHub Releases, bounded downloads and staging. Never reads chat data."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ARCHIVE = 'bongo-cat-chat-windows-x64.zip'
MANIFEST = 'update-manifest.json'
SIGNATURE = 'update-manifest.sig'
MARKER = '.bongo-cat-chat-install'
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_EXPANDED = 2 * MAX_ARCHIVE
CHECK_INTERVAL = 6 * 60 * 60
ASSETS = {ARCHIVE, MANIFEST, SIGNATURE}
HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


class UpdateError(ValueError):
    pass


def version(value):
    if not isinstance(value, str):
        raise UpdateError('invalid_version')
    match = re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.dev(0|[1-9][0-9]*))?', value or '')
    if not match or len(value) > 50:
        raise UpdateError('invalid_version')
    major, minor, patch, dev = match.groups()
    return int(major), int(minor), int(patch), int(dev is None), int(dev or 0)


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise UpdateError('duplicate_key')
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(result, dict):
            raise UpdateError('invalid_json')
        return result
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise UpdateError('invalid_json') from exc


def config():
    return load_json(Path(__file__).with_name('update-config.json').read_bytes())


def no_links(path):
    """Check lexical ancestors before resolving, including Windows junctions."""
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            attributes = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, 'st_file_attributes', 0) & 0x400:
            raise UpdateError('linked_path')
    return path


def child(root, *parts):
    root = no_links(root)
    target = no_links(root.joinpath(*parts))
    if not target.is_relative_to(root) or target == root:
        raise UpdateError('unsafe_path')
    return target


def remove_owned(root, path):
    path = child(root, Path(path).relative_to(root))
    if path.is_dir():
        # Refuse all reparse points before recursive removal, not just the root.
        for entry in path.rglob('*'):
            no_links(entry)
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def atomic_bytes(path, payload):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = child(path.parent, f'.{path.name}-{uuid4().hex}.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, payload):
    atomic_bytes(path, json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def installation(root):
    root = no_links(root)
    marker = child(root, MARKER)
    if marker.stat().st_size > 4096:
        raise UpdateError('invalid_installation')
    data = load_json(marker.read_bytes())
    if not isinstance(data, dict) or type(data.get('schema')) is not int or data['schema'] != 2:
        raise UpdateError('invalid_installation')
    version(data.get('active'))
    if data.get('previous') is not None:
        version(data['previous'])
    return data


def verify_manifest(raw, signature, settings):
    if len(raw) > 16384 or len(signature) != 64:
        raise UpdateError('invalid_manifest')
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(settings['public_key'], validate=True))
        key.verify(signature, raw)
    except (InvalidSignature, ValueError, KeyError) as exc:
        raise UpdateError('invalid_signature') from exc
    value = load_json(raw)
    required = {'schema', 'repository', 'version', 'platform', 'archive', 'size', 'sha256', 'data_schema', 'bootstrap_schema'}
    if not isinstance(value, dict) or set(value) != required:
        raise UpdateError('invalid_manifest')
    if any(type(value[k]) is not int for k in ('schema', 'bootstrap_schema', 'data_schema', 'size')) or not isinstance(value['sha256'], str):
        raise UpdateError('invalid_manifest')
    version(value['version'])
    if (value['schema'] != 1 or value['bootstrap_schema'] != 1 or value['data_schema'] != 1
            or value['platform'] != 'windows-x64' or value['repository'] != settings['repository']
            or value['archive'] != ARCHIVE or type(value['size']) is not int
            or not 1 <= value['size'] <= MAX_ARCHIVE or not re.fullmatch('[a-f0-9]{64}', value['sha256'])):
        raise UpdateError('unsupported_manifest')
    return value


def verify_archive(path, manifest):
    path = no_links(path)
    if path.stat().st_size != manifest['size']:
        raise UpdateError('invalid_size')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != manifest['sha256']:
        raise UpdateError('invalid_checksum')


def staged_manifest(root, settings):
    pending = child(root, '.updates', 'pending')
    raw = child(pending, MANIFEST).read_bytes()
    signature = child(pending, SIGNATURE).read_bytes()
    manifest = verify_manifest(raw, signature, settings)
    verify_archive(child(pending, ARCHIVE), manifest)
    return manifest


def safe_member(name):
    parts = PurePosixPath(name).parts
    if (not parts or len(name) > 240 or name.startswith('/') or '\\' in name
            or name.rstrip('/') != '/'.join(parts)):
        raise UpdateError('unsafe_archive_path')
    for part in parts:
        if (part in ('.', '..') or part.endswith((' ', '.')) or re.search(r'[\x00-\x1f:<>"|?*]', part)
                or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', part)):
            raise UpdateError('unsafe_archive_path')
    if parts[-1].lower() in {'steam_api64.dll', 'assembly-csharp.dll', 'mono-2.0-bdwgc.dll', 'sharedassets0.assets', 'resources.assets', 'heathen.steamworks.dll'}:
        raise UpdateError('game_file_in_archive')
    if parts[0] not in {'BongoCatChat.exe', 'BongoCatChatApp', 'uninstall.ps1'}:
        raise UpdateError('unexpected_archive_member')
    if parts[0] != 'BongoCatChatApp' and len(parts) != 1:
        raise UpdateError('unexpected_archive_member')
    return parts


def extract_archive(archive, destination):
    destination = no_links(destination)
    if destination.exists():
        raise UpdateError('stage_exists')
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        names, total = set(), 0
        if len(entries) > 20000:
            raise UpdateError('archive_too_large')
        for entry in entries:
            parts = safe_member(entry.filename)
            name = '/'.join(parts).lower()
            mode = entry.external_attr >> 16
            if (name in names or stat.S_ISLNK(mode) or entry.flag_bits & 1
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise UpdateError('unsafe_archive_entry')
            names.add(name)
            total += entry.file_size
        if total > MAX_EXPANDED or not {'bongocatchat.exe', 'bongocatchatapp/bongocatchatapp.exe', 'uninstall.ps1'} <= names:
            raise UpdateError('invalid_archive')
        if not any(name.startswith('bongocatchatapp/_internal/') for name in names):
            raise UpdateError('invalid_archive')
        if shutil.disk_usage(destination.parent).free < total + 64 * 1024 * 1024:
            raise UpdateError('disk_space')
        destination.mkdir()
        for entry in entries:
            target = child(destination, *safe_member(entry.filename))
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as incoming, target.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 128 * 1024)


def trusted_url(url):
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in HOSTS or parts.username or parts.password
            or parts.port not in (None, 443) or parts.fragment):
        raise UpdateError('untrusted_download')
    return url


class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, trusted_url(newurl))


class Transport:
    def __init__(self, cancelled=None):
        self.cancelled = cancelled or threading.Event()
        self.opener = urllib.request.build_opener(GitHubRedirect())

    def download(self, url, target, limit):
        if self.cancelled.is_set():
            raise UpdateError('cancelled')
        request = urllib.request.Request(trusted_url(url), headers={
            'Accept': 'application/vnd.github+json' if url.startswith('https://api.github.com/') else 'application/octet-stream',
            'User-Agent': 'BongoCatChat-Updater', 'X-GitHub-Api-Version': '2026-03-10'})
        started, total = time.monotonic(), 0
        with self.opener.open(request, timeout=15) as response, no_links(target).open('xb') as stream:
            while True:
                if self.cancelled.is_set() or time.monotonic() - started > 1800:
                    raise UpdateError('cancelled')
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise UpdateError('download_too_large')
                stream.write(chunk)
        return total


def check_and_stage(root, current, settings, transport, report):
    installation(root)
    repository = settings['repository']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not settings.get('public_key'):
        raise UpdateError('not_configured')
    cache = child(root, '.updates')
    cache.mkdir(exist_ok=True)
    working = child(cache, 'download-' + uuid4().hex)
    working.mkdir()
    try:
        transport.download(f'https://api.github.com/repos/{repository}/releases/latest', working / 'release.json', 256 * 1024)
        release = load_json((working / 'release.json').read_bytes())
        if not isinstance(release, dict):
            raise UpdateError('invalid_release')
        tag = release.get('tag_name', '')
        if release.get('draft') is not False or release.get('prerelease') is not False or not isinstance(tag, str) or not tag.startswith('v'):
            raise UpdateError('invalid_release')
        if version(tag[1:]) <= version(current):
            report('current', current)
            return
        assets = release.get('assets', [])
        if not isinstance(assets, list) or not all(isinstance(a, dict) for a in assets):
            raise UpdateError('invalid_release')
        for name in ASSETS:
            if sum(a.get('name') == name and a.get('state') == 'uploaded' for a in assets) != 1:
                raise UpdateError('missing_release_assets')
        base = f'https://github.com/{repository}/releases/download/{tag}/'
        transport.download(base + MANIFEST, working / MANIFEST, 16384)
        transport.download(base + SIGNATURE, working / SIGNATURE, 64)
        manifest = verify_manifest((working / MANIFEST).read_bytes(), (working / SIGNATURE).read_bytes(), settings)
        if tag != 'v' + manifest['version']:
            raise UpdateError('version_mismatch')
        failed = child(cache, 'attempted.json')
        if failed.exists() and load_json(failed.read_bytes()).get('sha256') == manifest['sha256']:
            raise UpdateError('previous_apply_failed')
        if shutil.disk_usage(cache).free < manifest['size'] * 4 + 128 * 1024 * 1024:
            raise UpdateError('disk_space')
        pending = child(cache, 'pending')
        if pending.exists():
            try:
                if staged_manifest(root, settings) == manifest:
                    report('ready', manifest['version'])
                    return
            except (OSError, ValueError):
                pass
        report('downloading', manifest['version'])
        transport.download(base + ARCHIVE, working / ARCHIVE, manifest['size'])
        verify_archive(working / ARCHIVE, manifest)
        (working / 'release.json').unlink()
        if pending.exists():
            remove_owned(cache, pending)
        os.replace(working, pending)
        report('ready', manifest['version'])
    finally:
        if working.exists():
            remove_owned(cache, working)


class UpdateManager:
    """The background thread uses only the update cache, never SQLite or Qt."""
    def __init__(self, root, current, offline=False, settings=None, transport=None, allowed=True):
        self.root, self.current = root, current
        self.settings = settings if settings is not None else config()
        self.cancelled = threading.Event()
        self.transport = transport
        self.lock, self.thread = threading.Lock(), None
        self.available = bool(root and not offline)
        self.inactive_state = 'offline' if offline else 'development'
        self.allowed, self.closed = allowed, False
        self.enabled = self.available and allowed
        self.state = {'state': 'idle' if self.enabled else 'offline' if offline else 'development', 'version': current, 'current': current}
        if self.enabled:
            try:
                result = load_json(child(root, '.updates', 'result.json').read_bytes())
                if result.get('state') in {'applied', 'rolled_back', 'apply_failed'}:
                    self.state['state'] = ('apply_failed' if result['state'] == 'applied'
                                           and result.get('version') != current else result['state'])
            except (OSError, ValueError, AttributeError):
                pass
        self.next_check = time.monotonic() + 15
        if not allowed:
            self.report('disabled')

    def set_allowed(self, allowed):
        self.allowed = allowed
        self.enabled = self.available and allowed and not self.closed
        if not allowed:
            self.cancelled.set()
            self.report('disabled')
        elif self.enabled:
            self.report('idle')
            self.next_check = time.monotonic() + 15
        elif not self.closed:
            self.report(self.inactive_state)

    def report(self, state, value=''):
        with self.lock:
            self.state = {'state': state, 'version': value, 'current': self.current}

    def snapshot(self):
        with self.lock:
            return {**self.state, 'allowed': self.allowed}

    def poll(self):
        if self.enabled and time.monotonic() >= self.next_check:
            self.request()

    def request(self):
        if not self.enabled or self.closed or self.thread and self.thread.is_alive():
            return
        self.cancelled = threading.Event()
        cancelled = self.cancelled
        transport = self.transport or Transport(cancelled)
        def report(state, value=''):
            # A cancelled request cannot overwrite the user's disabled state.
            with self.lock:
                if not cancelled.is_set():
                    self.state = {'state': state, 'version': value, 'current': self.current}
        self.next_check = time.monotonic() + CHECK_INTERVAL
        self.report('checking')
        def work():
            try:
                check_and_stage(self.root, self.current, self.settings, transport, report)
            except urllib.error.HTTPError as exc:
                report('unavailable' if exc.code == 404 else 'network_error')
            except (OSError, urllib.error.URLError, TimeoutError):
                report('network_error')
            except (ValueError, KeyError, TypeError, zipfile.BadZipFile):
                report('verification_failed')
        self.thread = threading.Thread(target=work, daemon=True, name='release-check')
        self.thread.start()

    def close(self):
        self.closed = True
        self.enabled = False
        self.cancelled.set()
