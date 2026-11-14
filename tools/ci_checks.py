"""Dependency-free CI selection and local documentation checks.

Only an explicit documentation allowlist can skip Windows packaging. Unknown
paths and unavailable comparison commits require the Windows job.
"""
from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

PACKAGED_DOCS = {
    'docs/privacy-policy.md', 'docs/privacy-policy.en.md',
    'docs/licensing/SOURCES.md',
}
ROOT_DOCS = {'README.md', 'README.en.md', 'AGENTS.md', 'CONTRIBUTING.md', 'CHANGELOG.md'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}


def documentation_only(path: str) -> bool:
    if path in PACKAGED_DOCS:
        return False
    return (path in ROOT_DOCS or
            path.startswith('docs/') and PurePosixPath(path).suffix.lower() in {'.md', *IMAGE_SUFFIXES})


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def valid_revision(revision: str) -> bool:
    return bool(re.fullmatch(r'[0-9a-f]{40}', revision)) and set(revision) != {'0'}


def make_plan(root: Path, event_name: str, event: dict) -> dict:
    plan = {'windows': True, 'base': None, 'head': 'HEAD', 'changed': [],
            'reason': 'Manual or unknown event: run the full Windows checks.'}
    try:
        if event_name == 'pull_request':
            pr = event['pull_request']
            head = pr['head']['sha']
            if not all(valid_revision(value) for value in (pr['base']['sha'], head)):
                raise ValueError('Missing comparison revision')
            base = git(root, 'merge-base', pr['base']['sha'], head).decode().strip()
        elif event_name == 'push':
            base, head = event['before'], event['after']
        else:
            return plan
        for revision in (base, head):
            if not valid_revision(revision):
                raise ValueError('Missing comparison revision')
            git(root, 'cat-file', '-e', revision + '^{commit}')
        # No rename detection: both the removed and added path must be classified.
        changed = git(root, 'diff', '--name-only', '-z', '--no-renames', base, head).decode().split('\0')
        changed = [path for path in changed if path]
        windows = not changed or any(not documentation_only(path) for path in changed)
        plan.update(base=base, head=head, changed=changed, windows=windows,
                    reason=('Application/build inputs or an empty diff: run Windows checks.' if windows else
                            'Documentation-only change: skip Windows checks.'))
    except (KeyError, ValueError, subprocess.CalledProcessError) as error:
        plan['reason'] = f'Comparison unavailable ({type(error).__name__}): run Windows checks.'
    return plan


def prose(text: str) -> str:
    """Ignore examples in fenced/inline code and HTML comments."""
    lines, fence = [], None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    text = re.sub(r'<!--.*?-->', '', '\n'.join(lines), flags=re.S)
    return re.sub(r'(`+).*?\1', '', text)


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value and (tag, name) in {('a', 'href'), ('img', 'src'), ('source', 'src')}:
                self.links.append(value)


def local_links(text: str) -> list[str]:
    text = prose(text)
    parser = HTMLLinks()
    parser.feed(text)
    # Inline links/images and reference definitions; one nested parenthesis is
    # supported in bare destinations. Angle-bracket destinations allow spaces.
    destination = r'<([^>\n]+)>|((?:[^\s()]+|\([^()]*\))+)'  # optional titles are not URLs
    links = parser.links
    for pattern in (r'\]\(\s*(?:' + destination + ')',
                    r'^\s{0,3}\[[^]\n]+\]:\s*(?:' + destination + ')'):
        links.extend(match[1] or match[2] for match in re.finditer(pattern, text, re.M))
    return links


def link_target(source: str, url: str) -> str | None:
    url = html.unescape(url)
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    path = unquote(parsed.path)
    # Resolve as repository paths rather than machine-specific paths.
    parts = [] if path.startswith('/') else list(PurePosixPath(source).parent.parts)
    for part in path.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                raise ValueError(f'Link escapes the repository: {url}')
            parts.pop()
        else:
            parts.append(part)
    return '/'.join(parts)


def check_docs(root: Path, plan: dict) -> list[str]:
    tracked = {path for path in git(root, 'ls-files', '-z').decode().split('\0') if path}
    # Include newly created local files when explicitly checking an uncommitted plan.
    tracked.update(path for path in plan['changed'] if (root / path).is_file())
    documents = sorted(path for path in tracked if PurePosixPath(path).suffix.lower() == '.md' and
                       (path in ROOT_DOCS or path.startswith('docs/')))
    changed = set(plan['changed'])
    errors = []
    for source in documents:
        try:
            text = (root / source).read_text(encoding='utf-8')
        except (OSError, UnicodeError) as error:
            errors.append(f'{source}: {error}')
            continue
        if re.search(r'^(?:<{7}|={7}|>{7})(?: |$)', text, re.M):
            errors.append(f'{source}: unresolved merge conflict marker')
        for url in local_links(text):
            try:
                target = link_target(source, url)
            except ValueError as error:
                errors.append(f'{source}: {error}')
                continue
            if target is None:
                continue
            # Validate changed documents, and inbound references to changed or
            # deleted assets/docs. Historical unrelated local references are not
            # required to exist on a fresh checkout.
            relevant = plan['base'] is None or source in changed or target in changed
            if relevant and not (target in tracked or any(p.startswith(target + '/') for p in tracked)):
                errors.append(f'{source}: missing local target {url}')
    for path in sorted(changed):
        if path.startswith('docs/') and PurePosixPath(path).suffix.lower() == '.svg' and (root / path).is_file():
            try:
                ET.parse(root / path)
            except ET.ParseError as error:
                errors.append(f'{path}: invalid SVG XML: {error}')
    print(f'Checked {len(documents)} Markdown documents; validated local references affected by the change.')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('plan').add_argument('--output', type=Path, required=True)
    sub.add_parser('docs').add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == 'plan':
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
        plan = make_plan(root, os.environ['GITHUB_EVENT_NAME'], event)
        args.output.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
        if output := os.environ.get('GITHUB_OUTPUT'):
            with open(output, 'a', encoding='utf-8') as stream:
                stream.write(f"windows={str(plan['windows']).lower()}\n")
        print(json.dumps(plan, indent=2))
        if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(summary, 'a', encoding='utf-8') as stream:
                stream.write(f"### CI scope\n\n{plan['reason']}\n\nChanged paths: {len(plan['changed'])}.\n")
        return 0
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    errors = check_docs(root, plan)
    for error in errors:
        print(error, file=sys.stderr)
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
