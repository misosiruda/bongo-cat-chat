"""Distribution preparation tests; no live process discovery or injection."""
import hashlib
import importlib.util
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
def assets(tmp_path, monkeypatch):
    folder=tmp_path/'assets';folder.mkdir()
    game=tmp_path/'game';game.mkdir()
    contract=json.loads((ROOT/'tools/merge_bridge/local-contract.json').read_text())
    profile=contract['profiles'][0]
    for name in set(profile['files']) | {'BongoCat_Data/Managed/Assembly-CSharp.dll','BongoCat_Data/Managed/System.Core.dll'}:
        path=game/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('synthetic '+name).encode())
        if name in profile['files']:profile['files'][name]=[hashlib.sha256(path.read_bytes()).hexdigest()]
    profile['files']['BongoCat_Data/Managed/BongoAutoChest.dll'].append(None)
    for name,key in [('Bridge.cs','source_sha256'),('MergePrepare.exe','prepare_sha256'),('Mono.Cecil.dll','cecil_sha256'),
                     ('FeatureProbe.exe','probe_sha256'),('feature-spec.json','spec_sha256')]:
        content=json.dumps(contract['probe']).encode() if name=='feature-spec.json' else ('synthetic '+name).encode()
        (folder/name).write_bytes(content);contract[key]=hashlib.sha256(content).hexdigest()
    (folder/'contract.json').write_text(json.dumps(contract))
    def probe(command, **kwargs):
        assert command[0]==str(folder/'FeatureProbe.exe') and kwargs['timeout']==20
        modules={p.name:'11111111-2222-3333-4444-555555555555' for p in (game/'BongoCat_Data/Managed').glob('*.dll')}
        return SimpleNamespace(returncode=0,stdout=json.dumps({'features':profile['features'],'modules':modules}).encode())
    monkeypatch.setattr(subprocess,'run',probe)
    return SimpleNamespace(root=game),folder,contract


@pytest.mark.parametrize('name',['Bridge.cs','MergePrepare.exe','Mono.Cecil.dll','FeatureProbe.exe','feature-spec.json'])
def test_payload_and_game_metadata_are_verified_before_compilation(assets,name):
    game,folder,contract=assets
    assert validate_assets(game,folder)==(folder,contract)
    (folder/name).write_text('changed')
    with pytest.raises(RuntimeError,match='bridge_binary_changed'):validate_assets(game,folder)


@pytest.mark.parametrize('name',['Assembly-CSharp.dll','System.Core.dll'])
def test_unrelated_binary_change_with_same_features_is_allowed(assets,name):
    game,folder,_=assets
    (game.root/'BongoCat_Data/Managed'/name).write_bytes(b'different metadata, same functional contract')
    validate_assets(game,folder)


def test_native_and_dependency_change_is_refused(assets):
    game,folder,_=assets
    (game.root/'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll').write_bytes(b'unknown native runtime')
    with pytest.raises(RuntimeError,match='unsupported_game_files'):validate_assets(game,folder)


def test_unknown_feature_is_rejected_before_opening_the_game(assets,monkeypatch):
    from bongo_chat import merge_install
    game,folder,_=assets
    probe=subprocess.run
    def changed(*args,**kwargs):
        value=probe(*args,**kwargs);result=json.loads(value.stdout);result['features']['chest']='0'*64
        value.stdout=json.dumps(result).encode();return value
    monkeypatch.setattr(subprocess,'run',changed)
    monkeypatch.setattr(merge_install,'running_game',lambda:game)
    monkeypatch.setattr(merge_install,'asset_directory',lambda:folder)
    def forbidden():pytest.fail('must not open or modify a game process')
    monkeypatch.setattr(merge_install,'kernel',forbidden)
    with pytest.raises(RuntimeError,match='unsupported_automation_features'):merge_install.connect()


@pytest.mark.parametrize('feature',['merge','chest','inventory'])
def test_changed_functional_contract_is_refused(assets,monkeypatch,feature):
    game,folder,_=assets
    probe=subprocess.run
    def changed(*args,**kwargs):
        value=probe(*args,**kwargs);result=json.loads(value.stdout);result['features'][feature]='0'*64
        value.stdout=json.dumps(result).encode();return value
    monkeypatch.setattr(subprocess,'run',changed)
    with pytest.raises(RuntimeError,match='unsupported_automation_features'):validate_assets(game,folder)


@pytest.mark.parametrize('change',['empty','missing_feature','no_pins','cross_profile','traversal','legacy_schema'])
def test_malformed_contract_fails_closed(assets,change):
    game,folder,contract=assets
    if change=='empty':contract['profiles']=[]
    if change=='missing_feature':contract['probe']['features'].pop('chest')
    if change=='no_pins':contract['probe']['pinned_assemblies']=[]
    if change=='cross_profile':contract['profiles'][0]['files'].pop('BongoCat.exe')
    if change=='traversal':contract['probe']['pinned_assemblies'][0]='../untrusted.dll'
    if change=='legacy_schema':contract['schema']=5
    (folder/'contract.json').write_text(json.dumps(contract))
    with pytest.raises(RuntimeError,match='bridge_assets_missing'):validate_assets(game,folder)


@pytest.mark.parametrize('change',['timeout','malformed','missing_module','unknown_feature','large'])
def test_probe_failure_never_approves_compatibility(assets,monkeypatch,change):
    game,folder,_=assets;probe=subprocess.run
    def failed(*args,**kwargs):
        if change=='timeout':raise subprocess.TimeoutExpired(args[0],20)
        value=probe(*args,**kwargs);result=json.loads(value.stdout)
        if change=='missing_module':result['modules'].pop('System.Core.dll')
        if change=='unknown_feature':result['features']['unknown']='0'*64
        value.stdout=b'{' if change=='malformed' else b'x'*16385 if change=='large' else json.dumps(result).encode()
        return value
    monkeypatch.setattr(subprocess,'run',failed)
    with pytest.raises(RuntimeError,match='automation_probe_failed'):validate_assets(game,folder)


def test_changed_file_during_probe_is_refused_even_with_same_features(assets,monkeypatch):
    game,folder,_=assets;probe=subprocess.run
    def changed(*args,**kwargs):
        value=probe(*args,**kwargs)
        (game.root/'BongoCat_Data/Managed/Assembly-CSharp.dll').write_bytes(b'changed while probing')
        return value
    monkeypatch.setattr(subprocess,'run',changed)
    with pytest.raises(RuntimeError,match='automation_files_changed'):validate_assets(game,folder)


def test_legacy_absence_is_allowed_but_unknown_legacy_is_refused(assets):
    game,folder,_=assets;legacy=game.root/'BongoCat_Data/Managed/BongoAutoChest.dll'
    legacy.unlink();validate_assets(game,folder)
    legacy.write_bytes(b'unknown helper')
    with pytest.raises(RuntimeError,match='unsupported_game_files'):validate_assets(game,folder)


def test_missing_game_file_has_safe_actionable_error(assets):
    game,folder,_=assets
    (game.root/'BongoCat_Data/Managed/Assembly-CSharp.dll').unlink()
    with pytest.raises(RuntimeError,match='merge_game_files_missing'):validate_assets(game,folder)


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
        (game.root/'BongoCat_Data/Managed/Assembly-CSharp.dll').write_bytes(b'changed')
        return session/HELPER
    monkeypatch.setattr('bongo_chat.merge_install.compile_helper',compile_changed)
    with pytest.raises(RuntimeError,match='automation_files_changed'):prepare_session(game,folder,session)
    assert not session.exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows C# runtime')
def test_csharp_bridge_consumes_synthetic_items_only():
    shell=shutil.which('pwsh')
    if not shell:pytest.skip('PowerShell 7 fixture runner')
    result=subprocess.run([shell,'-NoProfile','-File',str(ROOT/'tools/merge_bridge/test-bridge.ps1')],
        capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace')
    assert b'Interactive bridge fixture:' in result.stdout and b'synthetic exchanges=3' in result.stdout
    assert b'Chest fixture:' in result.stdout and b'synthetic requests only.' in result.stdout
