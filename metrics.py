"""Daily aggregates only. No actor/scope/content dimension or arbitrary label."""
from datetime import datetime,timedelta
import hashlib
import hmac
import math
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

NAMES=frozenset(('messages_total','jobs_total','jobs_done','jobs_failed','jobs_interrupted','delivery_unknown',
    'ingest_rejected','model_requests','model_failures','model_switches','model_latency','model_probe_requests',
    'role_usage','ooc_hits','fallback_count','retry_count','proactive_attempts','proactive_sent','proactive_replied',
    'daily_suppressed','tool_calls','tool_success','tool_failure','tool_timeout','confirm_required','worker_latency'))
WORKERS=frozenset(('chat','file','media','tool','quote'))


def aggregate(db,days=1,now=None):
    days=days if days in (1,7,30) else 1
    today=datetime.fromtimestamp(time.time() if now is None else now).date()
    first=(today-timedelta(days=days-1)).isoformat()
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metrics_daily'").fetchone()
    rows=[] if not exists else db.execute('''SELECT metric,dimension,sum(samples),sum(total),max(maximum)
        FROM metrics_daily WHERE day>=? AND day<=? GROUP BY metric,dimension ORDER BY metric,dimension''',(first,today.isoformat())).fetchall()
    data={}
    for name,dimension,n,total,maximum in rows:
        data.setdefault(name,{})[dimension]={'samples':n,'total':round(total,6),'average':round(total/n,6) if n else 0,'maximum':round(maximum,6)}
    return {'days':days,'from':first,'through':today.isoformat(),'metrics':data}


def offline(path,days=1,now=None):
    # Never instantiate Store here: it would mutate processing/sending job states.
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:return aggregate(db,days,now)
    finally:db.close()


def total(report,name):
    return sum(row['total'] for row in report.get('metrics',{}).get(name,{}).values())


class Metrics:
    def __init__(self,store,clock=time.time,monotonic=time.monotonic):
        self.store=store;self.clock=clock;self.monotonic=monotonic;self.started=monotonic()
        self.guard=threading.RLock();self.running={};self.dropped=0
        with store.lock,store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS metrics_daily(
                day TEXT,metric TEXT,dimension TEXT,samples INTEGER,total REAL,maximum REAL,
                PRIMARY KEY(day,metric,dimension))''')
        salt=store.get('*','metrics_salt')
        if not isinstance(salt,str):salt=secrets.token_hex(32);store.set('*','metrics_salt',salt)
        self.salt=salt.encode()

    def label(self,kind,value):
        if kind not in ('model','role','tool'):raise ValueError('invalid metric label domain')
        return kind+':'+hmac.new(self.salt,str(value).encode(),hashlib.sha256).hexdigest()[:16]

    def record(self,name,dimension='',value=1):
        if name not in NAMES:raise ValueError('unknown metric')
        if dimension not in WORKERS and dimension!='' and not re.fullmatch(r'(model|role|tool):[0-9a-f]{16}',dimension):
            raise ValueError('unsafe metric dimension')
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e8:
            raise ValueError('invalid metric value')
        day=datetime.fromtimestamp(self.clock()).strftime('%Y-%m-%d')
        with self.store.lock,self.store.db:
            self.store.db.execute('''INSERT INTO metrics_daily VALUES(?,?,?,?,?,?)
                ON CONFLICT(day,metric,dimension) DO UPDATE SET samples=samples+1,total=total+excluded.total,
                maximum=max(maximum,excluded.maximum)''',(day,name,dimension,1,float(value),float(value)))

    def emit(self,*args,**kwargs):
        try:self.record(*args,**kwargs)
        except Exception:
            with self.guard:self.dropped+=1
            return False
        return True

    def report(self,days=1):
        with self.store.lock:return aggregate(self.store.db,days,self.clock())

    def begin_job(self,ident,kind):
        if kind not in WORKERS:return
        with self.guard:self.running[ident]=(kind,self.monotonic())

    def end_job(self,ident):
        with self.guard:row=self.running.pop(ident,None)
        if row:self.emit('worker_latency',row[0],max(0,self.monotonic()-row[1]))

    def alerts(self,report=None,states=()):
        report=report or self.report();alerts=[];severity='OK'
        unknown=total(report,'delivery_unknown')
        if unknown:alerts.append('unknown_delivery');severity='CRITICAL' if unknown>=3 else 'WARN'
        if any(state=='COOLDOWN' for state in states):alerts.append('model_cooldown');severity=max((severity,'WARN'),key=('OK','WARN','CRITICAL').index)
        if total(report,'model_failures')>=5 and total(report,'model_failures')/max(1,total(report,'model_requests'))>=.5:
            alerts.append('model_failure_rate');severity='CRITICAL'
        if total(report,'tool_failure')>=5 and total(report,'tool_failure')/max(1,total(report,'tool_calls'))>=.5:
            alerts.append('tool_failure_rate');severity=max((severity,'WARN'),key=('OK','WARN','CRITICAL').index)
        with self.guard:
            if any(kind=='media' and self.monotonic()-start>600 for kind,start in self.running.values()):
                alerts.append('media_stalled');severity='CRITICAL'
        return {'level':severity,'reasons':alerts}

    def summary(self,queue_depth=0,states=()):
        report=self.report();m=report['metrics'];alert=self.alerts(report,states)
        lines=['运行 {} 秒｜队列 {}｜{}'.format(int(self.monotonic()-self.started),queue_depth,alert['level']),
               '今日消息 {}｜任务 {}｜失败 {}｜中断 {}｜未知投递 {}'.format(*[int(total(report,k)) for k in
                    ('messages_total','jobs_total','jobs_failed','jobs_interrupted','delivery_unknown')]),
               '模型尝试 {}｜失败 {}｜切换 {}'.format(*[int(total(report,k)) for k in ('model_requests','model_failures','model_switches')]),
               '人格使用 {}｜OOC {}｜重试 {}｜兜底 {}'.format(*[int(total(report,k)) for k in ('role_usage','ooc_hits','retry_count','fallback_count')]),
               '主动尝试 {}｜确认发送 {}｜回应 {}｜当日抑制群次 {}'.format(*[int(total(report,k)) for k in ('proactive_attempts','proactive_sent','proactive_replied','daily_suppressed')]),
               '工具申请/执行 {}｜成功 {}｜失败 {}｜超时 {}｜需确认 {}'.format(*[int(total(report,k)) for k in
                    ('tool_calls','tool_success','tool_failure','tool_timeout','confirm_required')])]
        latency=m.get('worker_latency',{})
        lines.append('平均耗时(s)：'+' / '.join(k+' '+str(round(latency.get(k,{}).get('average',0),2)) for k in ('chat','file','media','tool','quote')))
        if alert['reasons']:lines.append('告警：'+','.join(alert['reasons']))
        if self.dropped:lines.append('指标写入失败计数：'+str(self.dropped))
        return '\n'.join(lines)[:1100]

    def prune(self):
        cutoff=(datetime.fromtimestamp(self.clock()).date()-timedelta(days=90)).isoformat()
        with self.store.lock,self.store.db:
            self.store.db.execute('DELETE FROM metrics_daily WHERE day<?',(cutoff,))
            self.store.db.execute('DELETE FROM tool_audit WHERE time<?',(self.clock()-30*86400,))
            self.store.db.execute('DELETE FROM app_confirmations WHERE expires<?',(self.clock()-86400,))
