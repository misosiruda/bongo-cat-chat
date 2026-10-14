"""No real process access; fail-closed metadata and process lifetime contracts."""
import pytest
from bongo_chat.memory import GameMemory, MemoryUnavailable, Reader, fields


class FakeGame:
    def alive(self):return False


class DeadReader:
    game=FakeGame()
    def read(self,*args):raise AssertionError("must not read old addresses after restart")


def test_process_death_precedes_any_cached_address_read():
    memory=GameMemory.__new__(GameMemory);memory.reader=DeadReader();memory.roots={'cache':(1,2,3)}
    with pytest.raises(MemoryUnavailable,match='process_changed'):
        memory.root('cache')


def test_memory_read_failure_cannot_be_empty_hidden_list():
    memory=GameMemory.__new__(GameMemory);memory.reader=DeadReader();memory.roots={}
    with pytest.raises(MemoryUnavailable):memory.hidden()


def test_declared_generic_field_count_excludes_adjacent_memory():
    class Metadata:
        def read(self,addr,size):return {10000+0x1b:b'\x03',20000+0x1b:b'\x02'}.get(addr,b'')
        def pointer(self,addr):
            values={10000+0xf0:30000,30000:20000,10000+0x98:40000}
            for i in range(4):values.update({40000+32*i+16:10000,40000+32*i+8:1000+i})
            # Adjacent memory deliberately also contains a matching owner.
            values.update({40000+32*4+16:10000,40000+32*4+8:9999})
            return values.get(addr,0)
        def i32(self,addr):return {20000+0x100:4,**{40000+32*i+24:16+8*i for i in range(4)}}.get(addr)
        def cstring(self,addr):
            assert addr!=9999,'field decoder walked beyond the declared table'
            return ['hashCode','next','key','value'][addr-1000]
    assert len(fields(Metadata(),10000))==4


@pytest.mark.parametrize('flag,expected', [(b'\x00', False), (b'\x01', True), (b'\x02', None)])
def test_hidden_cache_decodes_boolean_and_rejects_invalid_values(monkeypatch, flag, expected):
    from bongo_chat import memory as module
    # Synthetic account-shaped key, never copied from a Steam account.
    uid = '10000000000000000'
    pointers = {100: 1000, 1000: 2000, 2000: 3000, 1008: 4000,
                4000: 5000, 5000: 6000, 6000: 7000, 4024: 1,
                4040: 8000, 4048: 9000, 8000: 10000, 10000: 11000,
                9000: 12000, 12000: 13000}
    integers = {1016: 1, 1020: 3, 7000+0x1c: 40, 4032: 0, 8016: 17}
    class Data:
        def pointer(self, address): return pointers[address]
        def i32(self, address): return integers[address]
        def exact(self, address, size): return {8020: uid.encode('utf-16-le'), 9016: flag}[address]
    monkeypatch.setattr(module, 'class_name', lambda reader, cls: {3000: 'Dictionary`2', 6000: 'Entry[]',
                        7000: 'Entry', 11000: 'String', 13000: 'PlayerData'}[cls])
    monkeypatch.setattr(module, 'fields', lambda reader, cls: {
        3000: {'_entries': 8, '_count': 16, '_version': 20},
        7000: {'hashCode': 16, 'next': 20, 'key': 24, 'value': 32}, 13000: {'IsHidden': 16}}[cls])
    memory = GameMemory.__new__(GameMemory)
    memory.reader, memory.root = Data(), lambda key: 100
    if expected is None:
        with pytest.raises(MemoryUnavailable, match='hidden_boolean'):
            memory.hidden()
    else:
        assert memory.hidden() == {uid: expected}


def test_background_discovery_cancel_closes_unpublished_reader(monkeypatch):
    import threading
    from bongo_chat import memory as module
    started, release = threading.Event(), threading.Event()
    closed = []
    class Memory:
        def __init__(self, game, stop):
            self.stop = stop
        def discover(self):
            started.set()
            assert release.wait(3)
        def close(self):
            closed.append(True)
    monkeypatch.setattr(module, 'GameMemory', Memory)
    discovery = module.MemoryDiscovery(object(), threading.Event())
    try:
        assert started.wait(2)
        discovery.close()
        release.set()
        assert discovery.done.wait(2)
        assert discovery.memory is None and closed == [True]
    finally:
        release.set()
        discovery.close()


def test_background_discovery_hands_off_and_closes_reader_once(monkeypatch):
    import threading
    from bongo_chat import memory as module
    closed = []
    class Memory:
        def __init__(self, game, stop):pass
        def discover(self):pass
        def close(self):closed.append(True)
    monkeypatch.setattr(module, 'GameMemory', Memory)
    discovery = module.MemoryDiscovery(object(), threading.Event())
    assert discovery.done.wait(2)
    assert isinstance(discovery.memory, Memory) and not discovery.failed
    discovery.close()
    discovery.close()
    assert closed == [True]


@pytest.fixture
def native_reader(tmp_path, monkeypatch):
    import json
    import threading
    from types import SimpleNamespace
    from bongo_chat import memory as module
    class Process:
        returncode = 0
        output = json.dumps({'metadata': [0x10000]}).encode()
        killed = False
        inputs = []
        def communicate(self, input=None, timeout=None):
            if input is not None:
                self.inputs.append(json.loads(input))
            return self.output, None
        def poll(self):return self.returncode
        def kill(self):self.killed = True; self.returncode = -9
    process = Process()
    helper = tmp_path / 'synthetic-tool.exe'
    helper.touch()
    reader = Reader.__new__(Reader)
    reader.scan_helper = helper
    reader.game = SimpleNamespace(pid=123, alive=lambda: True)
    reader.stop = threading.Event()
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: process)
    return reader, process


@pytest.mark.parametrize('result', [b'not json', b'[]', b'{"other":[]}', b'{"metadata":[true]}',
                                  b'{"metadata":[0]}', b'{"metadata":[65537]}', b'{"metadata":["65536"]}'])
def test_native_result_validation_rejects_bad_or_unaligned_addresses(native_reader, result):
    reader, process = native_reader
    process.output = result
    with pytest.raises(MemoryUnavailable, match='memory_scan_failed'):
        reader.scan({'metadata': b'abcdefgh'}, pointer_aligned=True)


def test_native_scan_contract_and_process_lifetime(native_reader):
    reader, process = native_reader
    assert reader.scan({'metadata': b'abcdefgh'}, pointer_aligned=True) == {'metadata': {0x10000}}
    assert process.inputs[-1] == dict(pid=123, private_only=True, pointer_aligned=True,
                                      patterns={'metadata': 'YWJjZGVmZ2g='})
    calls = iter([True, False])
    reader.game.alive = lambda: next(calls)
    with pytest.raises(MemoryUnavailable, match='process_changed'):
        reader.scan({'metadata': b'abcdefgh'})


def test_native_scan_cancellation_kills_only_owned_helper(native_reader):
    import subprocess
    reader, process = native_reader
    process.returncode = None
    def communicate(input=None, timeout=None):
        if process.killed:
            return b'', None
        reader.stop.set()
        raise subprocess.TimeoutExpired('synthetic-tool', 0.1)
    process.communicate = communicate
    with pytest.raises(MemoryUnavailable, match='discovery_cancelled_or_budget'):
        reader.scan({'metadata': b'abcdefgh'})
    assert process.killed


def test_missing_scanner_fails_closed(native_reader):
    reader, _ = native_reader
    reader.scan_helper.unlink()
    with pytest.raises(MemoryUnavailable, match='memory_scan_tool_missing'):
        reader.scan({'metadata': b'abcdefgh'})
