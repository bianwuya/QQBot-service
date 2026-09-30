"""One-shot administrator approvals; no confirmation operation exposed to LLM."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time
from app_executor import Executor, AppFailure


class AppController:
    def __init__(self, bot, executor=None, clock=time.time):
        self.bot=bot;self.store=bot.store;self.executor=executor or Executor();self.clock=clock
        self.lock=threading.RLock()
        with self.store.lock,self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS app_confirmations(
                ticket_hash TEXT PRIMARY KEY,owner_hash TEXT,scope TEXT,tool TEXT,args TEXT,
                config_hash TEXT,expires REAL,status TEXT)''')

    def _app(self, ctx, app_id, action):
        cfg=self.bot.config_loader()
        if ctx.owner not in cfg['admins']:raise AppFailure('permission_denied')
        if cfg.get('app_control_enabled') is not True:raise AppFailure('control_disabled')
        apps=cfg.get('controlled_apps',{})
        app=apps.get(app_id) if isinstance(apps,dict) else None
        if not isinstance(app,dict) or not re.fullmatch(r'[a-z0-9_-]{1,40}',app_id):raise AppFailure('app_not_allowed')
        if app.get('id')!=app_id or action not in app.get('allowed_actions',[]):raise AppFailure('action_not_allowed')
        scopes=app.get('allowed_scopes',['private'])
        if ctx.scope not in scopes and not (ctx.scope=='p:'+ctx.owner and 'private' in scopes):raise AppFailure('scope_denied')
        if self.store.get(ctx.scope,'enabled',True) is False:raise AppFailure('scope_disabled')
        if type(app.get('timeout')) not in (int,float) or not 1<=app['timeout']<=120:raise AppFailure('invalid_timeout')
        if action+'_method' not in app:raise AppFailure('missing_method')
        return app

    def status(self, ctx, app_id):
        app=self._app(ctx,app_id,'status')
        return {'app_id':app_id,**self.executor.status(app)}

    def request(self, ctx, tool, args):
        app=self._app(ctx,args['app_id'],args['action'])
        if args['action'] not in ('start','stop','restart'):raise AppFailure('action_not_allowed')
        now=self.clock();ticket=secrets.token_urlsafe(18)
        with self.store.lock,self.store.db:
            self.store.db.execute("UPDATE app_confirmations SET status='expired' WHERE status='pending' AND expires<?",(now,))
            actor=self.bot.tool_broker.actor_hash(ctx.owner)
            n=self.store.db.execute("SELECT count(*) FROM app_confirmations WHERE owner_hash=? AND status='pending'",(actor,)).fetchone()[0]
            if n>=5:raise AppFailure('confirmation_limit')
            self.store.db.execute('INSERT INTO app_confirmations VALUES(?,?,?,?,?,?,?,?)',
                (hashlib.sha256(ticket.encode()).hexdigest(),actor,ctx.scope,tool,json.dumps(args,sort_keys=True),
                 hashlib.sha256(json.dumps(app,sort_keys=True).encode()).hexdigest(),now+120,'pending'))
        return {'app_id':args['app_id'],'action':args['action'],'confirm_id':ticket,'expires_seconds':120,
                'instruction':'同一管理员在同一会话发送 /应用 确认 '+ticket+'；模型不能确认'}

    def confirm(self, ctx, ticket):
        if not isinstance(ticket,str) or len(ticket)>80:raise AppFailure('invalid_confirmation')
        # Serialize changes; scope/actor/config checks repeated at consumption.
        with self.lock:
            with self.store.lock,self.store.db:
                row=self.store.db.execute('SELECT * FROM app_confirmations WHERE ticket_hash=?',
                    (hashlib.sha256(ticket.encode()).hexdigest(),)).fetchone()
                if (not row or row['status']!='pending' or row['expires']<self.clock()
                        or row['scope']!=ctx.scope or row['owner_hash']!=self.bot.tool_broker.actor_hash(ctx.owner)):
                    raise AppFailure('invalid_confirmation')
                args=json.loads(row['args']);app=self._app(ctx,args['app_id'],args['action'])
                if row['tool']!='control_app':raise AppFailure('invalid_confirmation')
                if row['config_hash']!=hashlib.sha256(json.dumps(app,sort_keys=True).encode()).hexdigest():
                    raise AppFailure('configuration_changed')
                self.store.db.execute("UPDATE app_confirmations SET status='consumed' WHERE ticket_hash=?",(row['ticket_hash'],))
            tool=self.bot.tool_broker.registry.tools['control_app'];started=time.monotonic()
            self.bot.tool_broker.audit(ctx,tool,'started',started)
            try:
                detach=args['app_id']=='qqbot' and args['action']=='restart'
                if detach:
                    script=Path(app['restart_method'].get('script','')).resolve()
                    standard=(self.bot.root/'tools/restart-service.ps1').resolve()
                    if script!=standard:raise AppFailure('self_restart_script_denied')
                    # A missing/unknown preparation receipt prevents launch; ticket stays consumed.
                    with self.bot.delivery_locks.hold(ctx.scope):
                        receipt=self.bot.ob.send(ctx.scope,[{'type':'text','data':{'text':'准备重启 QQBot；恢复后请检查状态。'}}])
                    if not isinstance(receipt,dict) or not receipt.get('message_id'):raise AppFailure('preparation_unknown')
                current=self._app(ctx,args['app_id'],args['action'])
                if row['config_hash']!=hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest():
                    raise AppFailure('configuration_changed')
                result=self.executor.execute(app,args['action'],detach=detach)
            except Exception as ex:
                code=str(ex) if isinstance(ex,AppFailure) and str(ex) in {
                    'timeout_unknown','timeout','application_failed','self_restart_script_denied','preparation_unknown','permission_denied','configuration_changed',
                    'invalid_method','invalid_script','invalid_host','invalid_arguments','host_unavailable','unsupported_platform'} else 'application_error'
                self.bot.tool_broker.audit(ctx,tool,code,started)
                return {'ok':False,'error':code,'retry_safe':False}
            self.bot.tool_broker.audit(ctx,tool,'ok',started)
            return {'ok':True,'app_id':args['app_id'],'result':result}
