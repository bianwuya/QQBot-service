"""Explicit, previously verified vision-model routing; no text-model guessing.

Model IDs are opt-in administrator configuration populated only after real
synthetic-image checks. Model text never authorizes QQ actions or file reads.
"""
import base64
import threading
from pathlib import Path

from model_router import ModelFailure
from safe_net import Rejected

NO_VISION='这张图我现在没法可靠读取，不能凭空猜图。请稍后重试，或把关键信息发成文字。'
_NO_IMAGE_PHRASES=('无法查看图片','无法看到图片','不能查看图片','看不到图片内容',
                   '没有收到图片','没有提供图片','无法识别到图片','cannot view the image',
                   'i cannot see the image','no image provided')


def verified_models(config):
    cfg=config.get('vision')
    if config.get('vision_reply_enabled') is not True or not isinstance(cfg,dict):return []
    values=cfg.get('verified_models')
    if not isinstance(values,list):return []
    return list(dict.fromkeys(x for x in values[:2] if isinstance(x,str) and
                              2<=len(x)<=100 and '\n' not in x and '\r' not in x))


class VisionClient:
    def __init__(self,llm):self.llm=llm;self.slots=threading.BoundedSemaphore(1)

    def chat(self,config,messages,images,max_tokens=380,preferred_model=None):
        models=verified_models(config)
        if preferred_model in models:models=[preferred_model]+[x for x in models if x!=preferred_model]
        if not models:raise Rejected('尚无通过看图验证的视觉模型')
        if not 1<=len(images)<=2:raise Rejected('一次只支持1至2张图片')
        multimodal=[]
        for path in images:
            raw=Path(path).read_bytes()
            if not 100<len(raw)<=3*1024*1024 or not raw.startswith(b'\xff\xd8\xff'):
                raise Rejected('图片编码超过限制或内容不是安全的 JPEG')
            multimodal.append({'type':'image_url','image_url':
                {'url':'data:image/jpeg;base64,'+base64.b64encode(raw).decode('ascii')}})
        prepared=[]
        for item in messages:
            if item.get('role') not in ('system','user','assistant') or not isinstance(item.get('content'),str):
                raise Rejected('视觉请求的对话格式无效')
            prepared.append({'role':item['role'],'content':item['content']})
        user_positions=[i for i,x in enumerate(prepared) if x['role']=='user']
        if not user_positions:raise Rejected('视觉请求缺少问题')
        # Attach image data only once, to the most recent user turn.
        index=user_positions[-1]
        prepared[index]['content']=[{'type':'text','text':prepared[index]['content']}]+multimodal
        last=None
        for model in models:
            try:
                with self.slots:
                    data=self.llm.request('/chat/completions',
                        {'model':model,'messages':prepared,'stream':False,
                         'max_tokens':max(100,min(750,int(max_tokens)))},timeout=(5,50))
                choices=data.get('choices') or []
                answer=(choices[0].get('message') or {}).get('content') if choices else None
                if not isinstance(answer,str) or not answer.strip():
                    raise Rejected('视觉模型返回空答案')
                if any(text in answer.lower() for text in _NO_IMAGE_PHRASES):
                    raise Rejected('视觉模型表示没有看到图片')
                if choices[0].get('finish_reason')=='length':
                    answer+='\n[视觉模型输出达到上限，可能不完整。]'
                return answer.strip()
            except (Rejected,ModelFailure) as ex:
                last=ex
                continue  # Only OTHER pre-verified models, never arbitrary text models.
        raise Rejected('已验证的视觉模型暂不可用，不能猜测图片内容') from last
