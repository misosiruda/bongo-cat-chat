"""No real process access; fail-closed metadata and process lifetime contracts."""
import pytest
from bongo_chat.memory import GameMemory, MemoryUnavailable, fields


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
