"""Distribution preparation tests; no live process discovery or injection."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from bongo_chat.merge_install import validate_assets,compile_helper,prepare_session,HELPER

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def assets(tmp_path):
    folder=tmp_path/'assets';folder.mkdir()
    game=tmp_path/'game';game.mkdir()
    (game/'metadata').write_bytes(b'synthetic metadata')
    contract=dict(schema=2,files={'metadata':hashlib.sha256(b'synthetic metadata').hexdigest()})
    for name,key in [('Bridge.cs','source_sha256'),('MergePrepare.exe','prepare_sha256'),('Mono.Cecil.dll','cecil_sha256')]:
        content=('synthetic '+name).encode();(folder/name).write_bytes(content)
        contract[key]=hashlib.sha256(content).hexdigest()
    (folder/'contract.json').write_text(json.dumps(contract))
    return SimpleNamespace(root=game),folder,contract


def test_payload_and_game_metadata_are_verified_before_compilation(assets):
    game,folder,contract=assets
    assert validate_assets(game,folder)==(folder,contract)
    (folder/'Bridge.cs').write_text('changed')
    with pytest.raises(RuntimeError,match='bridge_binary_changed'):validate_assets(game,folder)


def test_wrong_game_build_is_refused(assets):
    game,folder,_=assets
    (game.root/'metadata').write_bytes(b'changed game')
    with pytest.raises(RuntimeError,match='unsupported_game_files'):validate_assets(game,folder)


def test_exact_hash_variants_preserve_other_file_checks(assets):
    game,folder,contract=assets
    original=contract['files']['metadata']
    alternate=hashlib.sha256(b'verified alternate').hexdigest()
    contract.update(schema=3)
    contract['files']['metadata']=[original,alternate]
    (game.root/'other').write_bytes(b'unchanged')
    contract['files']['other']=hashlib.sha256(b'unchanged').hexdigest()
    (folder/'contract.json').write_text(json.dumps(contract))
    validate_assets(game,folder)
    (game.root/'metadata').write_bytes(b'verified alternate')
    validate_assets(game,folder)
    (game.root/'other').write_bytes(b'unverified')
    with pytest.raises(RuntimeError,match='unsupported_game_files'):validate_assets(game,folder)
    (game.root/'other').write_bytes(b'unchanged')
    (game.root/'metadata').write_bytes(b'unverified third variant')
    with pytest.raises(RuntimeError,match='unsupported_game_files'):validate_assets(game,folder)


@pytest.mark.parametrize('digests',[[],None,{},[None],[''],['a'*63],['A'*64]])
def test_invalid_allowlist_fails_closed(assets,digests):
    game,folder,contract=assets
    contract.update(schema=3)
    contract['files']['metadata']=digests
    (folder/'contract.json').write_text(json.dumps(contract))
    with pytest.raises(RuntimeError,match='bridge_assets_missing'):validate_assets(game,folder)


def test_missing_or_unreadable_game_file_has_safe_actionable_error(assets,monkeypatch):
    game,folder,_=assets
    target=game.root/'metadata'
    target.unlink()
    with pytest.raises(RuntimeError,match='^merge_game_files_missing$'):validate_assets(game,folder)
    original=Path.read_bytes
    def denied(path):
        if path==target:raise PermissionError('private path must not reach UI')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',denied)
    with pytest.raises(RuntimeError,match='^merge_game_files_unreadable$'):validate_assets(game,folder)


def test_support_change_is_limited_to_two_pinned_autochest_files():
    contract=json.loads((ROOT/'tools/merge_bridge/local-contract.json').read_text())
    files=contract['files']
    variants={name:hashes for name,hashes in files.items() if isinstance(hashes,list)}
    assert len(files)==12
    assert variants=={'BongoCat_Data/Managed/BongoAutoChest.dll':[
        'ed3d3a7f8ae702605ec91a0029ce78c766c424d52f207b47fc4f2bbf4a0b754a',
        '8cc81f48322fd544b711291d67655a4f63cb0a88bf37b7e4c7f3f895e10f320e']}
    assert files['BongoCat_Data/Managed/Assembly-CSharp.dll']=='463a1758357f7ebcc291d0d96e33f6cc24b2e362a26f3762461d2760a81a23b4'


def test_compilation_uses_fixed_commands_and_stops_before_validation_on_failure(assets,tmp_path,monkeypatch):
    game,folder,_=assets
    system=tmp_path/'system';compiler=system/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    compiler.parent.mkdir(parents=True);compiler.write_bytes(b'never executed')
    monkeypatch.setenv('SystemRoot',str(system))
    calls=[]
    monkeypatch.setattr(subprocess,'run',lambda command,**kwargs:calls.append((command,kwargs)))
    session=tmp_path/'session';session.mkdir()
    assert compile_helper(game,folder,session)==session/HELPER
    assert len(calls)==2 and calls[0][0][0]==str(compiler) and calls[1][0][0]==str(folder/'MergePrepare.exe')
    assert calls[0][0][-1]==str(folder/'Bridge.cs') and all(c[1]['timeout']==30 for c in calls)
    calls.clear()
    def failure(command,**kwargs):calls.append(command);raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(subprocess,'run',failure)
    with pytest.raises(RuntimeError,match='merge_prepare_failed'):compile_helper(game,folder,session)
    assert len(calls)==1


def test_missing_windows_compiler_is_reported_without_execution(assets,tmp_path,monkeypatch):
    game,folder,_=assets;monkeypatch.setenv('SystemRoot',str(tmp_path/'missing'))
    with pytest.raises(RuntimeError,match='merge_compiler_missing'):compile_helper(game,folder,tmp_path)


def test_failed_preparation_can_be_retried_without_restarting_game(assets,tmp_path,monkeypatch):
    game,folder,_=assets
    session=tmp_path/'session';session.mkdir()
    def failure(*args):
        (session/HELPER).write_bytes(b'partial compilation')
        raise RuntimeError('merge_prepare_failed')
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',failure)
    with pytest.raises(RuntimeError,match='merge_prepare_failed'):prepare_session(game,folder,session)
    assert not session.exists()
    session.mkdir()
    def success(*args):
        (session/HELPER).write_bytes(b'synthetic complete helper')
        return session/HELPER
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',success)
    assert prepare_session(game,folder,session).read_bytes()==b'synthetic complete helper'


@pytest.mark.parametrize('evidence',['attach-attempt.json','session.json','ledger.json','unrelated.txt'])
def test_preparation_failure_preserves_attachment_evidence_and_unknown_files(assets,tmp_path,monkeypatch,evidence):
    game,folder,_=assets
    session=tmp_path/'session';session.mkdir()
    (session/evidence).write_bytes(b'preserve exactly')
    (session/HELPER).write_bytes(b'preserve helper')
    def failure(*args):raise RuntimeError('merge_prepare_failed')
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',failure)
    with pytest.raises(RuntimeError,match='merge_prepare_failed'):prepare_session(game,folder,session)
    assert (session/evidence).read_bytes()==b'preserve exactly'
    assert (session/HELPER).read_bytes()==b'preserve helper'


def test_changed_metadata_after_compilation_cleans_only_unattached_preparation(assets,tmp_path,monkeypatch):
    game,folder,_=assets
    session=tmp_path/'session';session.mkdir()
    def compile_changed(*args):
        (session/HELPER).write_bytes(b'synthetic helper')
        (game.root/'metadata').write_bytes(b'changed')
        return session/HELPER
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',compile_changed)
    with pytest.raises(RuntimeError,match='unsupported_game_files'):prepare_session(game,folder,session)
    assert not session.exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows C# runtime')
def test_csharp_bridge_consumes_synthetic_items_only():
    shell=shutil.which('pwsh')
    if not shell:pytest.skip('PowerShell 7 fixture runner')
    result=subprocess.run([shell,'-NoProfile','-File',str(ROOT/'tools/merge_bridge/test-bridge.ps1')],
        capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace')
    assert b'Interactive bridge fixture:' in result.stdout and b'synthetic exchanges=3' in result.stdout
