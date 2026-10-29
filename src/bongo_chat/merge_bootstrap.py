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
OFF = {name: i * 8 for i, name in enumerate(EXPORTS)}
OFF.update(path=64, namespace=72, klass_name=80, method_name=88,
           domain=96, thread=104, assembly=112, image=120, klass=128,
           method=136, exception=144, status=152, stage=160, load_error=168)
OFF[ERROR_EXPORT] = 176
OFF.update(raw=400, raw_length=408)


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
    data = bytearray(512)
    for name in (*EXPORTS, ERROR_EXPORT):
        struct.pack_into('<Q', data, OFF[name], exports[name])
    for key, value in [('path', str(dll_path)), ('namespace', 'BongoCatChat.MergeBridge'),
                       ('klass_name', 'Bridge'), ('method_name', 'Install')]:
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
        result, n = C.create_string_buffer(512), C.c_size_t()
        if not k.ReadProcessMemory(handle, data, result, 512, C.byref(n)) or n.value != 512:
            raise RuntimeError('bootstrap_result_unreadable_no_retry')
        value = {key: struct.unpack_from('<Q', result.raw, OFF[key])[0] for key in ('status', 'stage', 'exception', 'load_error')}
        value['load_message'] = result.raw[192:392].split(b'\0')[0].decode('utf-8', 'replace')
        return value
    finally:
        # Never free memory under an unfinished remote instruction pointer.
        if not thread or finished:
            for address in (data, code):
                if address: k.VirtualFreeEx(handle, address, 0, 0x8000)
        if thread: k.CloseHandle(thread)
