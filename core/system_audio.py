"""Windows Core Audio endpoint volume, via its native COM interface.

No media keys, generated scripts, extra service or GPU dependencies.
"""
import ctypes as c
import uuid


class GUID(c.Structure):
    _fields_=[('data',c.c_ubyte*16)]
    def __init__(self,value):
        super().__init__()
        self.data[:]=uuid.UUID(value).bytes_le


def _check(hr):
    if hr<0: raise OSError(f'Windows Core Audio: HRESULT {hr & 0xffffffff:08x}')


def endpoint_volume(mode='status',value=None,cancelled=lambda:False):
    import os
    if os.name!='nt': raise RuntimeError('Volume do sistema disponível somente no Windows.')
    ole=c.OleDLL('ole32')
    ole.CoInitializeEx.argtypes=[c.c_void_p,c.c_ulong]
    ole.CoInitializeEx.restype=c.c_long
    hr=ole.CoInitializeEx(None,0)
    initialized=hr in (0,1)
    if not initialized and (hr & 0xffffffff)!=0x80010106: _check(hr)
    interfaces=[]
    def method(obj,index,types=(),values=()):
        table=c.cast(obj,c.POINTER(c.POINTER(c.c_void_p))).contents
        callback=c.WINFUNCTYPE(c.c_long,c.c_void_p,*types)(table[index])
        result=callback(obj,*values);_check(result)
    def state(obj):
        volume=c.c_float();muted=c.c_int()
        method(obj,9,(c.POINTER(c.c_float),),(c.byref(volume),))
        method(obj,15,(c.POINTER(c.c_int),),(c.byref(muted),))
        return {'volume_percent':volume.value*100,'muted':bool(muted.value)}
    try:
        enumerator=c.c_void_p()
        cls=GUID('BCDE0395-E52F-467C-8E3D-C4579291692E');iid=GUID('A95664D2-9614-4F35-A746-DE8DB63617E6')
        ole.CoCreateInstance.argtypes=[c.POINTER(GUID),c.c_void_p,c.c_ulong,c.POINTER(GUID),c.POINTER(c.c_void_p)]
        ole.CoCreateInstance.restype=c.c_long
        _check(ole.CoCreateInstance(c.byref(cls),None,1,c.byref(iid),c.byref(enumerator)))
        interfaces.append(enumerator)
        device=c.c_void_p()
        method(enumerator,4,(c.c_int,c.c_int,c.POINTER(c.c_void_p)),(0,1,c.byref(device)))
        interfaces.append(device)
        endpoint=c.c_void_p();iid=GUID('5CDF2C82-841E-4546-9722-0CF74078229A')
        method(device,3,(c.POINTER(GUID),c.c_ulong,c.c_void_p,c.POINTER(c.c_void_p)),(c.byref(iid),23,None,c.byref(endpoint)))
        interfaces.append(endpoint)
        from core.volume_control import adjust
        def write(target,muted):
            method(endpoint,14,(c.c_int,c.c_void_p),(int(muted),None))
            method(endpoint,7,(c.c_float,c.c_void_p),(target/100,None))
        return adjust(mode,value,lambda:state(endpoint),write,cancelled,scope='system')
    finally:
        for obj in reversed(interfaces):
            table=c.cast(obj,c.POINTER(c.POINTER(c.c_void_p))).contents
            c.WINFUNCTYPE(c.c_ulong,c.c_void_p)(table[2])(obj)
        if initialized: ole.CoUninitialize()
