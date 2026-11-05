"""Read-only, bounded feature validation shared by chest and merge installation."""
import hashlib
import json
import os
import re
import subprocess

FEATURES = {'merge', 'chest', 'inventory'}
MANAGED = 'BongoCat_Data/Managed/'
LEGACY = MANAGED + 'BongoAutoChest.dll'
NATIVE = {'BongoCat.exe', 'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll',
          'BongoCat_Data/Plugins/x86_64/steam_api64.dll'}


def digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def require(condition):
    if not condition:
        raise ValueError


def checked_contract(contract):
    """No partial profiles, arbitrary paths, omitted features or permissive defaults."""
    try:
        spec, profiles = contract['probe'], contract['profiles']
        require(contract['schema'] == 6 and spec['schema'] == 2)
        require(set(spec['features']) == FEATURES)
        require(spec['assemblies'] == ['Assembly-CSharp.dll', 'System.Core.dll'])
        pins = spec['pinned_assemblies']
        require(isinstance(pins, list) and 1 <= len(pins) <= 32)
        require(len(set(pins)) == len(pins))
        require(spec['optional_pinned_assemblies'] == ['BongoAutoChest.dll'])
        require(not set(pins) & set(spec['assemblies'] + spec['optional_pinned_assemblies']))
        require(all(isinstance(n, str) and re.fullmatch(r'[A-Za-z0-9_.-]+\.dll', n) for n in pins))
        required = NATIVE | {MANAGED + n for n in pins} | {LEGACY}
        require(isinstance(profiles, list) and 1 <= len(profiles) <= 16)
        for profile in profiles:
            require(set(profile) == {'features', 'files'})
            require(set(profile['features']) == FEATURES and all(digest(v) for v in profile['features'].values()))
            require(set(profile['files']) == required)
            for name, values in profile['files'].items():
                require(isinstance(values, list) and 1 <= len(values) <= 16)
                require(all(digest(v) or (name == LEGACY and v is None) for v in values))
        return spec, profiles
    except (KeyError, TypeError, ValueError):
        raise RuntimeError('bridge_assets_missing') from None


def file_hashes(root, names):
    result = {}
    for name in sorted(names):
        try:
            # Bound each input, including malformed installations.
            with (root / name).open('rb') as stream:
                data = stream.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise RuntimeError('unsupported_game_files')
            result[name] = hashlib.sha256(data).hexdigest()
        except FileNotFoundError:
            if name != LEGACY:
                raise RuntimeError('merge_game_files_missing') from None
            result[name] = None
        except OSError:
            raise RuntimeError('merge_game_files_unreadable') from None
    return result


def validate_game_files(root, contract, assets=None):
    from .merge_install import asset_directory
    assets = assets or asset_directory()
    spec, profiles = checked_contract(contract)
    names = set(profiles[0]['files']) | {MANAGED + n for n in spec['assemblies']}
    before = file_hashes(root, names)
    candidates = [p for p in profiles if all(before[n] in values for n, values in p['files'].items())]
    if not candidates:
        raise RuntimeError('unsupported_game_files')
    try:
        if json.loads((assets / 'feature-spec.json').read_text(encoding='utf-8-sig')) != spec:
            raise RuntimeError('bridge_binary_changed')
        process = subprocess.run([str(assets / 'FeatureProbe.exe'), str(root / 'BongoCat_Data/Managed'),
                                  str(assets / 'feature-spec.json')], capture_output=True, timeout=20,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if process.returncode or len(process.stdout) > 16384:
            raise ValueError
        observed = json.loads(process.stdout)
        if not isinstance(observed, dict):
            raise ValueError
        modules, features = observed['modules'], observed['features']
        if not isinstance(modules, dict) or not isinstance(features, dict):
            raise ValueError
        expected_modules = {n[len(MANAGED):] for n, v in before.items() if n.startswith(MANAGED) and v is not None}
        if (set(observed) != {'modules', 'features'} or set(modules) != expected_modules
                or not all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', v)
                           for v in modules.values()) or set(features) != FEATURES
                or not all(digest(v) for v in features.values())):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise RuntimeError('automation_probe_failed') from None
    if before != file_hashes(root, names):
        raise RuntimeError('automation_files_changed')
    if not any(features == p['features'] for p in candidates):
        raise RuntimeError('unsupported_automation_features')
    # Hashes here bind one validated observation to compilation/attachment;
    # they are not a second support allowlist.
    return {'files': before, 'modules': modules, 'features': features}
