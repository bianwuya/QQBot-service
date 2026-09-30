"""Sequential failure routing; no retries for business errors or uncertain results."""
from collections import OrderedDict
import threading
import time
from safe_net import Rejected


class ModelFailure(Rejected):
    def __init__(self,code,failover=True):
        self.code=code;self.failover=failover
        super().__init__('模型网关暂不可用（'+code+'）')


def integer(config,key,default,low,high):
    value=config.get(key,default)
    return max(low,min(high,value)) if type(value) is int else default


class ModelRouter:
    def __init__(self,config_loader,clock=time.monotonic,metrics=None):
        self.metrics=metrics
        self.config_loader=config_loader;self.clock=clock;self.lock=threading.RLock()
        self.health=OrderedDict();self.sticky=OrderedDict();self.last_global_probe=0

    def settings(self,primary):
        cfg=self.config_loader();pool=cfg.get('model_pool')
        if not isinstance(pool,list) or not pool:return None
        names=[primary]+[m for m in pool[:8] if isinstance(m,str) and 0<len(m)<=160]
        names=list(dict.fromkeys(names))[:8]
        if len(names)<2:return None
        return dict(pool=names,threshold=integer(cfg,'failure_threshold',2,1,10),
                    cooldown=integer(cfg,'cooldown_seconds',120,30,3600),
                    interval=integer(cfg,'probe_interval',300,60,3600),
                    successes=integer(cfg,'probe_success_threshold',2,1,5))

    def state(self,model):
        state=self.health.setdefault(model,{'state':'HEALTHY','failures':0,'successes':0,'next_probe':0,'reason':'none'})
        self.health.move_to_end(model)
        while len(self.health)>64:self.health.popitem(last=False)
        return state

    def reset(self,scope=None):
        with self.lock:
            for key in list(self.sticky):
                if scope is None or key[0]==scope:del self.sticky[key]

    def _failure(self,model,error,settings):
        state=self.state(model);state['failures']+=1;state['reason']=error.code;state['successes']=0
        if state['failures']>=settings['threshold'] or error.code=='connect_timeout':
            state.update(state='COOLDOWN',next_probe=self.clock()+settings['cooldown'])
        else:state['state']='DEGRADED'
        return state['state']=='COOLDOWN'

    def run(self,scope,owner,primary,invoke,may_retry=lambda:True):
        settings=self.settings(primary)
        if settings is None:return invoke(primary)
        policy=tuple(settings['pool']);key=(scope,owner);now=self.clock()
        with self.lock:
            entry=self.sticky.get(key)
            if not entry or entry['policy']!=policy or entry['primary']!=primary:
                entry={'primary':primary,'model':primary,'policy':policy,'reason':'configured','last':now}
                self.sticky[key]=entry
            current=entry['model'];self.sticky.move_to_end(key)
            while len(self.sticky)>1024:self.sticky.popitem(last=False)
            order=list(dict.fromkeys([current]+settings['pool']))
        last=None;switching=False;reason='none'
        for model in order[:3]:
            with self.lock:
                if self.state(model)['state'] in ('COOLDOWN','PROBING'):
                    switching=True;reason=self.state(model)['reason'];continue
            try:
                result=invoke(model)
            except ModelFailure as ex:
                last=ex
                if not ex.failover:raise
                with self.lock:opened=self._failure(model,ex,settings)
                if not may_retry() or (not opened and not switching):raise
                switching=True;reason=ex.code
                continue
            with self.lock:
                self.state(model).update(state='HEALTHY',failures=0,successes=0,reason='none')
                # Do not restore a session reset by an admin while this request was running.
                if self.sticky.get(key) is entry:
                    entry.update(model=model,last=self.clock())
                    if model!=current:
                        entry['reason']=reason
                        if self.metrics:self.metrics.emit('model_switches',self.metrics.label('model',model))
            return result
        raise last or ModelFailure('all_models_cooldown',False)

    def probe_once(self,probe):
        now=self.clock()
        cfg=self.config_loader();default=(cfg.get('llm') or {}).get('default_model','')
        settings=self.settings(default)
        if settings is None:return False
        with self.lock:
            if self.last_global_probe and now-self.last_global_probe<settings['interval']:return False
            allowed=set(settings['pool'])
            for entry in self.sticky.values():allowed.add(entry['primary'])
            candidates=[m for m,s in self.health.items() if m in allowed and s['state'] in ('COOLDOWN','PROBING') and now>=s['next_probe']]
            if not candidates:return False
            model=candidates[0];state=self.state(model)
            state.update(state='PROBING',next_probe=now+settings['interval'])
            self.last_global_probe=now
        try:
            answer=probe(model)
            success=isinstance(answer,str) and bool(answer.strip())
        except Exception:success=False
        with self.lock:
            state=self.state(model)
            if success:
                state['successes']+=1
                if state['successes']>=settings['successes']:
                    state.update(state='HEALTHY',failures=0,successes=0,reason='probe_recovered')
                    for entry in self.sticky.values():
                        if entry['primary']==model:
                            if self.metrics and entry['model']!=model:self.metrics.emit('model_switches',self.metrics.label('model',model))
                            entry.update(model=model,reason='probe_recovered')
            else:state.update(state='COOLDOWN',successes=0,next_probe=self.clock()+settings['cooldown'],reason='probe_failed')
        return True

    def status(self,scope,owner,primary):
        settings=self.settings(primary)
        if settings is None:return '模型路由：单模型兼容模式；当前会话：'+primary
        with self.lock:
            entry=self.sticky.get((scope,owner),{})
            lines=[m+': '+self.state(m)['state'] for m in settings['pool']]
            lines+=['当前会话：'+entry.get('model',primary),'最近切换原因：'+entry.get('reason','none')]
            return '\n'.join(lines)
