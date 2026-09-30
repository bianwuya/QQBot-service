import copy
import json
import subprocess
from unittest.mock import Mock,patch
from pathlib import Path
from test_bot import Fixture
from tooling.broker import CallContext
from app_executor import AppFailure,Executor,script_command


class AppControlTests(Fixture):
    def setUp(self):
        super().setUp()
        self.cfg.update(app_control_enabled=True,controlled_apps={'napcat':{
            'id':'napcat','display_name':'NapCat','allowed_actions':['start','stop','restart','status'],
            'allowed_scopes':['private'],'timeout':5,
            **{k+'_method':{'kind':'script','script':'F:/private/path/hidden.ps1'} for k in ['start','stop','restart','status']}}})
        self.ctx=CallContext('p:11111','11111')
        self.controller=self.bot.app_control
        self.controller.executor=Mock()
        self.controller.executor.execute.return_value={'state':'command_completed'}
        self.controller.executor.status.return_value={'online':True}
        self.now=1000.;self.controller.clock=lambda:self.now

    def request(self,app='napcat',action='restart',ctx=None):
        return self.bot.tool_broker.invoke(ctx or CallContext('p:11111','11111'),'control_app',{'app_id':app,'action':action})

    def ticket(self):
        result=self.request();self.assertTrue(result['ok']);return result['result']['confirm_id']

    def confirm(self,ticket,ctx=None):
        return self.bot.tool_broker.confirm_application(ctx or self.ctx,ticket,self.controller)

    def test_l2_requires_config_admin_and_enabled(self):
        self.assertFalse(self.request(ctx=CallContext('g:33333','22222'))['ok'])
        self.cfg['app_control_enabled']=False
        self.assertFalse(self.request()['ok'])
        self.controller.executor.execute.assert_not_called()

    def test_unknown_app_action_and_group_scope_denied(self):
        self.assertFalse(self.request(app='powershell')['ok'])
        self.assertFalse(self.request(action='delete')['ok'])
        self.assertFalse(self.request(ctx=CallContext('g:33333','11111'))['ok'])
        self.controller.executor.execute.assert_not_called()

    def test_ticket_then_once_execution(self):
        token=self.ticket();self.controller.executor.execute.assert_not_called()
        self.assertTrue(self.confirm(token)['ok'])
        self.assertFalse(self.confirm(token)['ok'])
        self.controller.executor.execute.assert_called_once()

    def test_ticket_owner_scope_and_expiry(self):
        token=self.ticket();self.cfg['admins'].append('22222')
        self.assertFalse(self.confirm(token,CallContext('p:22222','22222'))['ok'])
        self.assertFalse(self.confirm(token,CallContext('g:33333','11111'))['ok'])
        self.now+=121
        self.assertFalse(self.confirm(token)['ok'])
        self.controller.executor.execute.assert_not_called()

    def test_revocation_and_allowlist_change(self):
        token=self.ticket();self.cfg['admins']=[]
        self.assertFalse(self.confirm(token)['ok'])
        self.cfg['admins']=['11111']
        self.cfg['controlled_apps']['napcat']['stop_method']['script']='changed.ps1'
        self.assertEqual(self.confirm(token)['error'],'configuration_changed')
        self.controller.executor.execute.assert_not_called()

    def test_timeout_consumes_ticket_and_has_audit(self):
        token=self.ticket()
        self.controller.executor.execute.side_effect=AppFailure('timeout_unknown')
        result=self.confirm(token)
        self.assertEqual(result['error'],'timeout_unknown')
        self.assertFalse(result['retry_safe'])
        self.assertFalse(self.confirm(token)['ok'])
        codes=[r[0] for r in self.bot.store.db.execute('SELECT error_code FROM tool_audit')]
        self.assertIn('timeout_unknown',codes)

    def test_exception_sanitized_and_paths_never_exposed(self):
        token=self.ticket()
        self.controller.executor.execute.side_effect=RuntimeError('F:/private/path secret_token')
        result=self.confirm(token)
        self.assertNotIn('private',str(result))
        self.assertNotIn('secret_token',str(result))
        audit=str([tuple(r) for r in self.bot.store.db.execute('SELECT * FROM tool_audit')])
        self.assertNotIn('private',audit)
        self.assertNotIn(token,audit)

    def test_model_no_confirmation_tool_and_metadata_only(self):
        desc=self.bot.tool_broker.descriptors(self.ctx)
        self.assertIn('control_app',str(desc))
        self.assertNotIn('confirm_application',str(desc))
        self.assertNotIn('F:/private',str(desc))
        self.assertNotIn('F:/private',str(self.request()))

    def test_self_restart_audit_and_prepare_before_script(self):
        app=copy.deepcopy(self.cfg['controlled_apps']['napcat']);app['id']='qqbot'
        app['restart_method']['script']=str(self.root/'tools/restart-service.ps1')
        self.cfg['controlled_apps']['qqbot']=app
        events=[]
        def send(*a,**kw):
            codes=[r[0] for r in self.bot.store.db.execute('SELECT error_code FROM tool_audit')]
            self.assertIn('started',codes)
            events.append('prepare');return {'message_id':1}
        self.bot.ob.send.side_effect=send
        def execute(*a,**kw):
            self.assertTrue(kw['detach']);events.append('launch');return {'state':'scheduled'}
        self.controller.executor.execute.side_effect=execute
        token=self.request(app='qqbot')['result']['confirm_id']
        self.assertTrue(self.confirm(token)['ok'])
        self.assertEqual(events,['prepare','launch'])

    def test_self_restart_unknown_preparation_prevents_launch(self):
        app=copy.deepcopy(self.cfg['controlled_apps']['napcat']);app['id']='qqbot'
        app['restart_method']['script']=str(self.root/'tools/restart-service.ps1')
        self.cfg['controlled_apps']['qqbot']=app
        self.bot.ob.send.return_value={}
        token=self.request(app='qqbot')['result']['confirm_id']
        self.assertFalse(self.confirm(token)['ok'])
        self.controller.executor.execute.assert_not_called()

    def test_explicit_admin_command_uses_broker(self):
        out=self.bot.process(self.e(user='11111',group=None,text='/应用 重启 napcat'),'request')
        token=json.loads(out[0]['text'])['result']['confirm_id']
        out=self.bot.process(self.e(user='11111',group=None,text='/应用 确认 '+token),'confirm')
        self.assertTrue(json.loads(out[0]['text'])['ok'])
        out=self.bot.process(self.e(text='/应用 重启 napcat',role='admin'),'group-admin')
        self.assertIn('指定管理员',out[0]['text'])

    def test_executor_timeout_and_shell_false(self):
        app=self.cfg['controlled_apps']['napcat']
        with patch('app_executor.script_command',return_value=['fixed.exe','fixed.ps1']),patch('app_executor.subprocess.run',side_effect=subprocess.TimeoutExpired('fixed',1)) as run:
            with self.assertRaisesRegex(AppFailure,'timeout_unknown'):Executor().execute(app,'restart')
            self.assertFalse(run.call_args.kwargs['shell'])

    def test_script_method_disallows_model_command_and_relative_path(self):
        for method in ({'kind':'shell','command':'calc'},{'kind':'script','script':'relative.ps1'},{'kind':'script','script':'C:/cmd.exe'}):
            with self.assertRaises(AppFailure):script_command(method)

    def test_admin_revoked_while_waiting_for_restart_preparation(self):
        app=copy.deepcopy(self.cfg['controlled_apps']['napcat']);app['id']='qqbot'
        app['restart_method']['script']=str(self.root/'tools/restart-service.ps1')
        self.cfg['controlled_apps']['qqbot']=app
        def send(*args,**kwargs):
            self.cfg['admins']=[]
            return {'message_id':1}
        self.bot.ob.send.side_effect=send
        token=self.request(app='qqbot')['result']['confirm_id']
        self.assertFalse(self.confirm(token)['ok'])
        self.controller.executor.execute.assert_not_called()
