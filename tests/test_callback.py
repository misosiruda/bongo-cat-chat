import ctypes as C
import json

import pytest

from bongo_chat.steam import Callback, ChatHeader, Steam


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_body_copied_before_callback_freed_and_id_is_app_owned(newline):
    steam=Steam.__new__(Steam)
    steam.pipe=1;steam.matchmaking=1;steam.rejected=0
    text = newline.join(["수신 버퍼 검증", "", "둘째 줄 🙂"])
    raw=json.dumps({"Channel": 3, "Message": text}, ensure_ascii=False).encode("utf-8")
    header=ChatHeader(10,20,1,7)
    freed=[];used=[False]
    steam.run_frame=lambda pipe:None
    def next_callback(pipe,out):
        if used[0]:return False
        used[0]=True
        cb=C.cast(out,C.POINTER(Callback)).contents
        cb.kind=507;cb.size=C.sizeof(header);cb.data=C.addressof(header)
        return True
    def read_entry(mm,lobby,chat_id,sender,buffer,size,entry_type):
        assert not freed and chat_id==7
        C.cast(sender,C.POINTER(C.c_uint64))[0]=20
        C.cast(entry_type,C.POINTER(C.c_int))[0]=1
        C.memmove(buffer,raw,len(raw));return len(raw)
    def free(pipe):
        freed.append(True);C.memset(C.addressof(header),0,C.sizeof(header))
    steam.next_callback=next_callback;steam.read_entry=read_entry;steam.free_callback=free
    result=steam.pump({"lobby":"10","account":"30","generation":"fixture"},{"20"})
    assert freed and len(result)==1 and result[0]["text"]==text
    assert steam.rejected == 0
    assert len(result[0]["id"])==36
    assert "chat_id" not in result[0]
