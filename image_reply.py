"""Explicit, offline text-card replies. No web search, AI image generation or user paths."""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from safe_net import Rejected

MAX_CARD_CHARS=180
MAX_CARD_BYTES=3*1024*1024


def _font(size):
    for file in ('C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/simhei.ttf',
                 'C:/Windows/Fonts/simsun.ttc','C:/Windows/Fonts/arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:return ImageFont.truetype(file,size)
        except (OSError,ValueError):continue
    return ImageFont.load_default(size=size)


def card_text(value):
    if not isinstance(value,str) or not value.strip():raise Rejected('用法：/图文卡 想放在卡片上的文字')
    text=value.strip()
    if len(text)>MAX_CARD_CHARS:raise Rejected('图文卡文字请控制在180字以内')
    # This is TEXT, never an asset ID, path, URL or an instruction to open files.
    if re.search(r'[\x00-\x08\x0b-\x1f\x7f]',text):raise Rejected('图文卡含不支持的控制字符')
    return text


def _wrap(draw,text,font,width):
    lines=[]
    for paragraph in text.splitlines():
        line=''
        if not paragraph:lines.append('');continue
        for char in paragraph:
            if draw.textlength(line+char,font=font)<=width:line+=char
            else:
                if line:lines.append(line)
                line=char
        if line:lines.append(line)
    if len(lines)>5:raise Rejected('图文卡内容过长，请缩短文字或减少换行')
    return lines


def render_card(value,destination):
    """Render a single text-only card in a caller-owned work directory."""
    text=card_text(value)
    path=Path(destination)
    if path.suffix.lower()!='.png':raise Rejected('图文卡输出文件类型无效')
    image=Image.new('RGB',(960,640),(18,28,49))
    draw=ImageDraw.Draw(image)
    # Locally drawn accent marks, not borrowed media or a third-party asset.
    draw.rounded_rectangle((32,32,928,608),radius=24,fill=(29,42,67),outline=(70,97,128),width=2)
    draw.rounded_rectangle((72,80,222,88),radius=3,fill=(250,181,75))
    draw.text((72,118),'小杂鱼 · 图文卡',font=_font(38),fill=(249,225,168))
    bodyfont=_font(44)
    lines=_wrap(draw,text,bodyfont,800)
    if len(lines)>7:raise Rejected('图文卡文字太长')
    y=230
    for line in lines:
        draw.text((72,y),line,font=bodyfont,fill=(244,247,251),stroke_width=0)
        y+=57
    draw.line((72,557,888,557),fill=(74,99,129),width=2)
    draw.text((72,572),'本地图文卡 · 未联网搜图/生图',font=_font(19),fill=(168,189,210))
    try:
        with path.open('xb') as stream:image.save(stream,format='PNG',optimize=True)
        if path.stat().st_size>MAX_CARD_BYTES:raise Rejected('图文卡文件超过3MB限制')
    except (Rejected,OSError,UnicodeError,ValueError):
        path.unlink(missing_ok=True)
        raise Rejected('图文卡生成失败，请换用更短的文字') from None
    return path


def validate_card(bot,path,job_id=None):
    """Check the actual file we send via OneBot file URI, not a model-supplied path."""
    image=bot.validate_output_path(path)
    if job_id is not None and not image.resolve().is_relative_to((bot.root/'work'/job_id).resolve()):
        raise Rejected('图文卡不属于当前任务')
    if image.suffix.lower()!='.png' or not 0<image.stat().st_size<=MAX_CARD_BYTES:
        raise Rejected('图文卡文件无效或超限')
    with Image.open(image) as decoded:
        if decoded.format!='PNG' or decoded.size!=(960,640):raise Rejected('图文卡像素或格式无效')
        decoded.verify()
    return image
