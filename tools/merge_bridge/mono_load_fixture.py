"""Disposable-process metadata loading diagnostic using the local Mono runtime."""
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from bootstrap import EXPORTS, ERROR_EXPORT, execute, kernel, start_ticks

root = Path(r'C:\Program Files (x86)\Steam\steamapps\common\BongoCat')
mono = C.CDLL(str(root / 'MonoBleedingEdge/EmbedRuntime/mono-2.0-bdwgc.dll'))
mono.mono_set_dirs.argtypes = [C.c_char_p, C.c_char_p]
mono.mono_jit_init_version.argtypes = [C.c_char_p, C.c_char_p]
mono.mono_jit_init_version.restype = C.c_void_p
mono.mono_assembly_open.argtypes = [C.c_char_p, C.POINTER(C.c_int)]
mono.mono_assembly_open.restype = C.c_void_p
mono.mono_domain_assembly_open.argtypes = [C.c_void_p, C.c_char_p]
mono.mono_domain_assembly_open.restype = C.c_void_p
mono.mono_set_assemblies_path.argtypes = [C.c_char_p]
mono.mono_set_assemblies_path(str(root / 'BongoCat_Data/Managed').encode())
mono.mono_set_dirs(str(root / 'BongoCat_Data/Managed').encode(), str(root / 'MonoBleedingEdge/etc').encode())
domain = mono.mono_jit_init_version(b'merge-fixture', b'v4.0.30319')
status = C.c_int(-1)
path = Path(sys.argv[1]).resolve()
if '--install-fixture' in sys.argv or '--bootstrap-fixture' in sys.argv:
    folder = Path(tempfile.mkdtemp(prefix='merge-mono-fixture-'))
    shutil.copyfile(path, folder / path.name)
    path = folder / path.name
    k=kernel(); h=k.OpenProcess(0x400,False,os.getpid())
    try: ticks=start_ticks(k,h)
    finally: k.CloseHandle(h)
    (folder/'session.json').write_text(json.dumps(dict(protocol=1,pid=os.getpid(),process_start_ticks=ticks,epoch='a'*32,token='b'*64,test_budget=0,mode='interactive' if '--interactive' in sys.argv else 'test')))
if '--bootstrap-fixture' in sys.argv:
    k=kernel(); h=k.OpenProcess(0x043a,False,os.getpid())
    exports={name:C.cast(getattr(mono,name),C.c_void_p).value for name in (*EXPORTS,ERROR_EXPORT)}
    try: result=execute(h,exports,path)
    finally:k.CloseHandle(h)
    print(json.dumps(dict(status=result['status'],stage=result['stage'],managed_exception=bool(result['exception']),load_error=result['load_error'])),flush=True)
    sys.exit(0 if result['status']==1 else 1)
path = str(path).encode()
domain_assembly = mono.mono_domain_assembly_open(domain, path)
assembly = mono.mono_assembly_open(path, C.byref(status))
print(json.dumps(dict(domain=bool(domain), domain_assembly=bool(domain_assembly), assembly=bool(assembly), status=status.value)), flush=True)
if '--install-fixture' in sys.argv and assembly:
    specs = {
        'mono_assembly_get_image': ([C.c_void_p], C.c_void_p),
        'mono_class_from_name': ([C.c_void_p,C.c_char_p,C.c_char_p],C.c_void_p),
        'mono_class_get_method_from_name': ([C.c_void_p,C.c_char_p,C.c_int],C.c_void_p),
        'mono_runtime_invoke': ([C.c_void_p,C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)],C.c_void_p),
        'mono_object_get_class': ([C.c_void_p],C.c_void_p),
        'mono_class_get_name': ([C.c_void_p],C.c_char_p),
    }
    for name,(args,ret) in specs.items():getattr(mono,name).argtypes=args;getattr(mono,name).restype=ret
    cls=mono.mono_class_from_name(mono.mono_assembly_get_image(assembly),b'BongoCatChat.MergeBridge',b'Bridge')
    method=mono.mono_class_get_method_from_name(cls,b'Install',0)
    error=C.c_void_p()
    mono.mono_runtime_invoke(method,None,None,C.byref(error))
    print(json.dumps(dict(install_exception=mono.mono_class_get_name(mono.mono_object_get_class(error)).decode() if error else None)),flush=True)
    if error: sys.exit(1)
