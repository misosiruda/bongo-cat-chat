"""Fixed Mono bootstrap for the explicitly connected item merge module.

Never accepts arbitrary method names or code from the app renderer.
All consuming operations are in Bridge.cs, not this bootstrap.
"""
import ctypes as C
from ctypes import wintypes as W
import struct
from pathlib import Path

EXPORTS = ('mono_get_root_domain', 'mono_thread_attach', 'mono_image_open_from_data_with_name',
           'mono_assembly_load_from_full', 'mono_class_from_name',
           'mono_class_get_method_from_name', 'mono_runtime_invoke', 'mono_thread_detach')
ERROR_EXPORT = 'mono_image_strerror'
DIAGNOSTIC_EXPORTS = ('mono_gchandle_new_v2', 'mono_gchandle_free_v2', 'mono_object_get_class',
    'mono_class_get_name', 'mono_class_get_namespace', 'mono_class_get_field_from_name',
    'mono_field_get_value', 'mono_string_length', 'mono_string_chars', 'mono_get_exception_class')
OFF = {name: i * 8 for i, name in enumerate(EXPORTS)}
OFF.update(path=64, namespace=72, klass_name=80, method_name=88,
           domain=96, thread=104, assembly=112, image=120, klass=128,
           method=136, exception=144, status=152, stage=160, load_error=168)
OFF[ERROR_EXPORT] = 176
OFF.update(raw=400, raw_length=408)
OFF.update({name: 416 + i * 8 for i, name in enumerate(DIAGNOSTIC_EXPORTS)})
OFF.update(diagnostic_exception=608, diagnostic_class=616, diagnostic_message=624,
           exception_class=632, message_field=688, inner_field=696)
DIAGNOSTIC_BASE, DIAGNOSTIC_STRIDE, RESULT_SIZE = 768, 336, 2048


def thunk():
    """Windows x64 ABI: one data pointer, preserved RBX, aligned shadow space."""
    code, labels, fixups = bytearray(), {}, []

    def emit(raw): code.extend(bytes.fromhex(raw))
    def disp(value): code.extend(struct.pack('<i', value))
    def load(reg, name):
        emit({'rcx': '48 8b 8b', 'rdx': '48 8b 93', 'r8': '4c 8b 83'}[reg]); disp(OFF[name])
    def save(name): emit('48 89 83'); disp(OFF[name])
    def branch(op, label):
        emit(op); fixups.append((len(code), label)); disp(0)
    def integer(name, n): emit('48 c7 83'); disp(OFF[name]); disp(n)
    def call(name, out=None):
        integer('stage', EXPORTS.index(name) + 1)
        emit('ff 93'); disp(OFF[name])
        if out:
            save(out); emit('48 85 c0'); branch('0f 84', 'cleanup')

    def native(name):
        # Diagnostic accessors never invoke a managed getter or overwrite stage 7.
        emit('ff 93'); disp(OFF[name])

    def address(reg, offset):
        emit({'rdx': '48 8d 93', 'r8': '4c 8d 83', 'r10': '4c 8d 93'}[reg]); disp(offset)

    def copy_name(offset, label):
        emit('48 85 c0'); branch('0f 84', label + '_done')
        emit('48 89 c1'); address('r10', offset); emit('41 bb 40 00 00 00')
        labels[label] = len(code)
        emit('8a 11 41 88 12 84 d2'); branch('0f 84', label + '_done')
        emit('48 ff c1 49 ff c2 41 ff cb'); branch('0f 85', label)
        labels[label + '_done'] = len(code)

    emit('53 48 83 ec 30 48 89 cb')  # shadow space plus fifth/sixth arguments
    call(EXPORTS[0], 'domain')
    load('rcx', 'domain'); call(EXPORTS[1], 'thread')
    load('rcx', 'raw'); load('rdx', 'raw_length'); emit('41 b8 01 00 00 00 4c 8d 8b'); disp(OFF['load_error'])
    emit('48 c7 44 24 20 00 00 00 00 48 8b 83'); disp(OFF['path']); emit('48 89 44 24 28')
    call(EXPORTS[2], 'image')
    load('rcx', 'image'); load('rdx', 'path'); emit('4c 8d 83'); disp(OFF['load_error']); emit('45 31 c9')
    call(EXPORTS[3], 'assembly')
    load('rcx', 'image'); load('rdx', 'namespace'); load('r8', 'klass_name'); call(EXPORTS[4], 'klass')
    load('rcx', 'klass'); load('rdx', 'method_name'); emit('45 31 c0'); call(EXPORTS[5], 'method')
    load('rcx', 'method'); emit('31 d2 45 31 c0 4c 8d 8b'); disp(OFF['exception'])
    call(EXPORTS[6]); integer('status', 1)
    emit('48 83 bb'); disp(OFF['exception']); emit('00'); branch('0f 84', 'cleanup')
    integer('status', 2)
    load('rcx', 'exception'); emit('48 89 8b'); disp(OFF['diagnostic_exception'])
    for level in range(3):
        record = DIAGNOSTIC_BASE + DIAGNOSTIC_STRIDE * level
        next_level = 'inner_' + str(level)
        # Pin both the exception and its message until all bounded copies finish.
        load('rcx', 'diagnostic_exception'); emit('48 85 c9'); branch('0f 84', 'diagnostics_done')
        emit('ba 01 00 00 00'); native('mono_gchandle_new_v2')
        emit('48 89 83'); disp(640 + level * 8)
        emit('48 85 c0'); branch('0f 84', 'diagnostics_done')
        if level == 0:
            # Establish the GC root before any other diagnostic accessor.
            native('mono_get_exception_class'); save('exception_class')
            emit('48 85 c0'); branch('0f 84', 'diagnostics_done')
        load('rcx', 'diagnostic_exception'); native('mono_object_get_class'); save('diagnostic_class')
        emit('48 85 c0'); branch('0f 84', 'diagnostics_done')
        load('rcx', 'diagnostic_class'); native('mono_class_get_name'); copy_name(record, 'name_' + str(level))
        load('rcx', 'diagnostic_class'); native('mono_class_get_namespace'); copy_name(record + 64, 'namespace_' + str(level))
        # Always read System.Exception's fields, never a custom subclass's shadow fields.
        load('rcx', 'exception_class'); load('rdx', 'message_field'); native('mono_class_get_field_from_name')
        emit('48 85 c0'); branch('0f 84', next_level)
        emit('48 89 c2'); load('rcx', 'diagnostic_exception'); address('r8', OFF['diagnostic_message'])
        integer('diagnostic_message', 0); native('mono_field_get_value')
        load('rcx', 'diagnostic_message'); emit('48 85 c9'); branch('0f 84', next_level)
        emit('ba 01 00 00 00'); native('mono_gchandle_new_v2')
        emit('48 89 83'); disp(664 + level * 8)
        emit('48 85 c0'); branch('0f 84', next_level)
        load('rcx', 'diagnostic_message'); native('mono_string_length'); emit('89 c0')
        emit('85 c0'); branch('0f 84', next_level)
        emit('83 f8 5f'); branch('0f 87', next_level)  # Reject negative/long messages, never truncate.
        emit('48 89 83'); disp(record + 128)
        load('rcx', 'diagnostic_message'); native('mono_string_chars')
        emit('48 85 c0'); branch('0f 84', next_level)
        emit('48 89 c1'); address('r10', record + 136)
        emit('44 8b 9b'); disp(record + 128); emit('41 d1 e3')
        labels['message_' + str(level)] = len(code)
        emit('8a 11 41 88 12 48 ff c1 49 ff c2 41 ff cb'); branch('0f 85', 'message_' + str(level))
        labels[next_level] = len(code)
        load('rcx', 'exception_class'); load('rdx', 'inner_field'); native('mono_class_get_field_from_name')
        emit('48 85 c0'); branch('0f 84', 'diagnostics_done')
        emit('48 89 c2'); load('rcx', 'diagnostic_exception'); address('r8', OFF['diagnostic_exception'])
        integer('diagnostic_exception', 0); native('mono_field_get_value')
    labels['diagnostics_done'] = len(code)
    for offset in range(640, 688, 8):
        emit('48 8b 8b'); disp(offset); emit('48 85 c9'); branch('0f 84', 'free_' + str(offset))
        native('mono_gchandle_free_v2')
        labels['free_' + str(offset)] = len(code)
    labels['cleanup'] = len(code)
    # Copy the Mono loader's bounded error string before detaching its CRT thread.
    emit('48 83 bb'); disp(OFF['load_error']); emit('00'); branch('0f 84', 'detach')
    load('rcx', 'load_error'); emit('ff 93'); disp(OFF[ERROR_EXPORT])
    emit('48 85 c0'); branch('0f 84', 'detach')
    emit('48 89 c1 4c 8d 93'); disp(192); emit('41 bb c8 00 00 00')
    labels['copy_error'] = len(code)
    emit('8a 11 41 88 12 84 d2'); branch('0f 84', 'detach')
    emit('48 ff c1 49 ff c2 41 ff cb'); branch('0f 85', 'copy_error')
    labels['detach'] = len(code)
    load('rcx', 'thread'); emit('48 85 c9'); branch('0f 84', 'end')
    # Do not overwrite the diagnostic stage when detaching.
    emit('ff 93'); disp(OFF[EXPORTS[7]])
    labels['end'] = len(code)
    emit('31 c0 48 83 c4 30 5b c3')
    for pos, label in fixups:
        struct.pack_into('<i', code, pos, labels[label] - pos - 4)
    return bytes(code)


def data_block(base, exports, dll_path, dll_bytes):
    data = bytearray(RESULT_SIZE)
    for name in (*EXPORTS, ERROR_EXPORT, *DIAGNOSTIC_EXPORTS):
        struct.pack_into('<Q', data, OFF[name], exports[name])
    for key, value in [('path', str(dll_path)), ('namespace', 'BongoCatChat.MergeBridge'),
                       ('klass_name', 'Bridge'), ('method_name', 'Install'),
                       ('message_field', '_message'), ('inner_field', '_innerException')]:
        encoded = value.encode('utf-8') + b'\0'
        struct.pack_into('<Q', data, OFF[key], base + len(data))
        data.extend(encoded)
    struct.pack_into('<Q', data, OFF['raw'], base + len(data))
    struct.pack_into('<Q', data, OFF['raw_length'], len(dll_bytes))
    data.extend(dll_bytes)
    return bytes(data)


def kernel():
    k = C.WinDLL('kernel32', use_last_error=True)
    specs = {
        'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'GetProcessTimes': ([W.HANDLE] + [C.POINTER(C.c_ulonglong)] * 4, W.BOOL),
        'VirtualAllocEx': ([W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD], C.c_void_p),
        'VirtualFreeEx': ([W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD], W.BOOL),
        'VirtualProtectEx': ([W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
        'WriteProcessMemory': ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
        'ReadProcessMemory': ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
        'FlushInstructionCache': ([W.HANDLE, C.c_void_p, C.c_size_t], W.BOOL),
        'CreateRemoteThread': ([W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)], W.HANDLE),
        'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
        'GetExitCodeThread': ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
    }
    for name, (args, result) in specs.items():
        getattr(k, name).argtypes, getattr(k, name).restype = args, result
    return k


def start_ticks(k, handle):
    values = [C.c_ulonglong() for _ in range(4)]
    if not k.GetProcessTimes(handle, *(C.byref(v) for v in values)):
        raise C.WinError(C.get_last_error())
    return values[0].value + 504911232000000000


def execute(handle, exports, dll_path, *, fixture_bytes=None):
    k = kernel()
    data = code = thread = None
    finished = False
    try:
        dll_bytes = Path(dll_path).read_bytes() if fixture_bytes is None else fixture_bytes
        if not 0 < len(dll_bytes) < 1024*1024: raise ValueError('invalid_helper_size')
        data_size = len(dll_bytes) + 8192
        data = k.VirtualAllocEx(handle, None, data_size, 0x3000, 4)
        code = k.VirtualAllocEx(handle, None, 4096, 0x3000, 4)
        if not data or not code: raise C.WinError(C.get_last_error())
        payload = data_block(data, exports, dll_path, dll_bytes)
        if len(payload) > data_size: raise ValueError('path_too_long')
        for address, raw in [(data, payload), (code, thunk())]:
            n = C.c_size_t()
            if not k.WriteProcessMemory(handle, address, raw, len(raw), C.byref(n)) or n.value != len(raw):
                raise C.WinError(C.get_last_error())
        old = W.DWORD()
        if not k.VirtualProtectEx(handle, code, 4096, 0x20, C.byref(old)) or not k.FlushInstructionCache(handle, code, 4096):
            raise C.WinError(C.get_last_error())
        thread = k.CreateRemoteThread(handle, None, 0, code, data, 0, None)
        if not thread: raise C.WinError(C.get_last_error())
        if k.WaitForSingleObject(thread, 10000) != 0:
            raise RuntimeError('bootstrap_outcome_unknown_no_retry')
        finished = True
        exit_code = W.DWORD()
        if not k.GetExitCodeThread(thread, C.byref(exit_code)) or exit_code.value != 0:
            raise RuntimeError('bootstrap_thread_failed_no_retry')
        result, n = C.create_string_buffer(RESULT_SIZE), C.c_size_t()
        if not k.ReadProcessMemory(handle, data, result, RESULT_SIZE, C.byref(n)) or n.value != RESULT_SIZE:
            raise RuntimeError('bootstrap_result_unreadable_no_retry')
        value = {key: struct.unpack_from('<Q', result.raw, OFF[key])[0] for key in ('status', 'stage', 'exception', 'load_error')}
        value['load_message'] = result.raw[192:392].split(b'\0')[0].decode('utf-8', 'replace')
        value.update(managed_diagnostics(result.raw))
        return value
    finally:
        # Never free memory under an unfinished remote instruction pointer.
        if not thread or finished:
            for address in (data, code):
                if address: k.VirtualFreeEx(handle, address, 0, 0x8000)
        if thread: k.CloseHandle(thread)


def managed_diagnostics(raw):
    """Discard all free text before results leave the native bootstrap boundary."""
    from .diagnostics import MANAGED_TYPES, INITIALIZATION_STEPS, MANAGED_REASONS
    types, details = [], {}
    for level in range(3):
        offset = DIAGNOSTIC_BASE + DIAGNOSTIC_STRIDE * level
        def name(start):
            data = raw[start:start + 64]
            return data.split(b'\0')[0].decode('ascii', 'replace') if b'\0' in data else ''
        kind, namespace = name(offset), name(offset + 64)
        if not kind:
            break
        qualified = namespace + '.' + kind
        types.append(qualified if qualified in MANAGED_TYPES else 'other')
        count = struct.unpack_from('<Q', raw, offset + 128)[0]
        if 0 < count < 96:
            message = raw[offset + 136:offset + 136 + count * 2].decode('utf-16-le', 'replace')
            if qualified == 'System.InvalidOperationException':
                if message in INITIALIZATION_STEPS:
                    details.setdefault('initialization_step', INITIALIZATION_STEPS[message])
                elif message in MANAGED_REASONS:
                    details['managed_reason'] = MANAGED_REASONS[message]
    if types:
        details['managed_exception_types'] = types
    return details
