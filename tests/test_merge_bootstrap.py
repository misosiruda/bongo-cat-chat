import json
from pathlib import Path
import subprocess
import sys

import pytest

WORKER = Path(__file__).resolve().parents[1] / 'tools/merge_bridge/bootstrap_fixture.py'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows x64 ABI')
@pytest.mark.parametrize('mode', ['success', 'exception', '0', '1', '2', '3', '4', '5'])
def test_bootstrap_in_disposable_process(mode):
    run = subprocess.run([sys.executable, str(WORKER), mode], capture_output=True,
                         text=True, timeout=15, check=True)
    value = json.loads(run.stdout)
    assert value['errors'] == []
    if mode in {'success', 'exception'}:
        assert value['calls'] == list(range(8))
        assert value['result']['status'] == (1 if mode == 'success' else 2)
        assert value['result']['exception'] == (0 if mode == 'success' else 999)
    else:
        failed = int(mode)
        assert value['calls'] == list(range(failed + 1)) + ([7] if failed >= 2 else [])
        assert value['result']['status'] == 0
        assert value['result']['stage'] == failed + 1
        assert value['result']['load_message'] == ('fixture_load_error' if failed == 2 else '')
    if mode != 'exception':
        assert value['diagnostic_calls'] == []


@pytest.mark.parametrize('mode', ['exception', 'nested', 'unknown', 'cyclic', 'missing_fields', 'long', 'null_handle', 'null_class'])
def test_exception_diagnostics_are_bounded_and_do_not_execute_managed_getters(mode):
    run = subprocess.run([sys.executable, str(WORKER), mode], capture_output=True, text=True, timeout=15, check=True)
    value = json.loads(run.stdout)
    result = value['result']
    assert result['status'] == 2 and result['stage'] == 7
    assert value['calls'] == list(range(8))  # Exactly one Install invocation, then detach.
    assert value['diagnostic_calls'][0] == 'pin'
    if mode != 'null_handle': assert value['diagnostic_calls'][1] == 'exception_base'
    for secret in ('private-user-path', 'PrivateUserClass', 'secret-token', 'bridge_init_5'):
        assert secret not in run.stdout
    if mode in {'exception', 'nested', 'cyclic'}:
        assert result['initialization_step'] == 'bind_game_fields'
    else:
        assert 'initialization_step' not in result
    if mode == 'nested':
        assert result['managed_exception_types'] == ['System.InvalidOperationException',
            'System.TypeInitializationException', 'System.MissingMethodException']
    if mode == 'unknown': assert result['managed_exception_types'] == ['other']
    if mode == 'cyclic': assert len(result['managed_exception_types']) == 3
    if mode in {'null_handle', 'null_class'}: assert 'managed_exception_types' not in result
