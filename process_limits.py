"""Windows job memory/child-lifetime boundary for untrusted document/media helpers."""
import os

def attach_job(process,memory_mb=768):
    if os.name!='nt':return None
    import ctypes
    from ctypes import wintypes as W
    class BASIC(ctypes.Structure):
        _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),
                  ('LimitFlags',W.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),
                  ('ActiveProcessLimit',W.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',W.DWORD),('SchedulingClass',W.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(n,ctypes.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class EXT(ctypes.Structure):
        _fields_=[('BasicLimitInformation',BASIC),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateJobObjectW.argtypes=[ctypes.c_void_p,W.LPCWSTR];k.CreateJobObjectW.restype=W.HANDLE
    k.SetInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD]
    k.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE]
    k.CloseHandle.argtypes=[W.HANDLE]
    handle=k.CreateJobObjectW(None,None)
    info=EXT();info.BasicLimitInformation.LimitFlags=0x2000|0x100|0x200
    info.ProcessMemoryLimit=memory_mb*1024*1024;info.JobMemoryLimit=memory_mb*1024*1024
    if not handle or not k.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not k.AssignProcessToJobObject(handle,W.HANDLE(int(process._handle))):
        if handle:k.CloseHandle(handle)
        process.kill();process.wait()
        raise RuntimeError('Unable to establish child process memory boundary')
    return lambda:k.CloseHandle(handle)
