"""Compiled scanner checks use synthetic byte buffers, never game memory."""
import base64
import json
import os
from pathlib import Path
import random
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows scan helper')


@pytest.fixture(scope='module')
def matcher():
    def run(args, payload=None):
        return subprocess.run([str(value) for value in args], input=payload, capture_output=True,
                              timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    prepared = run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ROOT / 'tools/prepare-compatibility.ps1'])
    assert prepared.returncode == 0, prepared.stdout
    directory = ROOT / 'artifacts/compatibility'
    executable = directory / 'MemoryScanFixture.exe'
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    built = run([compiler, '/nologo', '/platform:x64', '/target:exe', f'/out:{executable}',
                 f'/reference:{directory / "MemoryScan.exe"}', '/reference:System.Web.Extensions.dll',
                 ROOT / 'tests/fixtures/MemoryScanFixture.cs'])
    assert built.returncode == 0, built.stdout
    def search(patterns, blocks, aligned=False):
        payload = dict(aligned=aligned, patterns={key: base64.b64encode(value).decode() for key, value in patterns.items()},
                       blocks=[dict(start=start, data=base64.b64encode(data).decode(), length=length)
                               for start, data, length in blocks])
        result = run([executable], json.dumps(payload).encode())
        return result.returncode, json.loads(result.stdout)
    return search


def reference(patterns, data, start, aligned):
    result = {}
    for key, pattern in patterns.items():
        positions = []
        pos = data.find(pattern)
        while pos >= 0:
            if not aligned or (start+pos) % 8 == 0:
                positions.append(start+pos)
            pos = data.find(pattern, pos+1)
        result[key] = positions
    return result


@pytest.mark.parametrize('count', [2, 92])
def test_native_pointer_aliases_alignment_and_short_reads(matcher, count):
    pattern = struct.pack('<Q', 0x1234567887654321)
    patterns = {'target': pattern, 'alias': pattern,
                **{str(i): struct.pack('<Q', 0x100000000+i*8) for i in range(count)}}
    data = b'.'*5 + pattern + b'x' + pattern + b'.'*7 + pattern
    # The first byte is deliberately not an aligned remote address.
    start = 0x10003
    code, result = matcher(patterns, [(start, data+b'ignored-tail'+pattern, len(data))], True)
    assert code == 0
    assert {key: sorted(value) for key, value in result.items()} == reference(patterns, data, start, True)


def test_native_string_scan_preserves_overlaps_aliases_and_chunk_boundary(matcher):
    boundary = 4*1024*1024
    data = b'.'*(boundary-4) + b'abcdefgh--abcdefgh--aaaaa'
    patterns = {'name': b'abcdefgh', 'alias': b'abcdefgh', 'overlap': b'aaa', 'missing': b'absent'}
    blocks = [(0x10000, data[:boundary+8], boundary+8),
              (0x10000+boundary, data[boundary:], len(data)-boundary)]
    code, result = matcher(patterns, blocks)
    assert code == 0
    assert {key: sorted(value) for key, value in result.items()} == reference(patterns, data, 0x10000, False)


def test_native_byte_search_matches_reference_for_dense_random_data(matcher):
    rng = random.Random(123)
    data = bytes(rng.randrange(8) for _ in range(8192))
    patterns = {str(i): data[i:i+length] for i, length in enumerate(range(2, 34))}
    code, result = matcher(patterns, [(0x10000, data, len(data))])
    assert code == 0
    assert {key: sorted(value) for key, value in result.items()} == reference(patterns, data, 0x10000, False)


@pytest.mark.parametrize('patterns,data,aligned,error', [
    ({'many': b'x'}, b'x'*4097, False, 'ambiguous_metadata'),
    ({'wrong': b'abc'}, b'abc', True, 'unsupported_pointer_pattern'),
    ({}, b'', False, 'unsupported_metadata_candidates'),
])
def test_native_scan_keeps_failure_limits(matcher, patterns, data, aligned, error):
    code, result = matcher(patterns, [(0x10000, data, len(data))], aligned)
    assert code == 2 and result == {'error': error}
