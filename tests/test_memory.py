"""No real process access; fail-closed metadata and process lifetime contracts."""
import pytest
import ctypes as C
from bongo_chat.memory import GameMemory, MemoryUnavailable, Reader, Region, fields


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


def scanner(payload):
    class Game:
        def alive(self): return True
    class Kernel:
        def VirtualQueryEx(self, handle, address, target, size):
            if address: return 0
            region = C.cast(target, C.POINTER(Region)).contents
            region.BaseAddress = 0x10000
            region.RegionSize = len(payload)
            region.State, region.Type, region.Protect = 0x1000, 0x20000, 4
            return size
    reader = Reader.__new__(Reader)
    reader.game, reader.stop, reader.k, reader.handle = Game(), None, Kernel(), 1
    reader.read = lambda address, size: payload[address-0x10000:address-0x10000+size]
    return reader


def test_pointer_scan_handles_many_patterns_aliases_and_chunk_overlap():
    boundary = 4 * 1024 * 1024
    payload = b'.' * (boundary-4) + b'abcdefgh' + b'--abcdefgh--'
    patterns = {'a': b'abcdefgh', 'alias': b'abcdefgh', 'overlap': b'cdef',
                'missing1': b'not here', 'missing2': b'absent', 'tail': b'gh--'}
    result = scanner(payload).scan(patterns)
    assert result['a'] == result['alias'] == {0x10000+boundary-4, 0x10000+boundary+6}
    assert result['overlap'] == {p+2 for p in result['a']}
    assert not result['missing1'] and not result['missing2']
    assert len(result['tail']) == 2


def test_pointer_scan_keeps_ambiguity_and_cancel_limits():
    with pytest.raises(MemoryUnavailable, match='ambiguous_metadata'):
        scanner(b'x' * 4097).scan({'repeated': b'x'})
    reader = scanner(b'fixture')
    class Stop:
        def is_set(self): return True
    reader.stop = Stop()
    with pytest.raises(MemoryUnavailable, match='discovery_cancelled_or_budget'):
        reader.scan({'metadata': b'fixture'})


def test_aligned_pointer_scan_ignores_unaligned_decoys_and_keeps_aliases():
    import struct
    pointer = struct.pack('<Q', 0x1234567887654321)
    payload = pointer + b'X' + pointer + b'.' * 7 + pointer
    patterns = {'pointer': pointer, 'same': pointer, **{str(i): struct.pack('<Q', i) for i in range(80)}}
    result = scanner(payload).scan(patterns, pointer_aligned=True)
    assert result['pointer'] == result['same'] == {0x10000, 0x10000+24}
    assert sum(len(hits) for hits in result.values()) == 4
    with pytest.raises(MemoryUnavailable, match='unsupported_pointer_pattern'):
        scanner(payload).scan({'invalid': b'abc'}, pointer_aligned=True)


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
