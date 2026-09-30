"""Vision integration: mocked model/OneBot; real endpoint checked separately."""
import base64
import tempfile
from pathlib import Path
from unittest.mock import Mock
from PIL import Image

from app import GroupChatOutput
from protocol import normalize
from safe_net import Rejected
from vision_client import NO_VISION,VisionClient,verified_models
from test_bot import Fixture,event

FID='b'*32+'.png'

class VisionModelTest(Fixture):
    def setUp(self):
        super().setUp()
        self.cfg['vision_reply_enabled']=True
        self.cfg['vision']={'verified_models':['verified-vl'],
                            'napcat_image_roots':[str(self.root/'napcat-cache')]}
        cache=self.root/'napcat-cache';cache.mkdir()
        self.photo=cache/'sample.png';Image.new('RGB',(420,200),'blue').save(self.photo)
        self.bot.vision=VisionClient(self.bot.llm)
        self.bot.ob.call.side_effect=lambda action,payload,timeout=None:(
            {'file':str(self.photo)} if action=='get_image' else {})
        self.bot.llm.request.return_value={'choices':[{'message':{'content':'这张图有蓝色块。'},'finish_reason':'stop'}]}

    def raw_image(self,group=None,at=False,text=''):
        parts=[]
        if at:parts.append({'type':'at','data':{'qq':'99999'}})
        if text:parts.append({'type':'text','data':{'text':text}})
        parts.append({'type':'image','data':{'file':FID,'url':'http://attacker.invalid/'}})
        return normalize(event(user='22222',group=group,mid=923,segments=parts))

    def test_private_image_only_routes_to_verified_model_with_pixels(self):
        e=self.raw_image(group=None)
        self.assertEqual(e['image_count'],1)
        answer=self.bot.process(e,'vision-private')
        self.assertEqual(answer[0]['text'],'这张图有蓝色块。')
        self.bot.llm.chat.assert_not_called()
        call=self.bot.llm.request.call_args
        self.assertEqual(call.args[1]['model'],'verified-vl')
        parts=call.args[1]['messages'][-1]['content']
        self.assertEqual([x['type'] for x in parts],['text','image_url'])
        encoded=parts[1]['image_url']['url']
        self.assertTrue(base64.b64decode(encoded.split(',')[-1]).startswith(b'\xff\xd8\xff'))
        self.assertNotIn('attacker.invalid',str(call.args[1]))
        self.assertEqual(len(self.bot.store.context('p:22222','22222')),2)

    def test_group_visual_uses_role_prompt_not_text_router_or_actions(self):
        self.bot.store.set('g:33333','cap:vision',True)
        e=self.raw_image(group=33333,at=True,text='图里是什么')
        self.assertTrue(e['at'])
        answer=self.bot.process(e,'vision-group')
        self.assertIsInstance(answer,GroupChatOutput)
        self.assertEqual(answer[0]['text'],'这张图有蓝色块。')
        args=self.bot.llm.request.call_args.args[1]
        self.assertIn('小杂鱼',args['messages'][0]['content'])
        self.bot.llm.chat.assert_not_called()
        self.assertFalse(any(x['kind']=='share_action' for x in answer))

    def test_group_pixels_require_opt_in(self):
        e=self.raw_image(group=33333,at=True,text='图里是什么')
        self.bot.process(e,'group-no-opt-in')
        self.assertNotIn('get_image',[x.args[0] for x in self.bot.ob.call.call_args_list])
        self.bot.llm.request.assert_not_called()

    def test_model_unverified_or_failed_honestly_without_default_model(self):
        e=self.raw_image(group=None)
        self.cfg['vision']['verified_models']=[]
        self.assertEqual(self.bot.process(e,'no-model')[0]['text'],NO_VISION)
        self.bot.llm.request.assert_not_called();self.bot.llm.chat.assert_not_called()
        self.cfg['vision']['verified_models']=['verified-vl']
        self.bot.llm.request.side_effect=Rejected('gateway failed')
        self.assertEqual(self.bot.process(e,'model-down')[0]['text'],NO_VISION)
        self.bot.llm.chat.assert_not_called()

    def test_quoted_image_question_off_does_not_go_to_text_model(self):
        self.cfg['vision_reply_enabled']=False
        e=normalize(event(user='22222',group=None,mid=924,segments=[
            {'type':'reply','data':{'id':'923'}},
            {'type':'text','data':{'text':'这张图是什么'}}]))
        self.bot.ob.call.return_value={'message_type':'private','user_id':22222,
              'message':[{'type':'image','data':{'file':FID}}]}
        out=self.bot.process(e,'vision-off-quoted')
        self.assertEqual(out[0]['text'],NO_VISION)
        self.bot.llm.chat.assert_not_called();self.bot.llm.request.assert_not_called()

    def test_quote_wrong_group_never_downloaded(self):
        self.bot.store.set('g:33333','cap:vision',True)
        e=normalize(event(user='22222',group=33333,mid=924,segments=[
            {'type':'at','data':{'qq':'99999'}}, {'type':'reply','data':{'id':'923'}},
            {'type':'text','data':{'text':'这张图是什么'}}]))
        self.bot.ob.call.side_effect=lambda action,payload,timeout=None:({
            'message_type':'group','group_id':44444,
            'message':[{'type':'image','data':{'file':FID}}]} if action=='get_msg' else
            {'file':str(self.photo)})
        answer=self.bot.process(e,'quote-wrong-scope')
        self.assertEqual(answer[0]['text'],NO_VISION)
        self.assertNotIn('get_image',[c.args[0] for c in self.bot.ob.call.call_args_list])
        self.bot.llm.chat.assert_not_called();self.bot.llm.request.assert_not_called()

    def test_only_verified_models_can_fail_over(self):
        self.cfg['vision']['verified_models']=['broken-vl','verified-vl']
        self.bot.llm.request.side_effect=[Rejected('broken'),
             {'choices':[{'message':{'content':'第二个模型确实看到了蓝色块'}}]}]
        answer=self.bot.process(self.raw_image(group=None),'two-verified')
        self.assertIn('第二个模型',answer[0]['text'])
        self.assertEqual([call.args[1]['model'] for call in self.bot.llm.request.call_args_list],
                         ['broken-vl','verified-vl'])
        self.bot.llm.chat.assert_not_called()

    def test_vision_off_keeps_original_private_cannot_see_fallback(self):
        self.cfg['vision_reply_enabled']=False
        output=self.bot.process(self.raw_image(group=None),'vision-off')
        self.assertIn('读不了图片',output[0]['text'])
        self.bot.llm.request.assert_not_called()

if __name__=='__main__':
    import unittest;unittest.main()
