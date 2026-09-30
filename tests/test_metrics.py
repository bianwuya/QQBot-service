from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock,patch
from test_bot import Fixture
from metrics import Metrics,offline,total
from model_router import ModelFailure
from social_engine import SocialEngine
from tooling.broker import CallContext
import persona


class MetricsTests(Fixture):
    def setUp(self):
        super().setUp();self.m=self.bot.metrics

    def value(self,key):return total(self.m.report(),key)

    def test_message_and_job_counts_no_duplicate(self):
        e=self.e(text='正文不应该进指标')
        ident=self.bot.store.accept(e,self.cfg['limits'])
        self.assertIsNone(self.bot.store.accept(e,self.cfg['limits']))
        self.assertEqual(self.value('messages_total'),1)
        self.assertEqual(self.value('jobs_total'),1)
        self.bot.store.update(ident,'failed');self.bot.store.update(ident,'failed')
        self.assertEqual(self.value('jobs_failed'),1)

    def test_model_failures_and_latency(self):
        self.bot.llm.chat.side_effect=ModelFailure('http_503')
        with self.assertRaises(ModelFailure):self.bot.chat_model('g:33333',[])
        self.assertEqual(self.value('model_requests'),1)
        self.assertEqual(self.value('model_failures'),1)
        self.assertIn('model_latency',self.m.report()['metrics'])

    def test_model_switch_is_counted(self):
        self.cfg.update(model_pool=['test-model','backup'],failure_threshold=1)
        def invoke(model,*a,**kw):
            if model=='test-model':raise ModelFailure('http_503')
            return 'ok'
        self.bot.llm.chat.side_effect=invoke
        self.assertEqual(self.bot.chat_model('g:33333',[],owner='22222'),'ok')
        self.assertEqual(self.value('model_switches'),1)
        self.assertEqual(self.value('model_requests'),2)

    def test_persona_usage_ooc_retry_and_fallback(self):
        self.bot.llm.chat.side_effect=['作为AI，我不能回答。','我是语言模型。']
        self.bot.process(self.e(text='普通问题'),'persona')
        self.assertEqual(self.value('role_usage'),1)
        self.assertEqual(self.value('retry_count'),1)
        self.assertGreaterEqual(self.value('ooc_hits'),1)
        self.assertEqual(self.value('fallback_count'),1)

    def test_social_attempt_sent_reply_and_suppression(self):
        now=[datetime(2026,9,22,12).timestamp()]
        engine=SocialEngine(self.bot.store,clock=lambda:now[0],rng=lambda:0)
        self.bot.social=engine;scope='g:33333';engine.set_enabled(scope,True)
        for i in range(4):engine.observe(self.e(user='22222' if i%2 else '44444',mid=i+10))
        c=engine.choose(scope,persona.role_for(self.bot.store,scope))
        self.bot.connected=self.bot.online=True;self.bot.self_id='99999';self.bot.ob.send.return_value={'message_id':1}
        self.bot.social_attempt(c)
        self.assertEqual(self.value('proactive_attempts'),1);self.assertEqual(self.value('proactive_sent'),1)
        now[0]+=1;engine.observe(self.e(mid=55))
        self.assertEqual(self.value('proactive_replied'),1)
        state=engine.state(scope);state['count']=6;self.bot.store.set(scope,'social_budget',state)
        for _ in range(3):engine.choose(scope,persona.role_for(self.bot.store,scope))
        self.assertEqual(self.value('daily_suppressed'),1)

    def test_tool_counts_and_no_result_content(self):
        self.bot.tool_broker.invoke(CallContext('g:33333','22222'),'get_time',{})
        self.bot.tool_broker.invoke(CallContext('g:33333','22222'),'unknown',{})
        self.assertEqual(self.value('tool_calls'),2)
        self.assertEqual(self.value('tool_success'),1)
        self.assertEqual(self.value('tool_failure'),1)

    def test_worker_latency_from_real_job_boundary(self):
        ident=self.bot.store.accept(self.e(),self.cfg['limits']);job=self.bot.store.take('chat')
        self.bot.ob.send.return_value={'message_id':1};self.bot.run_job(job)
        row=self.m.report()['metrics']['worker_latency']['chat']
        self.assertEqual(row['samples'],1);self.assertGreaterEqual(row['average'],0)
        self.assertEqual(self.value('jobs_done'),1)

    def test_status_admin_only_and_bounded(self):
        denied=self.bot.process(self.e(text='/状态',role='admin'),'deny')[0]['text']
        self.assertIn('指定管理员',denied);self.assertNotIn('今日消息',denied)
        text=self.bot.process(self.e(user='11111',text='/状态'),'status')[0]['text']
        self.assertIn('今日消息',text);self.assertIn('平均耗时',text);self.assertLessEqual(len(text),1350)

    def test_no_bodies_tokens_passwords_qq_or_raw_labels_in_metrics(self):
        secret='TOKEN_PASSWORD_PROMPT_SECRET_918273645'
        e=self.e(user='12345678901234567890',text=secret)
        self.bot.store.accept(e,self.cfg['limits']);self.bot.llm.chat.return_value=secret
        self.bot.process(e,'privacy')
        self.m.emit('model_requests',self.m.label('model',secret))
        rows=json.dumps([tuple(r) for r in self.bot.store.db.execute('SELECT * FROM metrics_daily')])
        for value in (secret,'12345678901234567890','g:33333','test-model'):
            self.assertNotIn(value,rows)
        with self.assertRaises(ValueError):self.m.record('messages_total','p:22222')
        with self.assertRaises(ValueError):self.m.record(secret)

    def test_cross_day_1_7_30_windows(self):
        now=[datetime(2026,9,1,12).timestamp()];self.m.clock=lambda:now[0]
        self.m.record('messages_total');now[0]+=86400*6;self.m.record('messages_total')
        self.assertEqual(total(self.m.report(1),'messages_total'),1)
        self.assertEqual(total(self.m.report(7),'messages_total'),2)
        now[0]+=86400
        self.assertEqual(total(self.m.report(7),'messages_total'),1)
        self.assertEqual(total(self.m.report(30),'messages_total'),2)

    def test_offline_readonly_preserves_processing_job(self):
        ident=self.bot.store.accept(self.e(),self.cfg['limits']);self.bot.store.take()
        self.assertEqual(total(offline(self.root/'state/bot.sqlite3'),'messages_total'),1)
        self.assertEqual(self.bot.store.job(ident)['status'],'processing')
        script=Path(__file__).resolve().parents[1]/'tools/report-metrics.py'
        result=subprocess.run([sys.executable,'-X','utf8',str(script),'--db',str(self.root/'state/bot.sqlite3'),'--days','7','--json'],capture_output=True,text=True,encoding='utf-8',timeout=5)
        self.assertEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout)['days'],7)
        self.assertEqual(self.bot.store.job(ident)['status'],'processing')

    def test_empty_old_database_offline_no_migration(self):
        path=self.root/'legacy.sqlite';db=sqlite3.connect(path);db.execute('CREATE TABLE sentinel(x)');db.close()
        self.assertEqual(offline(path)['metrics'],{})
        db=sqlite3.connect(path)
        self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='metrics_daily'").fetchone()[0],0);db.close()

    def test_metrics_failure_does_not_retry_paid_work(self):
        with patch.object(self.m,'record',side_effect=sqlite3.OperationalError('locked')):
            self.assertEqual(self.bot.chat_model('g:33333',[]),'测试回答')
        self.bot.llm.chat.assert_called_once();self.assertGreater(self.m.dropped,0)

    def test_alerts_detect_unknown_model_and_media_stall(self):
        self.m.record('delivery_unknown');self.assertEqual(self.m.alerts()['level'],'WARN')
        self.m.record('delivery_unknown',value=2);self.assertEqual(self.m.alerts()['level'],'CRITICAL')
        self.assertIn('model_cooldown',self.m.alerts(states=['COOLDOWN'])['reasons'])
        clock=[100.];self.m.monotonic=lambda:clock[0];self.m.begin_job('fake','media');clock[0]+=601
        self.assertIn('media_stalled',self.m.alerts()['reasons']);self.m.end_job('fake')

    def test_aggregates_bounded_rows_and_thread_safe(self):
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:self.m.record('messages_total'),range(80)))
        self.assertEqual(self.value('messages_total'),80)
        self.assertEqual(self.bot.store.db.execute('SELECT count(*) FROM metrics_daily').fetchone()[0],1)

    def test_retention_does_not_delete_knowledge_or_memory(self):
        self.bot.knowledge.add('g:33333','group:33333','rules','群规不能刷屏')
        now=[datetime(2026,1,1,12).timestamp()];self.m.clock=lambda:now[0];self.m.record('messages_total')
        now[0]+=100*86400;self.m.prune()
        self.assertEqual(self.bot.store.db.execute('SELECT count(*) FROM metrics_daily').fetchone()[0],0)
        self.assertEqual(len(self.bot.knowledge.list('g:33333')),1)
