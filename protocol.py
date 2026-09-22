import hashlib
import json
import re
import time
from pathlib import Path
import requests
from media import share_urls
from safe_net import Rejected

class DeliveryUnknown(RuntimeError):pass

ADMIN_COMMANDS={'/模型','/模型列表','/默认模型','/启用','/停用','/群触发','/状态','/重发','/管理员','/配置','/任务','/执行','/run','/agent','/能力','/开','/关','/关键词','/风格','/指令'}

CAPABILITIES={'聊天':'chat','文件':'files','视频':'videos','关键词':'keywords'}
BUILTIN_COMMANDS=ADMIN_COMMANDS|{'/帮助','/help','/重置','/下载','/打包','/导出','/风格','/指令','/关键词','/能力','/开','/关'}
DEFAULT_KEYWORDS=['色色','瑟瑟','涩涩','搞颜色','羞羞','好色','色图','涩图','瑟图','色批','涩批','馋身子','擦边','不可描述','车门焊死','秋名山']

def cap(store,scope,name):
    return store.get(scope,'cap:'+name,True) is not False

def keywords_of(store):
    words=store.get('*','keywords')
    return [w for w in words if isinstance(w,str) and w.strip()] if words else list(DEFAULT_KEYWORDS)

def keyword_hit(text,keywords):
    text=text or ''
    return next((w for w in keywords if w and w in text),None)

def custom_commands(store,scope):
    data=store.get(scope,'custom_commands') or {}
    return {k:v for k,v in data.items() if isinstance(k,str) and k.startswith('/')
            and isinstance(v,dict) and v.get('mode') in ('text','gen') and isinstance(v.get('content'),str)}

def group_keywords(store,scope):
    return keywords_of(store)+[w for w in (store.get(scope,'keywords_extra') or []) if isinstance(w,str) and w.strip()]

def normalize(raw):
    if raw.get('post_type') not in ('message','notice'):return None
    if raw.get('post_type')=='notice' and raw.get('notice_type') not in ('group_upload','offline_file'):return None
    owner=str(raw.get('user_id',''));selfid=str(raw.get('self_id',''))
    if not owner.isdigit() or owner==selfid:return None
    group=raw.get('group_id')
    scope='g:'+str(group) if group else 'p:'+owner
    if group and not str(group).isdigit():return None
    segments=raw.get('message',[])
    if isinstance(segments,str):
        # Do not interpret user text as CQ markup; LLBot is configured to array format.
        segments=[{'type':'text','data':{'text':segments}}]
    if not isinstance(segments,list):return None
    segments=[s for s in segments[:100] if isinstance(s,dict) and isinstance(s.get('data',{}),dict)]
    text=''.join(str(s.get('data',{}).get('text','')) for s in segments if s.get('type')=='text').strip()
    files=[s['data'] for s in segments if s.get('type')=='file']
    if raw.get('notice_type') in ('group_upload','offline_file') and isinstance(raw.get('file'),dict):files=[raw['file']]
    if len(files)>3:raise Rejected('一次最多分析3个文件')
    files=[{'id':str(f.get('id') or f.get('file_id') or f.get('file') or ''),'name':str(f.get('name') or f.get('file_name') or '文件.txt'),
            'size':f.get('size') or f.get('file_size') or 0} for f in files]
    files=[f for f in files if f['id']]
    if not text and not files and not share_urls(segments):return None
    # File notices and file messages with the same scope/uploader/file IDs are one job.
    if files:key='file:'+scope+':'+owner+':'+','.join(sorted(f['id'] for f in files))
    else:
        mid=raw.get('message_id')
        if mid is None:return None
        key='msg:'+selfid+':'+scope+':'+str(mid)
    return {'key':hashlib.sha256(key.encode()).hexdigest(),'scope':scope,'owner':owner,'self_id':selfid,
            'text':text,'files':files,'videos':share_urls(segments),
            'at':any(s.get('type')=='at' and str(s.get('data',{}).get('qq'))==selfid for s in segments),
            'json_share':any(s.get('type')=='json' for s in segments)}

def command(text):
    head,_,arg=text.strip().partition(' ')
    return head,arg.strip()

def should_handle(e,cfg,store):
    cmd,_=command(e['text']);admin=e['owner'] in cfg['admins']
    if store.get(e['scope'],'enabled',True) is False and not admin:return False
    if e['scope'].startswith('p:'):return True
    if e['files'] and cfg.get('file_auto',True) and cap(store,e['scope'],'files'):return True
    if e['videos'] and cfg.get('video_auto',True) and cap(store,e['scope'],'videos'):return True
    if cmd.startswith('/') and cmd in BUILTIN_COMMANDS:return True
    if cmd in custom_commands(store,e['scope']):return True
    if (not cmd.startswith('/')) and cap(store,e['scope'],'keywords') and keyword_hit(e['text'],group_keywords(store,e['scope'])):
        if time.time()>=float(store.get(e['scope'],'kw_cooldown_until',0) or 0):return True
    if not cap(store,e['scope'],'chat'):return False
    return e['at'] or not store.get(e['scope'],'require_at',cfg.get('group_require_at',True))

def forward_batches(text,self_id,node_chars=1200,batch_nodes=30):
    if not self_id or not str(self_id).isdigit():raise Rejected('尚未获取 Bot 身份，不能构造转发')
    # Labels occupy their own node. Full content remains exactly recoverable, no CQ string execution.
    chunks=[];current=[];units=0
    for char in text:
        cost=2 if ord(char)>0xffff else 1
        if units+cost>node_chars:
            chunks.append(''.join(current));current=[];units=0
        current.append(char);units+=cost
    if current:chunks.append(''.join(current))
    batches=[chunks[i:i+batch_nodes-1] for i in range(0,len(chunks),batch_nodes-1)]
    result=[]
    for i,batch in enumerate(batches):
        strings=([f'回复 {i+1}/{len(batches)}'] if len(batches)>1 else [])+batch
        result.append([{'type':'node','data':{'name':'QQ助手','uin':str(self_id),'content':[{'type':'text','data':{'text':s}}]}} for s in strings])
    return result

class OneBot:
    def __init__(self,cfg):
        self.base=cfg['base_url'].rstrip('/');self.session=requests.Session();self.session.trust_env=False
        self.session.headers['Authorization']='Bearer '+cfg['token']
    def call(self,action,payload=None):
        try:
            r=self.session.post(self.base+'/'+action,json=payload or {},timeout=(5,90));r.raise_for_status()
            data=r.json()
        except (requests.RequestException,ValueError):raise DeliveryUnknown('OneBot 请求失败或超时，结果待确认') from None
        if data.get('status')!='ok' or data.get('retcode')!=0:raise Rejected('QQ 接口返回失败：'+action)
        return data.get('data') or {}
    def send(self,scope,segments):
        group=scope.startswith('g:');params={'group_id' if group else 'user_id':scope[2:],'message':segments}
        d=self.call('send_group_msg' if group else 'send_private_msg',params)
        if not d.get('message_id'):raise DeliveryUnknown('QQ 未返回消息标识，不能确认发送成功')
        return {'message_id':d['message_id']}
    def text(self,scope,text,self_id):
        if len(text)<=1400:return [self.send(scope,[{'type':'text','data':{'text':text}}])]
        receipts=[];group=scope.startswith('g:')
        for batch in forward_batches(text,self_id):
            d=self.call('send_group_forward_msg' if group else 'send_private_forward_msg',{'group_id' if group else 'user_id':scope[2:],'messages':batch})
            if not d.get('message_id'):raise DeliveryUnknown('QQ 未返回合并转发消息标识')
            receipts.append({'message_id':d['message_id']})
        return receipts
    def upload(self,scope,path):
        group=scope.startswith('g:');p=Path(path)
        d=self.call('upload_group_file' if group else 'upload_private_file',{'group_id' if group else 'user_id':scope[2:],'file':str(p.resolve()),'name':p.name})
        if not d.get('file_id'):raise DeliveryUnknown('QQ 未返回文件标识，上传结果待确认')
        return {'file_id':d['file_id']}
    def file_url(self,e,file):
        group=e['scope'].startswith('g:');args={'file_id':file['id']}
        if group:args['group_id']=e['scope'][2:]
        data=self.call('get_group_file_url' if group else 'get_private_file_url',args)
        if not data.get('url'):raise Rejected('QQ 未返回文件下载地址')
        return data['url']

class LLM:
    def __init__(self,cfg):
        self.cfg=cfg
    def request(self,path,payload=None):
        key=Path(self.cfg['key_file']).read_text('utf-8-sig').strip()
        if not key:raise Rejected('网关密钥为空')
        s=requests.Session();s.trust_env=False
        try:
            r=s.request('POST' if payload is not None else 'GET',self.cfg['base_url'].rstrip('/')+path,
                        json=payload,headers={'Authorization':'Bearer '+key},timeout=(5,self.cfg.get('timeout',120)),stream=True)
            if r.status_code!=200:raise Rejected('模型网关请求失败，HTTP '+str(r.status_code))
            chunks=[];n=0
            for chunk in r.iter_content(65536):
                n+=len(chunk)
                if n>4*1024*1024:raise Rejected('模型响应超过限制')
                chunks.append(chunk)
            return json.loads(b''.join(chunks))
        except requests.RequestException:raise Rejected('模型网关连接失败或超时') from None
        finally:s.close()
    def models(self):
        return sorted({x['id'] for x in self.request('/models').get('data',[]) if isinstance(x.get('id'),str)})
    def chat(self,model,messages):
        # Deliberately no tools/functions, command execution or Agent client in any model request.
        data=self.request('/chat/completions',{'model':model,'messages':messages,'stream':False,'max_tokens':self.cfg.get('max_tokens',4096)})
        choices=data.get('choices') or []
        if not choices:raise Rejected('模型没有返回答案')
        choice=choices[0];answer=choice.get('message',{}).get('content')
        if not isinstance(answer,str) or not answer.strip():raise Rejected('模型返回空答案')
        if choice.get('finish_reason')=='length':answer+='\n\n[模型达到输出上限，以上内容可能不完整。可继续追问。]'
        return answer
