"""Acquire before opening Store, so a second service cannot run crash recovery."""
from pathlib import Path
import os
import socket
from contextlib import contextmanager


class ServiceAlreadyRunning(RuntimeError):
    pass


class ServiceLease:
    def __init__(self,path):self.path=Path(path);self.handle=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        handle=open(self.path,'a+b')
        handle.seek(0,os.SEEK_END)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close();raise ServiceAlreadyRunning('服务实例已运行，未打开业务数据库') from None
        self.handle=handle
        return self

    def __exit__(self,*args):
        try:
            self.handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
        finally:self.handle.close();self.handle=None


@contextmanager
def health_listener(port):
    """Reserve the health port before Store recovery, including legacy running services."""
    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        if os.name=='nt':listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        else:listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(('127.0.0.1',port));listener.listen(5)
        yield listener
    finally:listener.close()
