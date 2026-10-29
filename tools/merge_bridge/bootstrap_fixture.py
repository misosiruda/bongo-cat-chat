"""Execute the exact native thunk in a disposable Python process, never a game."""
import ctypes as C
import json
import os
import sys
from bootstrap import EXPORTS, ERROR_EXPORT, execute, kernel

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
        if i == 6 and mode == 'exception': args[3][0] = 999
        if i == 2 and mode == '2': args[3][0] = 1
        return 0 if mode == str(i) else returns[i]
    return C.WINFUNCTYPE(C.c_void_p, *types[i])(run)

for i in range(8): callbacks.append(callback(i))
exports = {name: C.cast(cb, C.c_void_p).value for name, cb in zip(EXPORTS, callbacks)}
error_text = C.create_string_buffer(b'fixture_load_error')
error_cb = C.WINFUNCTYPE(C.c_void_p, C.c_int)(lambda status: C.addressof(error_text))
exports[ERROR_EXPORT] = C.cast(error_cb, C.c_void_p).value
k = kernel()
handle = k.OpenProcess(0x043a, False, os.getpid())
try: result = execute(handle, exports, 'C:\\fixture\\bridge.dll',fixture_bytes=b'MZ-fixture')
finally: k.CloseHandle(handle)
print(json.dumps(dict(result=result, calls=calls, errors=errors)))
