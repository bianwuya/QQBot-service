"""Group-scoped, opt-in quote cards. Never invoke a model or trust quoted text as identity."""
from datetime import datetime
from functools import lru_cache
import math
from pathlib import Path
import re
import secrets

from safe_net import Rejected

MAX_TEXT=240
MAX_CARD_BYTES=512*1024
_SECRET=re.compile(r'(?i)(密码|口令|验证码|令牌|密钥|password|passwd|token|secret|api[ _-]?key|'
                   r'authorization|cookie|-----BEGIN|\bsk-[A-Za-z0-9_-]{12,}|\beyJ[A-Za-z0-9_-]{12,}\.|'
                   r'\b[A-Fa-f0-9]{32,}\b|\b[A-Za-z0-9_-]{40,}\b)')


def quotes_enabled(store,scope):
    return store.get(scope,'cap:quotes',False) is True


def quote_request(e):
    """Return (action, subject) for deliberately narrow group-only triggers."""
    if not e.get('scope','').startswith('g:'):return None
    text=e.get('text','').strip()
    if text=='计入' and e.get('reply_id'):return ('capture',None)
    if text=='语录':
        targets=[x for x in e.get('mentions',[]) if x!=e.get('self_id')]
        if len(targets)==1 and len(e.get('mentions',[]))<=2:return ('lookup',targets[0])
    if text=='/语录' or text.startswith('/语录 '):return ('manage',None)
    return None


def _text_of(message):
    if isinstance(message,list):
        if not message or any(not isinstance(s,dict) or s.get('type')!='text' or
                              not isinstance(s.get('data'),dict) or
                              not isinstance(s['data'].get('text'),str) for s in message):
            raise Rejected('目前只支持收录纯文字原消息。')
        value=''.join(s['data']['text'] for s in message)
    elif isinstance(message,str) and '[cq:' not in message.casefold():
        value=message
    else:raise Rejected('目前只支持收录纯文字原消息。')
    value=value.strip()
    if not value or len(value)>MAX_TEXT or len(value.splitlines())>4 or any(
            ord(c)<32 and c not in '\n\t' for c in value):
        raise Rejected('原消息须为 1～240 字、最多四行的普通文字。')
    if _SECRET.search(value) or re.search(r'https?://\S*\?',value,re.I):
        raise Rejected('原消息可能包含凭据或敏感链接，未收录。')
    return value


def _safe_name(value):
    clean=''.join(c for c in str(value or '') if c.isprintable() and c not in '\r\n\t')[:18]
    return clean if clean and not _SECRET.search(clean) else '群友'


@lru_cache(maxsize=1)
def _card_fonts():
    from PIL import ImageFont
    regular=next((p for p in (Path('C:/Windows/Fonts/msyh.ttc'),Path('C:/Windows/Fonts/simhei.ttf')) if p.is_file()),None)
    if regular is None:raise Rejected('缺少中文字体，暂无法生成语录图片。')
    bold=Path('C:/Windows/Fonts/msyhbd.ttc')
    bold=bold if bold.is_file() else regular
    serif=next((p for p in (Path('C:/Windows/Fonts/STZHONGS.TTF'),Path('C:/Windows/Fonts/simsun.ttc')) if p.is_file()),regular)
    bodies={size:ImageFont.truetype(str(serif),size) for size in (34,46,60,74)}
    return (bodies,ImageFont.truetype(str(bold),24),ImageFont.truetype(str(serif),31),
            ImageFont.truetype(str(regular),18),ImageFont.truetype(str(serif),100))


def render_card(text,nickname,source_time,path,quote_id=None):
    """High-contrast amber quote poster; pre-rendered palette PNG for fast QQ upload."""
    from PIL import Image,ImageDraw
    bodies,title,meta,small,mark=_card_fonts()
    body_size=74 if len(text)<=12 else 60 if len(text)<=80 else 46 if len(text)<=160 else 34
    body=bodies[body_size];line_height=body_size+22
    probe=ImageDraw.Draw(Image.new('RGB',(840,80)))
    lines=[]
    for original in text.splitlines():
        original=original.expandtabs(2)
        advances=[probe.textlength(char,font=body) for char in original]
        # Book-like line lengths: reserve breathing room so the final line is not an orphan.
        planned=max(1,math.ceil(sum(advances)/(590*.82)))
        soft_limit=min(590,sum(advances)/planned+body_size*.25)
        line='';width=0;line_index=0
        for char,advance in zip(original,advances):
            limit=soft_limit if line_index<planned-1 else 590
            if width+advance>limit and line:
                if char in '，。！？；、：,.!?;:)]）】':
                    # Keep punctuation with its preceding character, even at a wrap.
                    if width+advance>590 and len(line)>1:
                        tail=line[-1];lines.append(line[:-1]);line=tail
                        width=probe.textlength(tail,font=body);line_index+=1
                else:
                    lines.append(line);line='';width=0;line_index+=1
            line+=char;width+=advance
        lines.append(line)
    if len(lines)>22:raise Rejected('原消息排版过长，无法安全生成图片。')
    height=max(470,364+len(lines)*line_height)
    image=Image.new('RGB',(840,height),(255,243,216));draw=ImageDraw.Draw(image)
    # Flat coral/cream/teal blocks make the card lively without a heavy gradient.
    draw.rectangle((0,0,840,115),fill=(250,139,110))
    draw.rounded_rectangle((46,34,211,88),radius=18,fill=(21,69,67))
    draw.text((67,44),'群 友 语 录',font=title,fill=(255,248,231))
    draw.text((580,55),'把这句话留下来',font=small,fill=(21,69,67))
    draw.line((47,112,792,112),fill=(21,69,67),width=2)
    draw.text((73,130),_safe_name(nickname)+' 说：',font=meta,fill=(195,75,56))
    draw.ellipse((746,143,770,167),fill=(250,139,110))
    draw.ellipse((776,132,792,148),fill=(21,69,67))
    draw.text((111,185),'“',font=mark,fill=(244,151,112))
    draw.line((166,224,166,height-163),fill=(244,118,86),width=4)
    for number,line in enumerate(lines):
        draw.text((197,225+number*line_height),line,font=body,fill=(20,64,63))
    draw.rectangle((0,height-134,840,height),fill=(244,118,86))
    draw.rectangle((0,height-128,840,height),fill=(21,69,67))
    date=datetime.fromtimestamp(source_time).strftime('%Y.%m.%d  %H:%M')
    draw.text((49,height-103),'原消息时间  '+date,font=meta,fill=(255,245,220))
    draw.line((48,height-68,791,height-68),fill=(118,154,145),width=1)
    footer='依据原话排版  ·  非 QQ 聊天截图'
    if quote_id:footer+='  ·  编号 '+quote_id
    draw.text((49,height-53),footer,font=small,fill=(227,239,218))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    image.quantize(colors=96,method=Image.Quantize.FASTOCTREE,dither=Image.Dither.NONE).save(
        path,format='PNG',optimize=False,compress_level=3)
    if path.stat().st_size>MAX_CARD_BYTES:
        path.unlink(missing_ok=True);raise Rejected('语录图片超过大小限制，未收录。')
    return path


def validate_card(bot,path):
    p=Path(path);base=(bot.root/'state/quote_cards').resolve()
    if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(base) or not 0<p.stat().st_size<=MAX_CARD_BYTES:
        raise Rejected('语录图片不可用，未发送。')
    return p


def remove_card(bot,path):
    """Deleting a quote cannot turn an untrusted DB path into arbitrary file deletion."""
    p=Path(path);base=(bot.root/'state/quote_cards').resolve()
    if not p.is_symlink() and p.resolve().is_relative_to(base):p.unlink(missing_ok=True)


def _capture(bot,e,ident,directory):
    if e['owner'] not in bot.config_loader()['admins']:return bot.scope_text(e,'只有 Bot 指定管理员可以计入语录。')
    if not quotes_enabled(bot.store,e['scope']):return []
    source_id=e['reply_id']
    if bot.store.quote_by_source(e['scope'],source_id):return bot.scope_text(e,'这条原消息已经计入过语录。')
    try:source=bot.ob.call('get_msg',{'message_id':source_id},timeout=(3,8))
    except Exception:raise Rejected('无法回查被回复的原消息，未收录。') from None
    if str(source.get('group_id',''))!=e['scope'][2:] or source.get('message_type')!='group':
        raise Rejected('只能计入当前群内被回复的原消息。')
    owner=str(source.get('user_id') or (source.get('sender') or {}).get('user_id') or '')
    if not owner.isdigit() or owner==e['self_id']:
        raise Rejected('无法确认被回复消息的群友身份。')
    text=_text_of(source.get('message'))
    name=_safe_name((source.get('sender') or {}).get('card') or (source.get('sender') or {}).get('nickname'))
    timestamp=source.get('time')
    if not isinstance(timestamp,(int,float)) or not 0<timestamp<datetime.now().timestamp()+86400:
        raise Rejected('无法确认原消息时间，未收录。')
    if e['owner'] not in bot.config_loader()['admins'] or not quotes_enabled(bot.store,e['scope']):
        return []
    quote_id=secrets.token_hex(6)
    card=bot.root/'state/quote_cards'/(quote_id+'.png')
    staged=directory/'quote.png'
    render_card(text,name,timestamp,staged,quote_id=quote_id)
    try:
        card.parent.mkdir(parents=True,exist_ok=True)
        staged.replace(card)
        outcome=bot.store.add_quote(quote_id,e['scope'],owner,source_id,text,str(card),e['owner'],timestamp)
    except Exception:
        staged.unlink(missing_ok=True);remove_card(bot,card);raise
    if outcome!='added':
        remove_card(bot,card)
        return bot.scope_text(e,{'exists':'这条原消息已经计入过语录。','optout':'该群友已退出语录收录。',
                                 'limit':'本群或该群友的语录已达上限。'}[outcome])
    return bot.scope_text(e,'已计入语录，编号：'+quote_id+'。')


def _lookup(bot,e,subject):
    if not quotes_enabled(bot.store,e['scope']):return []
    quote,count=bot.store.random_quote(e['scope'],subject)
    if not quote:return bot.scope_text(e,'这位群友在本群还没有语录。')
    validate_card(bot,quote['image_path'])
    return [{'kind':'quote_card','path':quote['image_path'],'quote_id':quote['id']}]


def _manage(bot,e):
    arg=e['text'][len('/语录'):].strip()
    if not arg or arg=='状态':
        return bot.scope_text(e,'本群语录：'+('开启' if quotes_enabled(bot.store,e['scope']) else '关闭')+
            '。管理员回复原消息发送「计入」；群友 @某人 语录 随机查看；/语录 删除 编号；/语录 退出 或 /语录 恢复。')
    if arg in ('退出','恢复'):
        with bot.delivery_locks.hold(e['scope']):
            paths=bot.store.set_quote_optout(e['scope'],e['owner'],arg=='退出')
            for path in paths:remove_card(bot,path)
        return bot.scope_text(e,'已退出语录并删除本群已有记录。' if arg=='退出' else '已恢复允许管理员收录你今后的群消息。')
    if arg.startswith('删除 '):
        quote_id=arg[3:].strip()
        if not re.fullmatch(r'[0-9a-f]{12}',quote_id):return bot.scope_text(e,'用法：/语录 删除 <12位编号>')
        with bot.delivery_locks.hold(e['scope']):
            path=bot.store.delete_quote(e['scope'],quote_id,e['owner'],e['owner'] in bot.config_loader()['admins'])
            if path:remove_card(bot,path)
        return bot.scope_text(e,'已删除语录。' if path else '未找到可由你删除的本群语录。')
    return bot.scope_text(e,'用法：/语录 状态、/语录 删除 编号、/语录 退出、/语录 恢复。')


def handle(bot,e,ident,directory):
    request=quote_request(e)
    if not request:return None
    action,subject=request
    if action=='manage':return _manage(bot,e)
    if action=='capture':return _capture(bot,e,ident,directory)
    return _lookup(bot,e,subject)
