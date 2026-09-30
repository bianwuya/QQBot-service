"""Bounded OneBot image ingestion. No network fetches, user paths or CQ-text parsing.

The caller supplies administrator-approved NapCat cache roots; an opaque file ID
is fetched via get_image then copied/decoded immediately (the NapCat file can be
short-lived). Only a same-conversation quoted message can supply a missing image.
"""
import io
import os
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from protocol import image_refs
from safe_net import Rejected

IMAGE_BYTES_LIMIT=8*1024*1024
IMAGE_PIXELS_LIMIT=12_000_000
MAX_DIMENSION=2048
_IMAGE_WORDS=('图片','图里','图中','看图','这张图','那张图','截图','照片','识图','画面','这幅图')
Image.MAX_IMAGE_PIXELS=IMAGE_PIXELS_LIMIT


def mentions_image(text):
    return isinstance(text,str) and any(word in text for word in _IMAGE_WORDS)


def find_refs(e,onebot):
    """Prefer current images; otherwise inspect at most one scoped reply."""
    if e.get('image_count'):
        if e['image_count']>2:raise Rejected('一次最多看2张图片')
        refs=e.get('image_refs') or []
        if len(refs)!=e['image_count']:raise Rejected('无法安全取得这张图片的标识，请重新发送')
        return refs
    mid=e.get('reply_id')
    if not mid:return []
    if not isinstance(mid,str) or not mid.isdigit() or len(mid)>20:
        raise Rejected('引用消息标识异常，无法取图')
    source=onebot.call('get_msg',{'message_id':int(mid)},timeout=(3,9))
    scope=e['scope']
    if scope.startswith('g:'):
        valid=source.get('message_type')=='group' and str(source.get('group_id'))==scope[2:]
    else:
        # get_msg does NOT include the recipient for bot-sent private photos.
        # In that case verify membership in THIS peer's friend-message history.
        valid=source.get('message_type')=='private' and str(source.get('user_id'))==e['owner']
        if not valid and source.get('message_type')=='private' and e.get('self_id') and \
                str(source.get('user_id'))==str(e['self_id']):
            history=onebot.call('get_friend_msg_history',
                    {'user_id':e['owner'],'count':25},timeout=(3,12))
            rows=history.get('messages',[]) if isinstance(history,dict) else []
            candidates=[row for row in rows[:25] if isinstance(row,dict) and
                    str(row.get('message_id'))==mid and row.get('message_type')=='private' and
                    str(row.get('user_id'))==str(e['self_id'])]
            valid=any(image_refs(row.get('message'),limit=3)==image_refs(source.get('message'),limit=3)
                    for row in candidates)
    if not valid:raise Rejected('只能读取同一会话里的引用图片')
    segments=source.get('message')
    refs=image_refs(segments,limit=3)
    if len(refs)>2:raise Rejected('一次最多看2张图片')
    if not refs and mentions_image(e.get('text')):
        raise Rejected('引用消息里没有可读取的图片，请直接发图')
    return refs


def read_image(onebot,file_id,allowed_roots,destination):
    """Read the file returned by get_image only inside configured roots, then
    validate dimensions and re-encode to strip EXIF/metadata before the model.
    The destination must be a private job-specific work directory.
    """
    if not image_refs([{'type':'image','data':{'file':file_id}}]):
        raise Rejected('图片标识异常')
    roots=[]
    for root in allowed_roots or ():
        try:
            path=Path(root).resolve(strict=True)
            if path.is_dir():roots.append(path)
        except (OSError,ValueError,TypeError):continue
    if not roots:raise Rejected('尚未配置安全的 QQ 图片缓存目录')
    data=onebot.call('get_image',{'file':file_id},timeout=(3,12))
    if not isinstance(data,dict):raise Rejected('QQ 未返回图片文件')
    value=data.get('file')
    if not isinstance(value,str) or not value or '\x00' in value:
        raise Rejected('QQ 未返回可读取的本地图片文件')
    try:
        original=Path(value).resolve(strict=True)
        if not original.is_file() or original.is_symlink() or not any(
                original==root or original.is_relative_to(root) for root in roots):
            raise Rejected('QQ 图片不在授权缓存目录内')
        with original.open('rb') as stream:
            size=os.fstat(stream.fileno()).st_size
            if not 0<size<=IMAGE_BYTES_LIMIT:raise Rejected('图片大小超过8MB限制')
            payload=stream.read(IMAGE_BYTES_LIMIT+1)
        if not payload or len(payload)>IMAGE_BYTES_LIMIT:raise Rejected('图片大小超过8MB限制')
    except Rejected:raise
    except (OSError,ValueError):raise Rejected('QQ 图片缓存暂不可读取，请重新发图') from None
    dest=Path(destination)
    created=False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as image:
                if image.format not in ('JPEG','PNG','WEBP','GIF','BMP'):
                    raise Rejected('暂不支持这种图片格式')
                if image.width*image.height>IMAGE_PIXELS_LIMIT:
                    raise Rejected('图片像素超过安全限制')
                image.seek(0)
                image.load()
                cleaned=ImageOps.exif_transpose(image)
                if cleaned.mode in ('RGBA','LA') or 'transparency' in cleaned.info:
                    cleaned=cleaned.convert('RGBA')
                    rgb=Image.new('RGB',cleaned.size,(255,255,255))
                    rgb.paste(cleaned,mask=cleaned.getchannel('A'))
                else:rgb=cleaned.convert('RGB')
                rgb.thumbnail((MAX_DIMENSION,MAX_DIMENSION))
                if dest.suffix.lower()!='.jpg':raise Rejected('无效的图片工作文件')
                with dest.open('xb') as target:
                    created=True
                    rgb.save(target,'JPEG',quality=85,optimize=True)
    except Rejected:
        if created:dest.unlink(missing_ok=True)
        raise
    except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        if created:dest.unlink(missing_ok=True)
        raise Rejected('图片无法安全解码，请换一张再试') from None
    return dest
