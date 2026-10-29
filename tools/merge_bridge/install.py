"""One-shot opt-in developer installation; no game restart or file patching.

A marker is written before attaching. Never automatically retry or create another
session for the same game lifetime, including after an uncertain attach outcome.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import uuid

import pefile
from bootstrap import EXPORTS, ERROR_EXPORT, execute, kernel, start_ticks

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from bongo_chat.environment import running_game
from bongo_chat.memory import Reader, MonoCatalog, fields


def check_existing_bridges(reader):
    catalog = MonoCatalog(reader)
    catalog.images()  # Validates the pinned native layout/accessor signatures.
    node, seen = reader.pointer(catalog.base + 0x740f90), set()
    while node:
        if node in seen or len(seen) >= 512: raise RuntimeError('assembly_list_invalid')
        seen.add(node)
        assembly = reader.pointer(node)
        image = reader.pointer(assembly + 0x60)
        name = reader.cstring(reader.pointer(image + 0x30)) or ''
        if name.startswith('BongoCatChat.MergeBridge'):
            cls = catalog.klass(image, 'Bridge', 'BongoCatChat.MergeBridge')
            offsets = fields(reader, cls)
            tables = catalog.vtables(cls)
            if not tables: raise RuntimeError('prior_bridge_state_unknown')
            for vt in tables:
                if not reader.exact(vt + 0x30, 1)[0] & 4: raise RuntimeError('prior_bridge_state_unknown')
                data = reader.pointer(vt + reader.i32(cls + 0x5c) * 8 + 0x48)
                if (reader.exact(data + offsets['installed'], 1) != b'\0'
                        or reader.i32(data + offsets['spent']) != 0):
                    raise RuntimeError('existing_bridge_do_not_reattach')
        node = reader.pointer(node + 8)


def install(budget):
    if budget not in (0, 1, 2): raise ValueError('invalid_test_budget')
    game = running_game()
    contract = json.loads(Path(__file__).with_name('local-contract.json').read_text())
    for name, digest in contract['files'].items():
        if hashlib.sha256((game.root / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('unsupported_game_file:' + name)
    k = kernel()
    handle = k.OpenProcess(0x043a, False, game.pid)
    if not handle: raise RuntimeError('process_access_failed')
    try:
        ticks = start_ticks(k, handle)
        reader = Reader(game)
        native = 'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll'
        try:
            check_existing_bridges(reader)
            base = reader.module(native)
            pe = pefile.PE(str(game.root / native))
            if pe.FILE_HEADER.Machine != 0x8664: raise RuntimeError('not_x64')
            exports = {}
            for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                name = (symbol.name or b'').decode('ascii')
                if name not in (*EXPORTS, ERROR_EXPORT): continue
                if symbol.forwarder or reader.exact(base + symbol.address, 24) != pe.get_data(symbol.address, 24):
                    raise RuntimeError('loaded_export_changed')
                exports[name] = base + symbol.address
            pe.close()
            if set(exports) != set((*EXPORTS, ERROR_EXPORT)): raise RuntimeError('mono_exports_missing')
        finally: reader.close()
        dll = ROOT / 'artifacts/merge-bridge/BongoCatChat.MergeBridge.Shared.dll'
        if not dll.is_file(): raise RuntimeError('build_bridge_first')
        # MSIX-hosted development shells may virtualize AppData away from the
        # standalone game. Use this explicit, ignored shared development folder.
        parent = ROOT / 'research/private/merge-bridge-session'
        parent.mkdir(parents=True, exist_ok=True)
        session = parent / f'{game.pid}-{ticks}'
        subprocess.run(['pwsh.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(Path(__file__).with_name('create-session.ps1')), '-Path', str(session)],
                       check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        config = dict(protocol=1, pid=game.pid, process_start_ticks=ticks, epoch=uuid.uuid4().hex,
                      token=secrets.token_hex(32), test_budget=budget,
                      helper_sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
        (session / 'session.json').write_text(json.dumps(config), encoding='utf-8')
        shutil.copyfile(dll, session / dll.name)
        if not game.alive() or start_ticks(k, handle) != ticks: raise RuntimeError('process_changed')
        (session / 'attach-attempt.json').write_text(json.dumps(dict(attempted_at=time.time())), encoding='utf-8')
        result = execute(handle, exports, session / dll.name)
        # Do not print or persist a live exception address.
        public = dict(status=result['status'], stage=result['stage'], managed_exception=bool(result['exception']), load_error=result['load_error'], load_message=result['load_message'])
        (session / 'attach-result.json').write_text(json.dumps(public), encoding='utf-8')
        print(json.dumps(dict(session=str(session), **public)))
        if result['status'] != 1: raise RuntimeError('attach_not_confirmed_no_retry')
    finally: k.CloseHandle(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', action='store_true', required=True)
    parser.add_argument('--test-budget', type=int, choices=(0, 1, 2), required=True)
    args = parser.parse_args()
    install(args.test_budget)
