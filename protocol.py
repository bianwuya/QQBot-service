import hashlib
import json
import re
import time
import threading
from pathlib import Path
import requests
from media import platform_of, share_urls
from quotes import quote_request, quotes_enabled
from safe_net import Rejected
from model_router import ModelFailure

class DeliveryUnknown(RuntimeError):pass

ADMIN_COMMANDS={'/模型','/模型列表','/默认模型','/角色','/角色列表','/嘲讽','/记忆','/启用','/停用','/群触发','/群上下文','/群接话','/群记忆','/状态','/重发','/管理员','/配置','/任务','/执行','/run','/agent','/能力','/开','/关','/关键词','/风格','/指令','/人格状态','/主动','/知识库','/应用'}

CAPABILITIES={'聊天':'chat','文件':'files','视频':'videos','B站转发':'video:bilibili',
              '小红书转发':'video:xiaohongshu','关键词':'keywords','语录':'quotes',
              '识图':'vision','图文卡':'image_card'}
BUILTIN_COMMANDS=ADMIN_COMMANDS|{'/帮助','/help','/重置','/下载','/打包','/导出','/风格','/指令','/关键词','/能力','/开','/关','/语录','/图文卡'}
DEFAULT_KEYWORDS=['色色','瑟瑟','涩涩','搞颜色','羞羞','好色','色图','涩图','瑟图','色批','涩批','馋身子','擦边','不可描述','车门焊死','秋名山']
# Only OneBot-generated opaque file identifiers may reach get_image. Never
# interpret CQ-looking text, a user-supplied URL or a filesystem path as an ID.
_IMAGE_FILE_ID = re.compile(r'[A-Za-z0-9_{}-]{12,150}(?:\.(?:jpg|jpeg|png|webp|gif|bmp|image))?\Z',re.I)

def image_refs(segments,limit=2):
    refs=[]
    if not isinstance(segments,list):return refs
    for segment in segments[:100]:
        if not isinstance(segment,dict) or segment.get('type')!='image':continue
        data=segment.get('data')
        if not isinstance(data,dict):continue
        file_id=data.get('file')
        if isinstance(file_id,str) and _IMAGE_FILE_ID.fullmatch(file_id):
            refs.append({'file':file_id})
        if len(refs)>=limit:break
    return refs

def cap(store,scope,name):
    # External vision and outbound image cards in a group require explicit
    # per-group administrator opt-in even when their global switch is enabled.
    opt_in=name=='quotes' or (name in ('vision','image_card') and scope.startswith('g:'))
    value=store.get(scope,'cap:'+name,False if opt_in else True)
    return value is True if opt_in else value is not False

def video_enabled(store,scope,url):
    platform=platform_of(url)
    return bool(platform and cap(store,scope,'videos') and cap(store,scope,'video:'+platform))

def only_video_share(e):
    text=e.get('text','')
    for url in e.get('videos',[]):text=text.replace(url,'')
    return not text.strip(' \t\r\n，。；;、！？!?()（）[]【】')

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
    owner=str(raw.get('user_id',''));selfid=str(raw.get('self_id',''))
    if not owner.isdigit() or owner==selfid:return None
    if raw.get('post_type')=='notice':
        kind = (raw.get('notice_type'),raw.get('sub_type'))
        notice = 'poke' if kind==('notify','poke') and str(raw.get('target_id'))==selfid else (
            'welcome' if raw.get('notice_type')=='group_increase' else None)
        if notice:
            group = str(raw.get('group_id',''))
            if not group.isdigit() or not selfid.isdigit():return None
            scope='g:'+group
            marker=str(raw.get('time') or int(time.time()//10))
            raw_key='notice:'+selfid+':'+scope+':'+notice+':'+owner+':'+marker
            return {'key':hashlib.sha256(raw_key.encode()).hexdigest(),'scope':scope,
                    'owner':owner,'self_id':selfid,'text':'','files':[],'videos':[],
                    'speaker':'群友','image_count':0,'at':False,'mentions':[],
                    'reply_id':None,'message_id':None,'json_share':False,'notice':notice}
        if raw.get('notice_type') not in ('group_upload','offline_file'):return None
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
    mentions=list(dict.fromkeys(str(s['data'].get('qq')) for s in segments if s.get('type')=='at'
        and str(s['data'].get('qq','')).isdigit() and 5<=len(str(s['data'].get('qq')))<=20))[:5]
    replies=[str(s['data'].get('id','')) for s in segments if s.get('type')=='reply'
             and str(s['data'].get('id','')).isdigit() and len(str(s['data'].get('id','')))<=20]
    files=[s['data'] for s in segments if s.get('type')=='file']
    if raw.get('notice_type') in ('group_upload','offline_file') and isinstance(raw.get('file'),dict):files=[raw['file']]
    if len(files)>3:raise Rejected('一次最多分析3个文件')
    files=[{'id':str(f.get('id') or f.get('file_id') or f.get('file') or ''),'name':str(f.get('name') or f.get('file_name') or '文件.txt'),
            'size':f.get('size') or f.get('file_size') or 0} for f in files]
    files=[f for f in files if f['id']]
    image_count=min(3,sum(s.get('type')=='image' for s in segments))
    image_files=image_refs(segments)
    at_self=any(s.get('type')=='at' and str(s.get('data',{}).get('qq'))==selfid for s in segments)
    videos=share_urls(segments)
    if not text and not files and not videos and not image_count and not (at_self and len(replies)==1):return None
    sender=raw.get('sender')
    name=(sender.get('card') or sender.get('nickname')) if isinstance(sender,dict) else None
    speaker=name[:40] if group and isinstance(name,str) else ''
    # File notices and file messages with the same scope/uploader/file IDs are one job.
    if files:key='file:'+scope+':'+owner+':'+','.join(sorted(f['id'] for f in files))
    else:
        mid=raw.get('message_id')
        if mid is None:return None
        key='msg:'+selfid+':'+scope+':'+str(mid)
    return {'key':hashlib.sha256(key.encode()).hexdigest(),'scope':scope,'owner':owner,'self_id':selfid,
            'text':text,'files':files,'videos':videos,'speaker':speaker,'image_count':image_count,
            'image_refs':image_files,'at':at_self,
            'json_share':any(s.get('type')=='json' for s in segments),
            'mentions':mentions,'reply_id':replies[0] if len(replies)==1 else None,
        'message_id':str(raw.get('message_id')) if str(raw.get('message_id','')).isdigit() else None}

def command(text):
    head,_,arg=text.strip().partition(' ')
    return head,arg.strip()

def should_handle(e,cfg,store):
    if e.get('notice'):return False  # Triggered only by the opt-in share-reply event path.
    cmd,_=command(e['text']);admin=e['owner'] in cfg['admins']
    if store.get(e['scope'],'enabled',True) is False and not admin:return False
    if e['scope'].startswith('p:'):return True
    quote=quote_request(e)
    if quote:
        if quote[0]=='manage':return True
        return quotes_enabled(store,e['scope']) and (quote[0]!='capture' or admin)
    if e['text'].strip()=='计入' and e.get('reply_id'):return False
    if e['text'].strip()=='语录' and e.get('mentions'):return False
    if e['files'] and cfg.get('file_auto',True) and cap(store,e['scope'],'files'):return True
    if e['videos'] and cfg.get('video_auto',True) and any(video_enabled(store,e['scope'],url) for url in e['videos']):return True
    if cmd.startswith('/') and cmd in BUILTIN_COMMANDS:return True
    if cmd in custom_commands(store,e['scope']):return True
    if (not cmd.startswith('/')) and cap(store,e['scope'],'keywords') and keyword_hit(e['text'],group_keywords(store,e['scope'])):
        if time.time()>=float(store.get(e['scope'],'kw_cooldown_until',0) or 0):return True
    # A disabled bare share should not fall through to normal chat in all-messages mode.
    if e['videos'] and not e['files'] and only_video_share(e) and not any(
            video_enabled(store,e['scope'],url) for url in e['videos']):return False
    if not cap(store,e['scope'],'chat'):return False
    # All-messages mode must not reply to every standalone group photo.
    if e.get('image_count') and not e['text'] and not e['at']:return False
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
        self.base=cfg['base_url'].rstrip('/');self.token=cfg['token'];self.local=threading.local()
    @property
    def session(self):
        if not hasattr(self.local,'session'):
            session=requests.Session();session.trust_env=False
            session.headers['Authorization']='Bearer '+self.token
            self.local.session=session
        return self.local.session
    def call(self,action,payload=None,timeout=(5,90)):
        try:
            r=self.session.post(self.base+'/'+action,json=payload or {},timeout=timeout);r.raise_for_status()
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
    def request(self,path,payload=None,timeout=None):
        key=Path(self.cfg['key_file']).read_text('utf-8-sig').strip()
        if not key:raise Rejected('网关密钥为空')
        s=requests.Session();s.trust_env=False;r=None
        try:
            r=s.request('POST' if payload is not None else 'GET',self.cfg['base_url'].rstrip('/')+path,
                        json=payload,headers={'Authorization':'Bearer '+key},timeout=timeout or (5,self.cfg.get('timeout',120)),stream=True)
            if r.status_code!=200:
                if r.status_code in (500,502,503,504):raise ModelFailure('http_'+str(r.status_code))
                # Only a bounded, explicit error code may mark no-account availability.
                first=next(r.iter_content(4096),b'')
                try:code=json.loads(first).get('error',{}).get('code')
                except (ValueError,AttributeError,TypeError):code=None
                if code in ('no_available_accounts','no_available_account','upstream_unavailable'):
                    raise ModelFailure('no_accounts')
                raise Rejected('模型网关请求失败，HTTP '+str(r.status_code))
            chunks=[];n=0
            for chunk in r.iter_content(65536):
                n+=len(chunk)
                if n>4*1024*1024:raise Rejected('模型响应超过限制')
                chunks.append(chunk)
            return json.loads(b''.join(chunks))
        except requests.ConnectTimeout:raise ModelFailure('connect_timeout') from None
        except requests.ReadTimeout:raise ModelFailure('response_unknown',False) from None
        except requests.ConnectionError:raise ModelFailure('connection_unknown',False) from None
        except requests.RequestException:raise ModelFailure('transport_unknown',False) from None
        finally:
            if r is not None:r.close()
            s.close()
    def models(self):
        return sorted({x['id'] for x in self.request('/models').get('data',[]) if isinstance(x.get('id'),str)})
    def chat(self,model,messages,max_tokens=None,mark_length=True,sampling=None):
        # Deliberately no tools/functions, command execution or Agent client in any model request.
        tokens=max_tokens if isinstance(max_tokens,int) and max_tokens>0 else self.cfg.get('max_tokens',4096)
        payload={'model':model,'messages':messages,'stream':False,'max_tokens':tokens}
        if isinstance(sampling,dict):
            # Optional, allow-listed sampling knobs (offline evaluation and future config); never forwarded blindly.
            for key,(low,high) in {'temperature':(0.0,2.0),'top_p':(0.0,1.0),'presence_penalty':(-2.0,2.0),'frequency_penalty':(-2.0,2.0)}.items():
                value=sampling.get(key)
                if isinstance(value,(int,float)) and not isinstance(value,bool):payload[key]=min(high,max(low,float(value)))
        data=self.request('/chat/completions',payload)
        choices=data.get('choices') or []
        if not choices:raise Rejected('模型没有返回答案')
        choice=choices[0];answer=choice.get('message',{}).get('content')
        if not isinstance(answer,str) or not answer.strip():raise Rejected('模型返回空答案')
        if choice.get('finish_reason')=='length' and mark_length:answer+='\n\n[模型达到输出上限，以上内容可能不完整。可继续追问。]'
        return answer

    def chat_tools(self,model,messages,broker,context,max_tokens=None,mark_length=True):
        from tooling.conversation import chat
        return chat(self,model,messages,broker,context,max_tokens,mark_length)

