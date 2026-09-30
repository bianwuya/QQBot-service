"""Retry only SQLite statements known not to have completed; never retry paid work."""
import sqlite3
import time


class Connection(sqlite3.Connection):
    def execute(self,*args,**kwargs):
        for attempt in range(4):
            try:return super().execute(*args,**kwargs)
            except sqlite3.OperationalError as ex:
                code=getattr(ex,'sqlite_errorcode',0)&255
                if code not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) or attempt==3:raise
                time.sleep(.03*(attempt+1))
