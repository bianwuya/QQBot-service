from unittest.mock import Mock,patch
import requests
from test_bot import Fixture
from model_router import ModelRouter,ModelFailure
from protocol import LLM,DeliveryUnknown
from safe_net import Rejected


class RouterTests(Fixture):
    def setUp(self):
        super().setUp()
        self.cfg.update(model_pool=['test-model','backup'],failure_threshold=2,cooldown_seconds=30,probe_interval=60,probe_success_threshold=2)
        self.now=1000.;self.r=ModelRouter(lambda:self.cfg,clock=lambda:self.now)
        self.bot.model_router=self.r

    def run_model(self,fn,scope='g:33333',owner='22222',primary='test-model'):
        return self.r.run(scope,owner,primary,fn)

    def failover(self):
        def invoke(model):
            if model=='test-model':raise ModelFailure('http_503')
            return 'backup answer'
        with self.assertRaises(ModelFailure):self.run_model(invoke)
        self.assertEqual(self.run_model(invoke),'backup answer')
        return invoke

    def test_healthy_no_switch_and_single_error_degraded(self):
        call=Mock(return_value='ok');self.assertEqual(self.run_model(call),'ok')
        call.assert_called_once_with('test-model')
        with self.assertRaises(ModelFailure):self.run_model(Mock(side_effect=ModelFailure('http_503')))
        self.assertEqual(self.r.health['test-model']['state'],'DEGRADED')

    def test_consecutive_503_then_sticky_backup(self):
        self.failover();call=Mock(return_value='sticky')
        self.assertEqual(self.run_model(call),'sticky');call.assert_called_once_with('backup')
        self.assertIn('http_503',self.r.status('g:33333','22222','test-model'))

    def test_connect_timeout_immediate_failover(self):
        def invoke(model):
            if model=='test-model':raise ModelFailure('connect_timeout')
            return 'ok'
        self.assertEqual(self.run_model(invoke),'ok')

    def test_business_prompt_and_delivery_errors_never_failover(self):
        for error in (Rejected('business'),DeliveryUnknown('delivery'),ModelFailure('response_unknown',False)):
            fn=Mock(side_effect=error)
            with self.assertRaises(type(error)):self.run_model(fn)
            fn.assert_called_once_with('test-model')
        self.assertEqual(self.r.health['test-model']['state'],'HEALTHY')

    def test_cooldown_probe_recovery_threshold(self):
        self.failover();probe=Mock(return_value='OK')
        self.assertFalse(self.r.probe_once(probe))
        self.now+=31
        self.assertTrue(self.r.probe_once(probe))
        self.assertEqual(self.r.health['test-model']['state'],'PROBING')
        self.assertFalse(self.r.probe_once(probe))
        call=Mock(return_value='backup');self.run_model(call);call.assert_called_once_with('backup')
        self.now+=61
        self.assertTrue(self.r.probe_once(probe))
        call=Mock(return_value='primary');self.run_model(call);call.assert_called_once_with('test-model')

    def test_failed_probe_returns_cooldown(self):
        self.failover();self.now+=31
        self.r.probe_once(Mock(side_effect=RuntimeError('no')))
        self.assertEqual(self.r.health['test-model']['state'],'COOLDOWN')

    def test_config_pool_change_and_manual_primary(self):
        self.failover();self.r.reset('g:33333')
        fn=Mock(return_value='manual')
        self.run_model(fn,primary='backup');fn.assert_called_once_with('backup')
        self.cfg['model_pool']=['new-backup'];fn.reset_mock()
        self.run_model(fn,primary='new-primary');fn.assert_called_once_with('new-primary')

    def test_old_config_is_exact_single_call_and_no_probe(self):
        del self.cfg['model_pool'];fn=Mock(side_effect=ModelFailure('http_503'))
        for _ in range(2):
            with self.assertRaises(ModelFailure):self.run_model(fn)
        self.assertEqual(fn.call_count,2)
        self.assertEqual(self.r.health,{})
        self.assertFalse(self.r.probe_once(Mock()))

    def test_no_retry_after_tool_execution(self):
        self.cfg['failure_threshold']=1
        fn=Mock(side_effect=ModelFailure('http_503'))
        with self.assertRaises(ModelFailure):self.r.run('g:1','2','test-model',fn,may_retry=lambda:False)
        fn.assert_called_once()

    def test_scope_owner_sticky_separate(self):
        self.failover()
        fn=Mock(return_value='other');self.run_model(fn,owner='44444',primary='backup')
        self.assertEqual(self.r.sticky[('g:33333','22222')]['primary'],'test-model')
        self.assertEqual(self.r.sticky[('g:33333','44444')]['primary'],'backup')

    def test_admin_switch_resets_sticky(self):
        self.failover()
        self.bot.process(self.e(user='11111',text='/模型 other-model'),'switch')
        self.assertEqual(self.r.sticky,{})

    def test_transport_classification(self):
        key=self.dir/'key';key.write_text('fake-key')
        cfg=dict(self.cfg['llm'],key_file=str(key))
        session=Mock();session.request.side_effect=requests.ConnectTimeout()
        with patch('protocol.requests.Session',return_value=session):
            with self.assertRaises(ModelFailure) as cm:LLM(cfg).request('/chat/completions',{})
        self.assertEqual(cm.exception.code,'connect_timeout')
        session.request.side_effect=requests.ReadTimeout()
        with patch('protocol.requests.Session',return_value=session):
            with self.assertRaises(ModelFailure) as cm:LLM(cfg).request('/chat/completions',{})
        self.assertFalse(cm.exception.failover)

    def test_http_503_vs_prompt_400(self):
        key=self.dir/'key';key.write_text('fake-key');cfg=dict(self.cfg['llm'],key_file=str(key))
        session=Mock();session.request.return_value.status_code=503
        with patch('protocol.requests.Session',return_value=session):
            with self.assertRaises(ModelFailure):LLM(cfg).request('/chat/completions',{})
        session.request.return_value.status_code=400
        session.request.return_value.iter_content.return_value=iter([b'{"error":{"code":"invalid_prompt"}}'])
        with patch('protocol.requests.Session',return_value=session):
            with self.assertRaises(Rejected) as cm:LLM(cfg).request('/chat/completions',{})
        self.assertNotIsInstance(cm.exception,ModelFailure)

    def test_connection_loss_is_unknown_not_safe_failover(self):
        key=self.dir/'key';key.write_text('fake-key');cfg=dict(self.cfg['llm'],key_file=str(key))
        session=Mock();session.request.side_effect=requests.ConnectionError('possibly paid')
        with patch('protocol.requests.Session',return_value=session):
            with self.assertRaises(ModelFailure) as cm:LLM(cfg).request('/chat/completions',{})
        self.assertEqual(cm.exception.code,'connection_unknown');self.assertFalse(cm.exception.failover)
        session.close.assert_called_once()

    def test_response_closed_even_on_upstream_failure(self):
        key=self.dir/'key';key.write_text('fake-key');cfg=dict(self.cfg['llm'],key_file=str(key))
        session=Mock();response=session.request.return_value;response.status_code=503
        with patch('protocol.requests.Session',return_value=session):
            with self.assertRaises(ModelFailure):LLM(cfg).request('/chat/completions',{})
        response.close.assert_called_once();session.close.assert_called_once()
