"""Program-owned identity and policy; model arguments cannot select a handler."""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import queue
import secrets
import threading
import time
from .schemas import validate


@dataclass
class CallContext:
    scope: str
    owner: str
    calls: int = 0
    failed: set = field(default_factory=set)


class Broker:
    def __init__(self, store, registry, config_loader):
        self.metrics=getattr(store,'metrics',None)
        self.store, self.registry, self.config_loader = store, registry, config_loader
        self.slots = threading.BoundedSemaphore(2)
        self.lock = threading.RLock()
        with store.lock, store.db:
            salt = store.get('*','tool_audit_salt')
            if not isinstance(salt,str):
                salt=secrets.token_hex(32);store.set('*','tool_audit_salt',salt)
            self.salt = salt.encode()
            store.db.execute('''CREATE TABLE IF NOT EXISTS tool_audit(
                id INTEGER PRIMARY KEY, time REAL, scope TEXT, actor_hash TEXT,tool_name TEXT,
                risk TEXT,result TEXT,duration REAL,error_code TEXT)''')
            store.db.execute('CREATE INDEX IF NOT EXISTS tool_rate ON tool_audit(scope,actor_hash,time)')

    def actor_hash(self, owner):
        return hmac.new(self.salt,str(owner).encode(),hashlib.sha256).hexdigest()[:24]

    def descriptors(self, context):
        cfg=self.config_loader()
        return self.registry.descriptors(context.owner in cfg['admins'],cfg.get('app_control_enabled') is True)

    def audit(self, ctx, tool, code, started):
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT INTO tool_audit(time,scope,actor_hash,tool_name,risk,result,duration,error_code) VALUES(?,?,?,?,?,?,?,?)',
                (time.time(),ctx.scope,self.actor_hash(ctx.owner),tool.name if tool else 'unknown',tool.risk if tool else 'unknown',
                 'ok' if code=='ok' else 'pending' if code=='started' else 'error',max(0,time.monotonic()-started),'' if code=='ok' else code))
        if self.metrics and code!='started':
            label=self.metrics.label('tool',tool.name if tool else 'unknown')
            self.metrics.emit('tool_success' if code=='ok' else 'tool_failure',label)
            if 'timeout' in code:self.metrics.emit('tool_timeout',label)

    def invoke(self, ctx, name, args):
        started=time.monotonic();tool=self.registry.tools.get(name) if isinstance(name,str) else None
        code='ok';result=None
        if self.metrics:self.metrics.emit('tool_calls',self.metrics.label('tool',tool.name if tool else 'unknown'))
        # Serializes rate reservation and per-message counters, not slow handlers.
        with self.lock:
            ctx.calls += 1
            cfg=self.config_loader()
            if ctx.calls>3:code='call_limit'
            elif tool is None:code='unknown_tool'
            elif name in ctx.failed:code='previous_failure'
            elif tool.risk!='L0' and not (tool.risk=='L2' and tool.confirmation and tool.name=='control_app'
                    and ctx.owner in cfg['admins'] and cfg.get('app_control_enabled') is True):code='risk_denied'
            elif not (ctx.scope.startswith(('g:','p:')) and ctx.owner.isdigit()):code='scope_denied'
            elif ctx.scope.startswith('p:') and ctx.scope!='p:'+ctx.owner:code='scope_denied'
            elif tool.permissions=='admin' and ctx.owner not in cfg['admins']:code='permission_denied'
            elif self.store.get(ctx.scope,'enabled',True) is False:code='scope_disabled'
            elif not validate(tool.parameters_schema,args):code='schema_error'
            else:
                with self.store.lock:
                    n=self.store.db.execute("SELECT count(*) FROM tool_audit WHERE scope=? AND actor_hash=? AND time>? AND error_code='started'",
                        (ctx.scope,self.actor_hash(ctx.owner),time.time()-60)).fetchone()[0]
                if n>=10:code='rate_limited'
                elif not self.slots.acquire(blocking=False):code='executor_busy'
                else:
                    # Durable reservation also prevents concurrent calls bypassing rate checks.
                    self.audit(ctx,tool,'started',started)
        if code=='ok':
            out=queue.Queue(maxsize=1)
            def run():
                try:
                    # Recheck mutable authorization in the execution thread.
                    if tool.permissions=='admin' and ctx.owner not in self.config_loader()['admins']:
                        out.put(('permission_denied',None))
                    else:
                        out.put(('ok',tool.handler(ctx,args)))
                except Exception:
                    out.put(('handler_error',None))
                finally:
                    self.slots.release()
            threading.Thread(target=run,daemon=True,name='bounded-tool').start()
            try:code,result=out.get(timeout=tool.timeout)
            except queue.Empty:code='timeout'
        if code=='ok' and tool.permissions=='admin' and ctx.owner not in self.config_loader()['admins']:
            code='permission_denied'
        if code!='ok':
            ctx.failed.add(name if isinstance(name,str) else '')
            result=None
        if code=='ok':
            try:
                if len(json.dumps(result,ensure_ascii=False))>4000:
                    code='result_too_large';result=None;ctx.failed.add(name)
            except (ValueError,TypeError):
                code='invalid_result';result=None;ctx.failed.add(name)
        if code=='ok' and isinstance(result,dict) and 'confirm_id' in result and self.metrics:self.metrics.emit('confirm_required')
        self.audit(ctx,tool,code,started)
        return {'ok':code=='ok','result':result,'error':None if code=='ok' else code}

    def confirm_application(self, ctx, ticket, controller):
        from app_executor import AppFailure
        started=time.monotonic();tool=self.registry.tools.get('control_app')
        if self.metrics:self.metrics.emit('tool_calls',self.metrics.label('tool','control_app'))
        if ctx.owner not in self.config_loader()['admins']:
            self.audit(ctx,tool,'permission_denied',started)
            return {'ok':False,'error':'permission_denied'}
        try:return controller.confirm(ctx,ticket)
        except AppFailure as ex:
            code=str(ex) if str(ex) in {'invalid_confirmation','configuration_changed','control_disabled','app_not_allowed',
                'action_not_allowed','scope_denied','scope_disabled','permission_denied','invalid_timeout','missing_method'} else 'confirmation_rejected'
            self.audit(ctx,tool,code,started)
            return {'ok':False,'error':code}
