"""Synthetic Mono catalog reads: no game, addresses or external calls."""
import struct
import threading
from types import SimpleNamespace

import pytest

from bongo_chat import memory as module
from bongo_chat.memory import GameMemory, MemoryUnavailable, MonoCatalog, Reader


class CatalogReader(Reader):
    def __init__(self):
        self.data = {}
        self.stop = threading.Event()
        self.game = SimpleNamespace(alive=lambda: True)

    def put(self, address, data):
        self.data.update({address + index: value for index, value in enumerate(data)})

    def pointer_at(self, address, value):
        self.put(address, struct.pack('<Q', value))

    def read(self, address, size):
        return bytes(self.data.get(address + index, 0) for index in range(size))

    def module(self, relative):
        return 0x100000


@pytest.fixture
def catalog():
    r = CatalogReader()
    c = MonoCatalog(r)
    c.base = 0x100000
    # One hash bucket containing two classes, only one with the required name.
    image, first, target = 0x20000, 0x30000, 0x31000
    r.put(image + 0x4d0, struct.pack('<QQQiiQ', 0, 0, c.base + 0x147340, 1, 2, 0x22000))
    r.pointer_at(0x22000, first)
    for cls, label, string, next_cls in [(first, b'Unrelated\0', 0x40000, target),
                                        (target, b'PlayerDataCache\0', 0x40100, 0)]:
        r.pointer_at(cls + 0x40, image)
        r.pointer_at(cls + 0x48, string)
        r.pointer_at(cls + 0x50, 0x40200)
        r.pointer_at(cls + 0x108, next_cls)
        r.put(string, label)
    r.put(0x40200, b'\0')
    r.pointer_at(target + 0xd0, 0x50000)
    r.put(0x50000, struct.pack('<H', 1))
    r.put(0x50008, struct.pack('<QQ', 0, 0x51000))
    r.pointer_at(0x51000, target)
    r.pointer_at(0x51010, 0x52000)
    r.put(0x52094, struct.pack('<i', 1))
    return c


def test_catalog_finds_class_and_vtable_without_scanning(catalog):
    cls = catalog.klass(0x20000, 'PlayerDataCache', '')
    assert cls == 0x31000
    assert catalog.vtables(cls) == {0x51000}


@pytest.mark.parametrize('change,error', [
    ('cycle', 'class_catalog_invalid'),
    ('duplicate_name', 'metadata_not_unique'),
    ('foreign_image', 'class_image_mismatch'),
    ('oversized_table', 'class_catalog_invalid'),
    ('wrong_accessor', 'class_catalog_invalid'),
    ('missing_name', 'metadata_not_unique'),
])
def test_catalog_rejects_ambiguous_or_invalid_metadata(catalog, change, error):
    r = catalog.r
    if change == 'cycle':r.pointer_at(0x31108, 0x30000)
    elif change == 'duplicate_name':r.put(0x40000, b'PlayerDataCache\0')
    elif change == 'foreign_image':r.pointer_at(0x31040, 0x90000)
    elif change == 'oversized_table':r.put(0x204e8, struct.pack('<i', 20000))
    elif change == 'wrong_accessor':r.pointer_at(0x204e0, 0x99999)
    elif change == 'missing_name':r.put(0x40100, b'Missing\0')
    with pytest.raises(MemoryUnavailable, match=error):
        catalog.klass(0x20000, 'PlayerDataCache', '')


def test_catalog_detects_table_change_during_traversal(catalog):
    original = catalog.r.cstring
    def change(address):
        catalog.r.put(0x204ec, struct.pack('<i', 3))
        return original(address)
    catalog.r.cstring = change
    with pytest.raises(MemoryUnavailable, match='class_catalog_changed'):
        catalog.klass(0x20000, 'PlayerDataCache', '')


@pytest.mark.parametrize('change', ['wrong_class', 'wrong_domain', 'duplicate_vtable', 'too_many_domains', 'changed_array'])
def test_catalog_rejects_wrong_or_changing_vtable(catalog, change):
    r = catalog.r
    if change == 'wrong_class':r.pointer_at(0x51000, 0x30000)
    elif change == 'wrong_domain':r.put(0x52094, struct.pack('<i', 0))
    elif change == 'duplicate_vtable':r.pointer_at(0x50008, 0x51000)
    elif change == 'too_many_domains':r.put(0x50000, struct.pack('<H', 64))
    else:
        original = r.i32
        def change_array(address):
            r.pointer_at(0x50010, 0)
            return original(address)
        r.i32 = change_array
    with pytest.raises(MemoryUnavailable):
        catalog.vtables(0x31000)


def populate_images(catalog):
    r, base = catalog.r, catalog.base
    for offset, value in {0xb4ef8:'488b0d91c06800', 0xb51d0:'488b4160c3',
                          0x14d420:'488b4130c3', 0xc4f93:'498d8dd0040000',
                          0x147340:'488d8108010000c3', 0x1c5f97:'488b9fd0000000'}.items():
        r.put(base + offset, bytes.fromhex(value))
    r.pointer_at(base + 0x740f90, 0x60000)
    for node, assembly, image, string, label, next_node in [
        (0x60000, 0x61000, 0x20000, 0x62000, b'Assembly-CSharp\0', 0x60100),
        (0x60100, 0x61100, 0x21000, 0x62100, b'Heathen.Steamworks\0', 0),
    ]:
        r.put(node, struct.pack('<QQ', assembly, next_node))
        r.pointer_at(assembly + 0x60, image)
        r.pointer_at(image + 0x30, string)
        r.pointer_at(image + 0x4c0, assembly)
        r.put(string, label)


def test_catalog_checks_loaded_accessors_and_assembly_ownership(catalog):
    populate_images(catalog)
    assert catalog.images() == {'Assembly-CSharp': 0x20000, 'Heathen.Steamworks': 0x21000}
    catalog.r.pointer_at(0x214c0, 0x61000)
    with pytest.raises(MemoryUnavailable, match='assembly_not_unique'):
        catalog.images()


@pytest.mark.parametrize('change,error', [
    ('signature', 'unsupported_catalog_layout'), ('cycle', 'assembly_list_invalid'),
    ('duplicate', 'assembly_not_unique'), ('missing', 'assembly_missing'),
    ('changed', 'assembly_list_changed'),
])
def test_catalog_rejects_invalid_assembly_list(catalog, change, error):
    populate_images(catalog)
    r = catalog.r
    if change == 'signature':r.put(catalog.base + 0xb4ef8, b'\0')
    elif change == 'cycle':r.pointer_at(0x60108, 0x60000)
    elif change == 'duplicate':r.put(0x62100, b'Assembly-CSharp\0')
    elif change == 'missing':r.pointer_at(0x60008, 0)
    else:
        original = r.cstring
        def change_head(address):
            r.pointer_at(catalog.base + 0x740f90, 0x60100)
            return original(address)
        r.cstring = change_head
    with pytest.raises(MemoryUnavailable, match=error):
        catalog.images()


def test_catalog_cancellation_budget_and_process_death(catalog, monkeypatch):
    catalog.r.stop.set()
    with pytest.raises(MemoryUnavailable, match='discovery_cancelled'):
        catalog.check()
    catalog.r.stop.clear()
    monkeypatch.setattr(module.time, 'monotonic', lambda: catalog.started + 6)
    with pytest.raises(MemoryUnavailable, match='catalog_unavailable'):
        catalog.check()
    monkeypatch.undo()
    catalog.r.game.alive = lambda: False
    with pytest.raises(MemoryUnavailable, match='process_changed'):
        catalog.images()


@pytest.mark.parametrize('outcome', ['success', 'catalog_failure', 'root_failure', 'cancelled', 'unsupported'])
def test_discovery_keeps_common_root_validation_and_bounded_fallback(catalog, monkeypatch, outcome):
    memory = GameMemory.__new__(GameMemory)
    memory.reader, memory.roots, memory.diagnostics = catalog.r, {}, {}
    calls = []
    def locate(self, specifications):
        calls.append('catalog')
        if outcome == 'unsupported':raise MemoryUnavailable('unsupported_catalog_layout')
        if outcome in ('catalog_failure', 'cancelled'):
            if outcome == 'cancelled':self.r.stop.set()
            raise MemoryUnavailable('catalog_unavailable')
        return {'cache': 1, 'lobby': 2}, {'cache': {3}, 'lobby': {4}}
    def resolve(*args):
        calls.append('roots')
        if outcome == 'root_failure':
            memory.roots['cache'] = (1, 2, 3)
            raise MemoryUnavailable('static_root_not_unique')
    def scan(specifications):
        assert memory.roots == {}
        calls.append('scan')
    monkeypatch.setattr(MonoCatalog, 'locate', locate)
    memory.resolve_roots, memory.discover_scan = resolve, scan
    if outcome in ('cancelled', 'unsupported'):
        with pytest.raises(MemoryUnavailable):memory.discover()
        assert calls == ['catalog']
    else:
        memory.discover()
        assert calls == {'success': ['catalog', 'roots'], 'catalog_failure': ['catalog', 'scan'],
                         'root_failure': ['catalog', 'roots', 'scan']}[outcome]
        assert memory.diagnostics['discovery_method'] == ('catalog' if outcome == 'success' else 'scan')
