import json
import sqlite3
import threading
import time
import uuid
from sqlite_runtime import Connection
from task_dispatch import classify

class Busy(ValueError):pass

class Store:
    def __init__(self,path):
        self.lock=threading.RLock();self.metrics=None;self.recovered_counts={}
        self.db=sqlite3.connect(str(path),check_same_thread=False,timeout=.2,factory=Connection)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,event_key TEXT UNIQUE,scope TEXT,owner TEXT,payload TEXT,status TEXT,created REAL,output TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS job_dispatch(job TEXT PRIMARY KEY,kind TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_order ON jobs(scope,owner,status,created);
        CREATE TABLE IF NOT EXISTS upload_claims(file_key TEXT PRIMARY KEY,job TEXT);
        CREATE TABLE IF NOT EXISTS video_claims(scope TEXT NOT NULL,video_key TEXT NOT NULL,
            job TEXT NOT NULL,claimed REAL NOT NULL,PRIMARY KEY(scope,video_key));
        CREATE TABLE IF NOT EXISTS quote_cards(id TEXT PRIMARY KEY,scope TEXT NOT NULL,subject TEXT NOT NULL,
            source_id TEXT NOT NULL,content TEXT NOT NULL,image_path TEXT NOT NULL,created_by TEXT NOT NULL,
            source_time REAL NOT NULL,created REAL NOT NULL,UNIQUE(scope,source_id));
        CREATE INDEX IF NOT EXISTS quote_lookup ON quote_cards(scope,subject,created DESC);
        CREATE TABLE IF NOT EXISTS quote_optouts(scope TEXT NOT NULL,subject TEXT NOT NULL,
            PRIMARY KEY(scope,subject));
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
        CREATE TABLE IF NOT EXISTS share_observed(id TEXT PRIMARY KEY,scope TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS share_lines(id TEXT PRIMARY KEY,scope TEXT NOT NULL,day TEXT NOT NULL,
            speaker TEXT NOT NULL,text TEXT NOT NULL,created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS share_lines_recent ON share_lines(scope,day,created DESC);
        CREATE TABLE IF NOT EXISTS share_notes(scope TEXT NOT NULL,kind TEXT NOT NULL,subject TEXT NOT NULL,
            content TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(scope,kind,subject));
        CREATE TABLE IF NOT EXISTS share_digests(scope TEXT NOT NULL,day TEXT NOT NULL,
            digest TEXT NOT NULL,facts TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(scope,day));
        CREATE TABLE IF NOT EXISTS share_affinity(owner TEXT PRIMARY KEY,score REAL NOT NULL,
            day TEXT NOT NULL,gain REAL NOT NULL,last REAL NOT NULL,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS share_usage(scope TEXT NOT NULL,owner TEXT NOT NULL,kind TEXT NOT NULL,
            day TEXT NOT NULL,count INTEGER NOT NULL,last REAL NOT NULL,PRIMARY KEY(scope,owner,kind));
        ''')
        with self.lock,self.db:
            for row in self.db.execute('SELECT id,payload FROM jobs WHERE id NOT IN (SELECT job FROM job_dispatch)').fetchall():
                try:kind=classify(json.loads(row['payload']))
                except (ValueError,TypeError,AttributeError):kind='tool'
                self.db.execute('INSERT INTO job_dispatch VALUES(?,?)',(row['id'],kind))
        # Do not rerun paid work or resend an uncertain delivery after a crash.
        with self.db:
            self.recovered_counts['jobs_interrupted']=self.db.execute("UPDATE jobs SET status='interrupted',error='服务重启，未自动重跑' WHERE status='processing'").rowcount
            self.recovered_counts['delivery_unknown']=self.db.execute("UPDATE jobs SET status='unknown',error='服务重启，投递结果待确认' WHERE status='sending'").rowcount
    def get(self,scope,key,default=None):
        with self.lock:
            row=self.db.execute('SELECT value FROM settings WHERE scope=? AND key=?',(scope,key)).fetchone()
            return json.loads(row[0]) if row else default
    def set(self,scope,key,value):
        with self.lock,self.db:self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?,?)',(scope,key,json.dumps(value,ensure_ascii=False)))
    def quote_by_source(self,scope,source_id):
        with self.lock:return self.db.execute('SELECT id FROM quote_cards WHERE scope=? AND source_id=?',
                                              (scope,source_id)).fetchone()
    def add_quote(self,ident,scope,subject,source_id,content,image_path,created_by,source_time):
        with self.lock,self.db:
            if self.db.execute('SELECT 1 FROM quote_optouts WHERE scope=? AND subject=?',(scope,subject)).fetchone():
                return 'optout'
            if self.db.execute('SELECT 1 FROM quote_cards WHERE scope=? AND source_id=?',(scope,source_id)).fetchone():
                return 'exists'
            count=self.db.execute('SELECT count(*) FROM quote_cards WHERE scope=? AND subject=?',(scope,subject)).fetchone()[0]
            total=self.db.execute('SELECT count(*) FROM quote_cards WHERE scope=?',(scope,)).fetchone()[0]
            if count>=50 or total>=500:return 'limit'
            try:self.db.execute('INSERT INTO quote_cards VALUES(?,?,?,?,?,?,?,?,?)',
                (ident,scope,subject,source_id,content,image_path,created_by,float(source_time),time.time()))
            except sqlite3.IntegrityError:return 'exists'
            return 'added'
    def random_quote(self,scope,subject):
        import secrets
        with self.lock:
            count=self.db.execute('SELECT count(*) FROM quote_cards WHERE scope=? AND subject=?',(scope,subject)).fetchone()[0]
            if not count:return None,0
            row=self.db.execute('SELECT * FROM quote_cards WHERE scope=? AND subject=? ORDER BY created DESC LIMIT 1 OFFSET ?',
                                (scope,subject,secrets.randbelow(count))).fetchone()
            return dict(row),count
    def quote_exists(self,scope,ident):
        with self.lock:return bool(self.db.execute('SELECT 1 FROM quote_cards WHERE scope=? AND id=?',
                                                   (scope,ident)).fetchone())
    def delete_quote(self,scope,ident,requester,admin=False):
        with self.lock,self.db:
            row=self.db.execute('SELECT image_path,subject FROM quote_cards WHERE scope=? AND id=?',(scope,ident)).fetchone()
            if not row or (not admin and row['subject']!=requester):return None
            self.db.execute('DELETE FROM quote_cards WHERE scope=? AND id=?',(scope,ident))
            return row['image_path']
    def set_quote_optout(self,scope,subject,disabled):
        with self.lock,self.db:
            if not disabled:
                self.db.execute('DELETE FROM quote_optouts WHERE scope=? AND subject=?',(scope,subject))
                return []
            self.db.execute('INSERT OR IGNORE INTO quote_optouts VALUES(?,?)',(scope,subject))
            paths=[row[0] for row in self.db.execute('SELECT image_path FROM quote_cards WHERE scope=? AND subject=?',
                                                     (scope,subject)).fetchall()]
            self.db.execute('DELETE FROM quote_cards WHERE scope=? AND subject=?',(scope,subject))
            return paths
    def claim_video(self,scope,video_key,job,now=None,ttl=600):
        now=time.time() if now is None else float(now)
        with self.lock,self.db:
            row=self.db.execute('''SELECT v.job,v.claimed,j.status FROM video_claims v
                LEFT JOIN jobs j ON j.id=v.job WHERE v.scope=? AND v.video_key=?''',(scope,video_key)).fetchone()
            if row and row['job']==job:return True
            if row and (row['claimed']>now-ttl or row['status'] in ('queued','processing','sending')):return False
            self.db.execute('INSERT OR REPLACE INTO video_claims VALUES(?,?,?,?)',(scope,video_key,job,now))
            return True
    def release_video(self,job):
        with self.lock,self.db:self.db.execute('DELETE FROM video_claims WHERE job=?',(job,))
    def video_sent(self,job):
        with self.lock,self.db:self.db.execute('UPDATE video_claims SET claimed=? WHERE job=?',(time.time(),job))
    def accept(self,event,limits,initial_status='queued'):
        if initial_status not in ('queued','processing'):raise ValueError('invalid initial status')
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
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(ident,event['key'],event['scope'],event['owner'],json.dumps(event,ensure_ascii=False),initial_status,now,None,None))
            self.db.execute('INSERT INTO job_dispatch VALUES(?,?)',(ident,classify(event)))
            for key in file_keys:self.db.execute('INSERT INTO upload_claims VALUES(?,?)',(key,ident))
        if self.metrics:
            self.metrics.emit('jobs_total')
            if not event.get('social'):self.metrics.emit('messages_total')
        return ident
    def take(self,kind=None):
        with self.lock,self.db:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            params=() if kind is None else (kind,)
            filter_kind='' if kind is None else ' AND d.kind=?'
            row=self.db.execute("""SELECT j.* FROM jobs j JOIN job_dispatch d ON d.job=j.id
                WHERE j.status='queued'"""+filter_kind+""" AND NOT EXISTS(
                    SELECT 1 FROM jobs prev WHERE prev.scope=j.scope AND prev.owner=j.owner
                    AND prev.status IN ('queued','processing','sending')
                    AND (prev.created<j.created OR (prev.created=j.created AND prev.rowid<j.rowid)))
                ORDER BY j.created,j.rowid LIMIT 1""",params).fetchone()
            if row:self.db.execute("UPDATE jobs SET status='processing' WHERE id=? AND status='queued'",(row['id'],))
            return dict(row) if row else None
    def can_deliver(self,ident):
        with self.lock:
            row=self.db.execute("""SELECT 1 FROM jobs j JOIN job_dispatch d ON d.job=j.id
                WHERE j.id=? AND d.kind='chat' AND EXISTS(
                    SELECT 1 FROM jobs prev JOIN job_dispatch pd ON pd.job=prev.id
                    WHERE prev.scope=j.scope AND pd.kind='chat' AND prev.status IN ('processing','sending')
                    AND (prev.created<j.created OR (prev.created=j.created AND prev.rowid<j.rowid)))""",(ident,)).fetchone()
            return row is None
    def scope_busy(self,scope):
        with self.lock:
            return bool(self.db.execute("SELECT 1 FROM jobs WHERE scope=? AND status IN ('queued','processing','sending') LIMIT 1",(scope,)).fetchone())
    def update(self,ident,status,output=None,error=None):
        with self.lock,self.db:
            old=self.db.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()
            self.db.execute('UPDATE jobs SET status=?,output=coalesce(?,output),error=? WHERE id=?',(status,json.dumps(output,ensure_ascii=False) if output is not None else None,error,ident))
        metric={'done':'jobs_done','failed':'jobs_failed','interrupted':'jobs_interrupted','unknown':'delivery_unknown'}.get(status)
        if self.metrics and old and old[0]!=status and metric:self.metrics.emit(metric)
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
            self.db.execute("""DELETE FROM video_claims WHERE claimed<? AND NOT EXISTS(
                SELECT 1 FROM jobs WHERE id=video_claims.job AND status IN ('queued','processing','sending'))""",
                (time.time()-600,))
            self.db.execute("DELETE FROM upload_claims WHERE job IN (SELECT id FROM jobs WHERE created<? AND status NOT IN ('queued','processing','sending'))",(cutoff,))
            self.db.execute("DELETE FROM delivery WHERE job IN (SELECT id FROM jobs WHERE created<? AND status NOT IN ('queued','processing','sending'))",(cutoff,))
            self.db.execute("DELETE FROM job_dispatch WHERE job IN (SELECT id FROM jobs WHERE created<? AND status NOT IN ('queued','processing','sending'))",(cutoff,))
            self.db.execute("DELETE FROM jobs WHERE created<? AND status NOT IN ('queued','processing','sending')",(cutoff,))
            self.db.execute('DELETE FROM history WHERE created<?',(cutoff,))
            self.db.execute('DELETE FROM files WHERE created<?',(cutoff,))
