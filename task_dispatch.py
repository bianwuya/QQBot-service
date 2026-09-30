"""Conservative task classes and per-scope atomic multi-element deliveries."""
from contextlib import contextmanager
import threading
from quotes import quote_request


def classify(event):
    text=event.get('text','').strip();head,_,arg=text.partition(' ')
    if event.get('social'):return 'tool'
    if quote_request(event):return 'quote'
    if head in ('/下载','/打包','/导出') or (head=='/知识库' and arg.split(' ',1)[0] in ('导入','重建')):return 'file'
    if head.startswith('/'):return 'tool'
    if event.get('files'):return 'file'
    if event.get('videos'):return 'media'
    return 'chat'


def worker_counts(config=None):
    config=config if isinstance(config,dict) else {}
    defaults={'chat':2,'file':1,'media':1,'tool':1,'quote':2}
    caps={'chat':4,'file':2,'media':1,'tool':1,'quote':2}
    return {k:max(1,min(caps[k],config[k])) if type(config.get(k)) is int else v for k,v in defaults.items()}


class LockPool:
    def __init__(self):
        self.guard=threading.Lock();self.entries={}

    @contextmanager
    def hold(self,key):
        with self.guard:
            entry=self.entries.setdefault(key,[threading.RLock(),0]);entry[1]+=1
        try:
            with entry[0]:yield
        finally:
            with self.guard:
                entry[1]-=1
                if entry[1]==0:del self.entries[key]
