"""Execute the exact native thunk in a disposable Python process, never a game."""
import ctypes as C
import json
import os
import sys
from bootstrap import EXPORTS, ERROR_EXPORT, DIAGNOSTIC_EXPORTS, execute, kernel

mode = sys.argv[1]
calls, callbacks, errors = [], [], []
returns = [101, 102, 103, 104, 105, 106, 0, 0]
expected = [(), (101,), (b'MZ-fixture', 10, 1, 0, b'C:\\fixture\\bridge.dll'), (103,b'C:\\fixture\\bridge.dll',0),
            (103, b'BongoCatChat.MergeBridge', b'Bridge'), (105, b'Install', 0),
            (106, None, None), (102,)]
types = [(), (C.c_void_p,), (C.c_void_p,C.c_uint,C.c_int,C.POINTER(C.c_int),C.c_int,C.c_char_p), (C.c_void_p,C.c_char_p,C.POINTER(C.c_int),C.c_int),
         (C.c_void_p, C.c_char_p, C.c_char_p), (C.c_void_p, C.c_char_p, C.c_int),
         (C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)), (C.c_void_p,)]

def callback(i):
    def run(*args):
        calls.append(i)
        check = (C.string_at(args[0],args[1]),args[1],args[2],args[4],args[5]) if i==2 else (args[0],args[1],args[3]) if i==3 else args[:3] if i==6 else args
        if check != expected[i]: errors.append(i)
        if i == 6 and mode in {'exception', 'nested', 'unknown', 'cyclic', 'missing_fields', 'long', 'null_handle', 'null_class'}: args[3][0] = 999
        if i == 2 and mode == '2': args[3][0] = 1
        return 0 if mode == str(i) else returns[i]
    return C.WINFUNCTYPE(C.c_void_p, *types[i])(run)

for i in range(8): callbacks.append(callback(i))
exports = {name: C.cast(cb, C.c_void_p).value for name, cb in zip(EXPORTS, callbacks)}
error_text = C.create_string_buffer(b'fixture_load_error')
error_cb = C.WINFUNCTYPE(C.c_void_p, C.c_int)(lambda status: C.addressof(error_text))
exports[ERROR_EXPORT] = C.cast(error_cb, C.c_void_p).value
pins, freed, diagnostic_calls = [], [], []
texts = {}
for obj, kind, namespace, message in [
    (999, 'InvalidOperationException', 'System', 'bridge_init_5'),
    (1999, 'TypeInitializationException', 'System', 'private-user-path'),
    (2999, 'MissingMethodException', 'System', 'secret-token')]:
    if mode == 'unknown': kind, namespace, message = 'PrivateUserClass', 'private-user-path', 'secret-token'
    if mode == 'long': message = 'bridge_init_5' + 'X'*200
    texts[obj] = (C.create_string_buffer(kind.encode()), C.create_string_buffer(namespace.encode()),
                  C.create_string_buffer(message.encode('utf-16-le') + b'\0\0'), len(message))
def pin(obj, pinned):
    diagnostic_calls.append('pin')
    if mode == 'null_handle': return 0
    assert pinned == 1
    pins.append(obj)
    return 0x100000000 + len(pins)
def field(cls, name):
    assert cls == 888  # Exception base fields; a derived class may shadow them.
    if mode == 'missing_fields': return 0
    return {'_message': 1, '_innerException': 2}[name.decode()]
def field_value(obj, selected, output):
    output[0] = (obj + 10000 if selected == 1 else
                 999 if mode == 'cyclic' else obj + 1000 if mode == 'nested' and obj < 2999 else 0)
diagnostic = [
    (C.c_void_p, (C.c_void_p, C.c_int), pin),
    (None, (C.c_void_p,), lambda handle: freed.append(handle - 0x100000000)),
    (C.c_void_p, (C.c_void_p,), lambda obj: 0 if mode == 'null_class' else obj),
    (C.c_void_p, (C.c_void_p,), lambda cls: C.addressof(texts[cls][0])),
    (C.c_void_p, (C.c_void_p,), lambda cls: C.addressof(texts[cls][1])),
    (C.c_void_p, (C.c_void_p,C.c_char_p), field),
    (None, (C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)), field_value),
    (C.c_int, (C.c_void_p,), lambda obj: texts[obj - 10000][3]),
    (C.c_void_p, (C.c_void_p,), lambda obj: C.addressof(texts[obj - 10000][2])),
    (C.c_void_p, (), lambda: diagnostic_calls.append('exception_base') or 888),
]
for name, (result, args, function) in zip(DIAGNOSTIC_EXPORTS, diagnostic):
    cb = C.WINFUNCTYPE(result, *args)(function)
    callbacks.append(cb)
    exports[name] = C.cast(cb,C.c_void_p).value
k = kernel()
handle = k.OpenProcess(0x043a, False, os.getpid())
try: result = execute(handle, exports, 'C:\\fixture\\bridge.dll',fixture_bytes=b'MZ-fixture')
finally: k.CloseHandle(handle)
assert sorted(freed) == list(range(1, len(pins)+1))
print(json.dumps(dict(result=result, calls=calls, errors=errors, diagnostic_calls=diagnostic_calls)))
