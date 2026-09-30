import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from test_bot import Fixture,LIMITS,CFG
from store import Store,Busy
from protocol import DeliveryUnknown,OneBot
from task_dispatch import classify,worker_counts,LockPool


class ConcurrencyTests(Fixture):
    def setUp(self):
        super().setUp();self.threads=[];self.releases=[]
        self.bot.ob.send.return_value={'message_id':1}

    def tearDown(self):
        for release in self.releases:release.set()
        self.bot.stop.set()
        for t in self.threads:t.join(4)
        self.assertFalse(any(t.is_alive() for t in self.threads))
        super().tearDown()

    def enqueue(self,text='hello',user='22222',mid=1,**kwargs):
        e=self.e(text=text,user=user,mid=mid)
        e.update(kwargs)
        return self.bot.store.accept(e,self.cfg['limits'])

    def worker(self,kind):
        t=threading.Thread(target=self.bot.worker,args=(kind,),daemon=True);self.threads.append(t);t.start()

    def gate(self):
        event=threading.Event();self.releases.append(event);return event

    def test_task_classification_and_conservative_counts(self):
        for event,expected in [({'text':'hey'},'chat'),({'files':[1]},'file'),({'videos':[1]},'media'),
                               ({'text':'/应用 确认 x'},'tool'),({'text':'/知识库 导入'},'file'),({'text':'/下载 https://x'},'file')]:
            self.assertEqual(classify(event),expected)
        self.assertEqual(worker_counts(),{'chat':2,'file':1,'media':1,'tool':1,'quote':2})
        self.assertEqual(worker_counts({'media':99,'chat':99})['media'],1)
        self.assertEqual(worker_counts({'chat':99})['chat'],4)

    def test_long_media_does_not_block_other_user_chat(self):
        entered=threading.Event();done=threading.Event();release=self.gate()
        def process(e,ident):
            if e['videos']:entered.set();release.wait(3)
            else:done.set()
            return [{'kind':'text','text':e['text']}]
        self.bot.process=process
        self.enqueue('video',videos=['test']);self.enqueue('chat',user='44444',mid=2)
        self.worker('media');self.assertTrue(entered.wait(2));self.worker('chat')
        self.assertTrue(done.wait(2));self.assertFalse(release.is_set())

    def test_long_tool_does_not_block_chat(self):
        entered=threading.Event();done=threading.Event();release=self.gate()
        def process(e,ident):
            if e['text'].startswith('/'):entered.set();release.wait(3)
            else:done.set()
            return []
        self.bot.process=process
        self.enqueue('/应用 状态 napcat');self.enqueue('chat',user='44444',mid=2)
        self.worker('tool');self.assertTrue(entered.wait(2));self.worker('chat');self.assertTrue(done.wait(2))

    def test_same_owner_fifo_across_two_chat_workers(self):
        first=threading.Event();second=threading.Event();release=self.gate();order=[]
        def process(e,ident):
            order.append(e['text'])
            if e['text']=='one':first.set();release.wait(3)
            else:second.set()
            return []
        self.bot.process=process
        self.enqueue('one',mid=1);self.enqueue('two',mid=2)
        self.worker('chat');self.worker('chat');self.assertTrue(first.wait(2))
        self.assertFalse(second.wait(.35));release.set();self.assertTrue(second.wait(2));self.assertEqual(order,['one','two'])

    def test_different_users_generate_parallel_but_deliver_in_order(self):
        first=threading.Event();second=threading.Event();release=self.gate();sent=[];delivered=threading.Event()
        def process(e,ident):
            if e['text']=='one':first.set();release.wait(3)
            else:second.set()
            return [{'kind':'text','text':e['text']}]
        def send(scope,parts):
            sent.append(parts[0]['data']['text'])
            if len(sent)==2:delivered.set()
            return {'message_id':1}
        self.bot.process=process;self.bot.ob.send.side_effect=send
        self.enqueue('one');self.enqueue('two',user='44444',mid=2)
        self.worker('chat');self.worker('chat')
        self.assertTrue(first.wait(2));self.assertTrue(second.wait(2));self.assertEqual(sent,[])
        release.set();self.assertTrue(delivered.wait(2));self.assertEqual(sent,['one','two'])

    def test_queued_chat_behind_video_does_not_block_another_chat_delivery(self):
        self.enqueue('video',videos=['test']);self.enqueue('waiting',mid=2)
        other=self.enqueue('other',user='44444',mid=3)
        self.bot.store.take('media')
        self.assertEqual(self.bot.store.take('chat')['id'],other)
        self.assertTrue(self.bot.store.can_deliver(other))

    def test_atomic_claim_no_duplicate_paid_work(self):
        ident=self.enqueue()
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs=list(pool.map(lambda _:self.bot.store.take('chat'),range(8)))
        self.assertEqual([j['id'] for j in jobs if j],[ident])

    def test_multi_element_deliveries_do_not_interleave(self):
        first=self.enqueue('one');second=self.enqueue('two',user='44444',mid=2);sent=[]
        def send(scope,parts):
            sent.append(parts[0]['data']['text']);time.sleep(.01);return {'message_id':1}
        self.bot.ob.send.side_effect=send
        def deliver(args):
            ident,prefix=args
            self.bot.deliver(self.e(),ident,[{'kind':'text','text':prefix+'1'},{'kind':'text','text':prefix+'2'}])
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(deliver,[(first,'a'),(second,'b')]))
        self.assertIn(sent,[['a1','a2','b1','b2'],['b1','b2','a1','a2']])

    def test_sqlite_busy_recovers_without_model_retry(self):
        other=sqlite3.connect(self.root/'state/bot.sqlite3',check_same_thread=False)
        other.execute('BEGIN IMMEDIATE')
        timer=threading.Timer(.35,other.rollback);timer.start()
        try:self.bot.store.set('g:33333','busy_test',True)
        finally:timer.join(2);other.close()
        self.assertTrue(self.bot.store.get('g:33333','busy_test'));self.bot.llm.chat.assert_not_called()

    def test_worker_crash_retains_processing_then_restart_interrupts(self):
        ident=self.enqueue();job=self.bot.store.take('chat')
        self.bot.process=Mock(side_effect=SystemExit('simulated crash'))
        with self.assertRaises(SystemExit):self.bot.run_job(job)
        self.assertEqual(self.bot.store.job(ident)['status'],'processing')
        other=Store(self.root/'state/bot.sqlite3')
        try:self.assertEqual(other.job(ident)['status'],'interrupted');self.assertIsNone(other.take('chat'))
        finally:other.db.close()

    def test_unknown_delivery_not_requeued(self):
        ident=self.enqueue();job=self.bot.store.take('chat')
        self.bot.process=Mock(return_value=[{'kind':'text','text':'answer'}])
        self.bot.ob.send.side_effect=DeliveryUnknown('test')
        self.bot.run_job(job)
        self.assertEqual(self.bot.store.job(ident)['status'],'unknown')
        self.assertEqual(self.bot.store.receipts(ident),{0:'unknown'})
        self.assertIsNone(self.bot.store.take('chat'))
        self.bot.process.assert_called_once()

    def test_global_and_owner_limits_survive_concurrent_accept(self):
        self.cfg['limits'].update(max_pending=2,max_pending_per_user=1)
        self.enqueue()
        with self.assertRaises(Busy):self.enqueue(mid=2)
        def accept(n):
            try:return self.enqueue(user=str(50000+n),mid=n+10)
            except Busy:return None
        with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(accept,range(5)))
        self.assertEqual(sum(bool(r) for r in results),1)
        self.assertEqual(self.bot.store.counts(),{'queued':2})

    def test_model_calls_bounded_to_two(self):
        release=self.gate();two=threading.Event();guard=threading.Lock();live=0;peak=0
        def chat(*a,**k):
            nonlocal live,peak
            with guard:
                live+=1;peak=max(peak,live)
                if live==2:two.set()
            release.wait(2)
            with guard:live-=1
            return 'ok'
        self.bot.llm.chat.side_effect=chat
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(self.bot.chat_model,'g:'+str(i),[]) for i in range(3)]
            self.assertTrue(two.wait(2));self.assertEqual(peak,2);release.set()
            self.assertEqual([f.result(2) for f in futures],['ok']*3)
        self.assertEqual(peak,2)

    def test_onebot_sessions_thread_local(self):
        ob=OneBot(CFG['onebot']);barrier=threading.Barrier(2)
        def session(_):
            value=ob.session;barrier.wait(2);return value
        with ThreadPoolExecutor(max_workers=2) as pool:sessions=list(pool.map(session,range(2)))
        self.assertIsNot(sessions[0],sessions[1])
        for session in sessions:session.close()

    def test_old_jobs_get_dispatch_backfill(self):
        path=self.root/'old.sqlite3';db=sqlite3.connect(path)
        db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,event_key TEXT UNIQUE,scope TEXT,owner TEXT,payload TEXT,status TEXT,created REAL,output TEXT,error TEXT)')
        event=dict(self.e(),videos=['test'])
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',('legacy','old','g:33333','22222',json.dumps(event),'queued',1,None,None))
        db.commit();db.close();store=Store(path)
        try:self.assertEqual(store.take('media')['id'],'legacy')
        finally:store.db.close()
