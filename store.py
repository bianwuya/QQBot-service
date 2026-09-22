import json
import sqlite3
import threading
import time
import uuid

class Busy(ValueError):pass

class Store:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,event_key TEXT UNIQUE,scope TEXT,owner TEXT,payload TEXT,status TEXT,created REAL,output TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS upload_claims(file_key TEXT PRIMARY KEY,job TEXT);
        CREATE TABLE IF NOT EXISTS delivery(job TEXT,idx INTEGER,status TEXT,receipt TEXT,PRIMARY KEY(job,idx));
        CREATE TABLE IF NOT EXISTS settings(scope TEXT,key TEXT,value TEXT,PRIMARY KEY(scope,key));
        CREATE TABLE IF NOT EXISTS history(scope TEXT,owner TEXT,role TEXT,content TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS files(scope TEXT,owner TEXT,path TEXT,name TEXT,created REAL,PRIMARY KEY(scope,owner));
        CREATE TABLE IF NOT EXISTS user_profiles(
            scope TEXT,owner TEXT,interaction_count INTEGER NOT NULL,active_days INTEGER NOT NULL,
            first_seen REAL NOT NULL,last_seen REAL NOT NULL,memory_enabled INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(scope,owner));
        CREATE TABLE IF NOT EXISTS user_profile_days(
            scope TEXT,owner TEXT,active_date TEXT,PRIMARY KEY(scope,owner,active_date));
        CREATE TABLE IF NOT EXISTS user_memories(
            id TEXT PRIMARY KEY,scope TEXT,owner TEXT,type TEXT NOT NULL,content TEXT NOT NULL,
            confidence REAL NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            last_used_at REAL,status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory_candidates(
            id TEXT PRIMARY KEY,scope TEXT,owner TEXT,type TEXT NOT NULL,content TEXT NOT NULL,
            confidence REAL NOT NULL,created_at REAL NOT NULL,status TEXT NOT NULL,memory_id TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS memory_candidate_content
            ON memory_candidates(scope,owner,type,content);
        CREATE INDEX IF NOT EXISTS memory_lookup
            ON user_memories(scope,owner,status,updated_at DESC);
        ''')
        # Do not rerun paid work or resend an uncertain delivery after a crash.
        with self.db:
            self.db.execute("UPDATE jobs SET status='interrupted',error='服务重启，未自动重跑' WHERE status='processing'")
            self.db.execute("UPDATE jobs SET status='unknown',error='服务重启，投递结果待确认' WHERE status='sending'")
    def get(self,scope,key,default=None):
        with self.lock:
            row=self.db.execute('SELECT value FROM settings WHERE scope=? AND key=?',(scope,key)).fetchone()
            return json.loads(row[0]) if row else default
    def set(self,scope,key,value):
        with self.lock,self.db:self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?,?)',(scope,key,json.dumps(value,ensure_ascii=False)))
    def accept(self,event,limits):
        now=time.time()
        with self.lock,self.db:
            if self.db.execute('SELECT 1 FROM jobs WHERE event_key=?',(event['key'],)).fetchone():return None
            event=dict(event)
            file_keys=[]
            if event.get('files'):
                remaining=[]
                for f in event['files']:
                    key=event['scope']+':'+event['owner']+':'+f['id']
                    if not self.db.execute('SELECT 1 FROM upload_claims WHERE file_key=?',(key,)).fetchone():
                        remaining.append(f);file_keys.append(key)
                if not remaining:return None
                event['files']=remaining
            active=self.db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','processing','sending')").fetchone()[0]
            mine=self.db.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','processing','sending')",(event['owner'],)).fetchone()[0]
            recent=self.db.execute('SELECT max(created),count(*) FROM jobs WHERE owner=? AND created>?',(event['owner'],now-86400)).fetchone()
            if active>=limits['max_pending'] or mine>=limits['max_pending_per_user']:raise Busy('队列已满')
            if recent[0] and now-recent[0]<limits['cooldown_seconds']:raise Busy('请求过快')
            if recent[1]>=limits['daily_requests_per_user']:raise Busy('每日额度已用完')
            ident=uuid.uuid4().hex[:12]
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(ident,event['key'],event['scope'],event['owner'],json.dumps(event,ensure_ascii=False),'queued',now,None,None))
            for key in file_keys:self.db.execute('INSERT INTO upload_claims VALUES(?,?)',(key,ident))
            return ident
    def take(self):
        with self.lock,self.db:
            row=self.db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:self.db.execute("UPDATE jobs SET status='processing' WHERE id=?",(row['id'],))
            return dict(row) if row else None
    def update(self,ident,status,output=None,error=None):
        with self.lock,self.db:
            self.db.execute('UPDATE jobs SET status=?,output=coalesce(?,output),error=? WHERE id=?',(status,json.dumps(output,ensure_ascii=False) if output is not None else None,error,ident))
    def receipt(self,ident,idx,status,receipt=None):
        with self.lock,self.db:self.db.execute('INSERT OR REPLACE INTO delivery VALUES(?,?,?,?)',(ident,idx,status,json.dumps(receipt,ensure_ascii=False)))
    def counts(self):
        with self.lock:return dict(self.db.execute('SELECT status,count(*) FROM jobs GROUP BY status').fetchall())
    def job(self,ident):
        with self.lock:
            row=self.db.execute('SELECT * FROM jobs WHERE id=?',(ident,)).fetchone()
            return dict(row) if row else None
    def receipts(self,ident):
        with self.lock:return {r['idx']:r['status'] for r in self.db.execute('SELECT * FROM delivery WHERE job=?',(ident,))}
    def context(self,scope,owner):
        with self.lock:
            rows=self.db.execute('SELECT role,content FROM history WHERE scope=? AND owner=? ORDER BY created DESC LIMIT 12',(scope,owner)).fetchall()
            return [dict(r) for r in reversed(rows)]
    def remember(self,scope,owner,user,answer):
        with self.lock,self.db:
            now=time.time()
            for i,(role,content) in enumerate([('user',user),('assistant',answer)]):
                self.db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(scope,owner,role,content[:12000],now+i*.001))
            self.db.execute('DELETE FROM history WHERE rowid IN (SELECT rowid FROM history WHERE scope=? AND owner=? ORDER BY created DESC LIMIT -1 OFFSET 12)',(scope,owner))
    def reset(self,scope,owner):
        with self.lock,self.db:self.db.execute('DELETE FROM history WHERE scope=? AND owner=?',(scope,owner))
    def memory_profile(self,scope,owner):
        with self.lock:
            row=self.db.execute('SELECT * FROM user_profiles WHERE scope=? AND owner=?',(scope,owner)).fetchone()
            if not row:return None
            result=dict(row);result['memory_enabled']=bool(result['memory_enabled']);return result
    def record_memory_interaction(self,scope,owner,now=None,day=None):
        now=time.time() if now is None else float(now)
        day=day or time.strftime('%Y-%m-%d',time.localtime(now))
        with self.lock,self.db:
            row=self.db.execute('SELECT * FROM user_profiles WHERE scope=? AND owner=?',(scope,owner)).fetchone()
            if row is None:
                self.db.execute('INSERT INTO user_profiles VALUES(?,?,?,?,?,?,?)',(scope,owner,0,0,now,now,0))
                interaction_count=0;enabled=False
            else:
                interaction_count=int(row['interaction_count']);enabled=bool(row['memory_enabled'])
            self.db.execute('INSERT OR IGNORE INTO user_profile_days VALUES(?,?,?)',(scope,owner,day))
            active_days=self.db.execute('SELECT count(*) FROM user_profile_days WHERE scope=? AND owner=?',(scope,owner)).fetchone()[0]
            interaction_count+=1;enabled=enabled or (interaction_count>=10 and active_days>=3)
            self.db.execute('UPDATE user_profiles SET interaction_count=?,active_days=?,last_seen=?,memory_enabled=? WHERE scope=? AND owner=?',
                            (interaction_count,active_days,now,int(enabled),scope,owner))
        return self.memory_profile(scope,owner)
    def memory_stats(self,scope):
        with self.lock:
            profiles=self.db.execute('SELECT count(*) FROM user_profiles WHERE scope=?',(scope,)).fetchone()[0]
            enabled=self.db.execute('SELECT count(*) FROM user_profiles WHERE scope=? AND memory_enabled=1',(scope,)).fetchone()[0]
            memories=self.db.execute("SELECT count(*) FROM user_memories WHERE scope=? AND status='active'",(scope,)).fetchone()[0]
            candidates=self.db.execute('SELECT count(*) FROM memory_candidates WHERE scope=?',(scope,)).fetchone()[0]
        return {'profiles':profiles,'enabled':enabled,'memories':memories,'candidates':candidates}
    def list_memories(self,scope,owner,status='active',limit=100):
        limit=max(1,min(int(limit),200))
        with self.lock:
            rows=self.db.execute('SELECT * FROM user_memories WHERE scope=? AND owner=? AND status=? ORDER BY updated_at DESC LIMIT ?',
                                 (scope,owner,status,limit)).fetchall()
            return [dict(row) for row in rows]
    def add_memory_candidate(self,scope,owner,candidate,now=None):
        now=time.time() if now is None else float(now)
        with self.lock,self.db:
            row=self.db.execute('SELECT id FROM memory_candidates WHERE scope=? AND owner=? AND type=? AND content=?',
                                (scope,owner,candidate['type'],candidate['content'])).fetchone()
            if row:return row['id']
            ident=uuid.uuid4().hex
            self.db.execute('INSERT INTO memory_candidates VALUES(?,?,?,?,?,?,?,?,?)',
                            (ident,scope,owner,candidate['type'],candidate['content'],candidate['confidence'],now,'pending',None))
            return ident
    def mark_memory_candidate(self,ident,status,memory_id=None):
        with self.lock,self.db:self.db.execute('UPDATE memory_candidates SET status=?,memory_id=? WHERE id=?',(status,memory_id,ident))
    def add_memory(self,scope,owner,candidate,now=None):
        now=time.time() if now is None else float(now);ident=uuid.uuid4().hex
        with self.lock,self.db:
            self.db.execute('INSERT INTO user_memories VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (ident,scope,owner,candidate['type'],candidate['content'],candidate['confidence'],now,now,None,'active'))
        return ident
    def update_memory(self,ident,content,confidence,now=None):
        now=time.time() if now is None else float(now)
        with self.lock,self.db:
            self.db.execute('UPDATE user_memories SET content=?,confidence=?,updated_at=? WHERE id=?',
                            (content,float(confidence),now,ident))
    def touch_memories(self,idents,now=None):
        if not idents:return
        now=time.time() if now is None else float(now)
        marks=','.join('?' for _ in idents)
        with self.lock,self.db:self.db.execute('UPDATE user_memories SET last_used_at=? WHERE id IN ('+marks+')',(now,*idents))
    def set_file(self,scope,owner,path,name):
        with self.lock,self.db:self.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)',(scope,owner,str(path),name,time.time()))
    def file(self,scope,owner):
        with self.lock:
            row=self.db.execute('SELECT * FROM files WHERE scope=? AND owner=?',(scope,owner)).fetchone()
            return dict(row) if row else None
    def prune(self,hours=24):
        cutoff=time.time()-hours*3600
        with self.lock,self.db:
            self.db.execute("DELETE FROM upload_claims WHERE job IN (SELECT id FROM jobs WHERE created<? AND status NOT IN ('queued','processing','sending'))",(cutoff,))
            self.db.execute("DELETE FROM delivery WHERE job IN (SELECT id FROM jobs WHERE created<? AND status NOT IN ('queued','processing','sending'))",(cutoff,))
            self.db.execute("DELETE FROM jobs WHERE created<? AND status NOT IN ('queued','processing','sending')",(cutoff,))
            self.db.execute('DELETE FROM history WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM files WHERE created<?',(cutoff,))
