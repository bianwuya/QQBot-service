"""Outbound is entirely mocked here; real admin-private NapCat test is separate."""
from pathlib import Path
from PIL import Image

from app import GroupChatOutput
from image_reply import render_card,validate_card
from protocol import DeliveryUnknown,normalize
from safe_net import Rejected
from test_bot import Fixture,LIMITS,event

class ImageReplyTest(Fixture):
    def setUp(self):
        super().setUp()
        self.bot.ob.send.return_value={'message_id':888}

    def test_off_by_default_and_bad_input(self):
        e=self.e(group=None,text='/图文卡 测试')
        self.assertIn('尚未启用',self.bot.process(e,'card-off')[0]['text'])
        self.assertFalse((self.root/'work/card-off/reply-card.png').exists())
        self.cfg['image_reply_enabled']=True
        with self.assertRaisesRegex(Rejected,'用法'):self.bot.process(self.e(group=None,text='/图文卡'), 'card-empty')
        with self.assertRaises(Rejected):render_card('字'*181,self.dir/'too-long.png')
        with self.assertRaises(Rejected):render_card('一\n二\n三\n四\n五\n六',self.dir/'too-tall.png')
        self.bot.store.set('p:22222','cap:image_card',False)
        self.assertIn('未启用',self.bot.process(e,'card-cap-off')[0]['text'])
        self.bot.ob.send.assert_not_called()

    def test_private_text_plus_real_image_segment_single_receipt(self):
        self.cfg['image_reply_enabled']=True
        e=self.e(group=None,text='/图文卡 今天记得喝水，不用联网搜图。')
        ident=self.bot.store.accept(e,LIMITS)
        output=self.bot.process(e,ident)
        self.assertEqual(len(output),1)
        self.assertEqual(output[0]['kind'],'image_card')
        with Image.open(output[0]['path']) as image:
            self.assertEqual(image.size,(960,640));self.assertEqual(image.format,'PNG')
        self.bot.deliver(e,ident,output)
        self.assertEqual(self.bot.store.receipts(ident),{0:'sent'})
        self.bot.ob.send.assert_called_once()
        scope,segments=self.bot.ob.send.call_args.args
        self.assertEqual(scope,'p:22222')
        self.assertEqual([x['type'] for x in segments],['text','image'])
        self.assertTrue(segments[1]['data']['file'].startswith('file:///'))
        self.bot.llm.chat.assert_not_called();self.bot.llm.request.assert_not_called()

    def test_group_reply_at_text_image_order_and_cooldown(self):
        self.cfg['image_reply_enabled']=True
        blocked=self.bot.process(self.e(group=33333,text='/图文卡 未授权'), 'card-group-blocked')
        self.assertIn('未启用',blocked[0]['text'])
        self.bot.store.set('g:33333','cap:image_card',True)
        e=normalize(event(user='22222',group=33333,mid=345,text='/图文卡 你好',segments=[
            {'type':'at','data':{'qq':'99999'}},{'type':'text','data':{'text':'/图文卡 你好'}}]))
        ident=self.bot.store.accept(e,LIMITS)
        output=self.bot.process(e,ident)
        self.bot.ob.call.return_value={'message_type':'group','group_id':33333,'user_id':22222}
        self.bot.deliver(e,ident,output)
        self.assertEqual([x['type'] for x in self.bot.ob.send.call_args.args[1]],
                         ['reply','at','text','image'])
        later=normalize(event(user='22222',group=33333,mid=346,text='/图文卡 再来一张'))
        self.assertIn('冷却',self.bot.process(later,'card-later')[0]['text'])
        self.assertFalse((self.root/'work/card-later/reply-card.png').exists())

    def test_switch_off_before_delivery_and_other_job_path_rejected(self):
        self.cfg['image_reply_enabled']=True
        e=self.e(group=None,text='/图文卡 这是一段文字')
        ident=self.bot.store.accept(e,LIMITS)
        output=self.bot.process(e,ident)
        self.cfg['image_reply_enabled']=False
        with self.assertRaisesRegex(Rejected,'已关闭'):self.bot.deliver(e,ident,output)
        self.bot.ob.send.assert_not_called()
        self.cfg['image_reply_enabled']=True
        other=self.root/'work'/'someone-else';other.mkdir()
        sample=render_card('不是这个任务的卡片',other/'reply-card.png')
        with self.assertRaisesRegex(Rejected,'不属于当前任务'):validate_card(self.bot,sample,ident)

    def test_unknown_receipt_never_automatically_replays_card(self):
        self.cfg['image_reply_enabled']=True
        e=self.e(user='11111',group=None,text='/图文卡 不要重复投递')
        ident=self.bot.store.accept(e,LIMITS)
        output=self.bot.process(e,ident)
        self.bot.ob.send.side_effect=DeliveryUnknown('发送结果不明')
        with self.assertRaises(DeliveryUnknown):self.bot.deliver(e,ident,output)
        self.assertEqual(self.bot.store.receipts(ident),{0:'unknown'})
        self.bot.store.update(ident,'unknown',output=output)
        result=self.bot.process(self.e(user='11111',group=None,text='/重发 '+ident),'replay-attempt')
        self.assertIn('不可通过',result[0]['text'])
        self.assertEqual(self.bot.ob.send.call_count,1)

if __name__=='__main__':
    import unittest;unittest.main()
