"""Local, allowlisted report preview and a fixed GitHub issue draft URL."""
import json
import re
import sys
from urllib.parse import urlencode
from uuid import uuid4

from . import __version__
from .diagnostics import clean_details, connection_error

ISSUES = 'https://github.com/misosiruda/bongo-cat-chat/issues/new'
AREAS = frozenset({'app', 'chest', 'merge'})
STATES = frozenset({'disconnected', 'connecting', 'connected', 'error'})
NOTICES = frozenset({'offline', 'checking', 'ready', 'read_only', 'worker_stopped',
    'unsupported_game_build', 'game_missing_or_ambiguous', 'process_access_failed',
    'steam_unavailable', 'no_lobby', 'searching_lobby', 'connection_changed', 'view_unavailable',
    'discovering', 'discovery_failed', 'game_files_changed', 'compatibility_tool_missing', 'compatibility_timeout'})


def environment():
    # Deliberately exclude platform.platform(), host/user names, paths and env vars.
    value = {'os': 'windows' if sys.platform == 'win32' else 'other',
             'python': '.'.join(map(str, sys.version_info[:3])),
             'architecture': '64-bit' if sys.maxsize > 2**32 else '32-bit',
             'packaged': bool(getattr(sys, 'frozen', False))}
    if sys.platform == 'win32':
        version = sys.getwindowsversion()
        value['windows'] = f'{version.major}.{version.minor}.{version.build}'
    return value


def collect(area, chat, connection, *, storage_error=False):
    if not isinstance(area, str) or area not in AREAS:
        raise ValueError('invalid_report_area')
    result = {'schema': 1, 'app_version': __version__, 'area': area, 'environment': environment(),
              'storage_error': storage_error is True}
    chat = chat if isinstance(chat, dict) else {}
    notice = chat.get('notice')
    result['chat'] = {'connected': chat.get('connected') is True,
                      'notice': notice if isinstance(notice, str) and notice in NOTICES else 'unknown'}
    build = chat.get('game_build')
    if isinstance(build, str) and re.fullmatch(r'[0-9]{1,12}', build):
        result['chat']['game_build'] = build
    if not isinstance(connection, dict):
        result['automation'] = {'state': 'unavailable', 'attempts': []}
        return result
    state = connection.get('state')
    summary = {'state': state if isinstance(state, str) and state in STATES else 'unknown', 'attempts': []}
    if connection.get('error'):
        summary['error'] = connection_error(connection['error'])
    attempts = connection.get('attempts')
    if isinstance(attempts, list):
        for item in attempts[-3:]:
            if isinstance(item, dict):
                summary['attempts'].append(dict(clean_details(item), error=connection_error(item.get('error'))))
    result['automation'] = summary
    return result


class ReportPreview:
    """Only the exact reviewed report can be opened/copied. No renderer-supplied URL."""
    def __init__(self):
        self.current = None

    def prepare(self, area, chat, connection, language='ko', *, storage_error=False):
        details = collect(area, chat, connection, storage_error=storage_error)
        title = f'Bug report: {area} ({__version__})'
        if language == 'en':
            intro = ('## What happened?\nPlease describe the problem and what you expected.\n\n'
                     '## Diagnostics\nCollected by the app; no chat, account/lobby IDs, paths or connection tokens.\n')
        else:
            intro = ('## 어떤 문제가 있었나요?\n문제가 생긴 상황과 기대한 동작을 적어 주세요.\n\n'
                     '## 자동 수집한 진단\n대화·계정/로비 ID·파일 경로·연결 토큰은 포함하지 않아요.\n')
        body = intro + '\n```json\n' + json.dumps(details, ensure_ascii=True, indent=2) + '\n```\n'
        url = ISSUES + '?' + urlencode({'title': title, 'body': body})
        # GitHub rejects oversized query URLs. This also bounds clipboard output.
        if len(url) > 7500:
            raise ValueError('report_too_large')
        self.current = {'id': uuid4().hex, 'title': title, 'body': body, 'url': url}
        return {key: self.current[key] for key in ('id', 'title', 'body')}

    def get(self, report_id):
        if not self.current or not isinstance(report_id, str) or report_id != self.current['id']:
            raise ValueError('report_expired')
        return dict(self.current)

    def clear(self):
        self.current = None
