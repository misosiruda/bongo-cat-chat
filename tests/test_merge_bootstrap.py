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
