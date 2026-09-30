"""Quote parsing, consent, rendering, persistence and delivery; no live QQ access."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app import Bot
from protocol import normalize,should_handle
from quotes import render_card
from safe_net import Rejected
from store import Store
from task_dispatch import classify,worker_counts

LIMITS={'max_pending':40,'max_pending_per_user':3,'cooldown_seconds':0,'daily_requests_per_user':100,
        'max_input_chars':12000,'file_bytes':30*1024*1024,'extract_chars':40000,'work_retention_hours':24}
CFG={'admins':['11111'],'onebot':{'base_url':'http://127.0.0.1:3000','token':'fake'},
     'llm':{'base_url':'http://127.0.0.1:7866/v1','key_file':'unused','default_model':'test'},
     'limits':LIMITS,'group_require_at':True}

def event(text='计入',user='11111',group=33333,mid=1,reply=None,mentions=()):
    parts=([{'type':'reply','data':{'id':reply}}] if reply is not None else [])
    parts += [{'type':'at','data':{'qq':str(user_id)}} for user_id in mentions]
    parts += [{'type':'text','data':{'text':text}}]
    raw={'post_type':'message','message_type':'group','self_id':99999,'user_id':int(user),
         'group_id':group,'message_id':mid,'message':parts}
    return normalize(raw)

class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.cfg=copy.deepcopy(CFG)
        self.bot=Bot(self.root,lambda:self.cfg);self.bot.ob=Mock();self.bot.ob.send.return_value={'message_id':6}
        self.bot.ob.call.return_value={'message_type':'group','group_id':33333,'user_id':22222,
            'sender':{'nickname':'测试群友'},'time':int(time.time()),
            'message':[{'type':'text','data':{'text':'今天天气很好，我们一起出门吧。'}}]}
        self.bot.llm=Mock()
    def tearDown(self):
        self.bot.store.db.close();self.temp.cleanup()
    def job(self,e):
        ident=self.bot.store.accept(e,LIMITS)
        self.assertIsNotNone(ident)
        return ident
    def capture(self,e=None):
        e=e or event(reply=9001)
        return self.bot.process(e,self.job(e))

    def test_disabled_by_default_does_not_capture_or_query(self):
        e=event(reply=9001);q=event('语录',user='33333',mentions=('22222',),mid=2)
        self.assertFalse(should_handle(e,self.cfg,self.bot.store))
        self.assertFalse(should_handle(q,self.cfg,self.bot.store))
        self.assertIn('关闭',self.bot.process(event('/语录',mid=3),'status')[0]['text'])
        self.assertIn('语录 ✗',self.bot.process(event('/能力',mid=4),'caps')[0]['text'])
        self.bot.process(event('/开 语录',mid=5),'enable')
        self.assertTrue(should_handle(e,self.cfg,self.bot.store))
        self.assertTrue(should_handle(q,self.cfg,self.bot.store))
        self.assertEqual(classify(q),'quote')
        self.assertEqual(worker_counts()['quote'],2)
        self.assertFalse(should_handle(event(reply=9001,user='33333'),self.cfg,self.bot.store))

    def test_admin_replies_capture_then_random_image_sends_once_without_model(self):
        self.bot.store.set('g:33333','cap:quotes',True)
        captured=self.capture()[0]['text'];self.assertIn('已计入',captured)
        quote=self.bot.store.quote_by_source('g:33333','9001');self.assertIsNotNone(quote)
        q=event('语录',user='33333',mentions=('22222',),mid=2);ident=self.job(q)
        result=self.bot.process(q,ident)
        self.assertEqual(result[0]['kind'],'quote_card')
        with Image.open(result[0]['path']) as image:
            self.assertEqual(image.format,'PNG');self.assertGreater(image.width,700)
        self.bot.deliver(q,ident,result)
        scope,parts=self.bot.ob.send.call_args.args
        self.assertEqual(scope,'g:33333');self.assertEqual([x['type'] for x in parts],['image'])
        self.assertTrue(parts[0]['data']['file'].startswith('file:///'))
        self.bot.llm.chat.assert_not_called()

    def test_source_must_be_same_group_and_real_author(self):
        self.bot.store.set('g:33333','cap:quotes',True)
        self.bot.ob.call.return_value['group_id']=44444
        with self.assertRaises(Rejected):self.capture()
        self.assertIsNone(self.bot.store.quote_by_source('g:33333','9001'))
        self.bot.ob.call.return_value['group_id']=33333
        self.bot.ob.call.return_value['user_id']=99999
        with self.assertRaises(Rejected):self.capture(event(reply=9001,mid=2))

    def test_source_content_and_fetch_failures_do_not_store(self):
        self.bot.store.set('g:33333','cap:quotes',True)
        self.bot.ob.call.side_effect=RuntimeError('timeout')
        with self.assertRaises(Rejected):self.capture()
        self.bot.ob.call.side_effect=None
        for i,value in enumerate(('密码：hunter2','查看 https://site.example/?token=secret'),2):
            self.bot.ob.call.return_value['message']=[{'type':'text','data':{'text':value}}]
            with self.assertRaises(Rejected):self.capture(event(reply=9001,mid=i))
        self.assertIsNone(self.bot.store.quote_by_source('g:33333','9001'))

    def test_unique_source_across_parallel_admins_and_across_groups(self):
        self.cfg['admins'].append('55555');self.bot.store.set('g:33333','cap:quotes',True)
        e1=event(reply=9001,mid=1);e2=event(user='55555',reply=9001,mid=2)
        ids=[self.job(e) for e in (e1,e2)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            outputs=list(executor.map(lambda p:self.bot.process(*p),[(e1,ids[0]),(e2,ids[1])]))
        self.assertEqual(sum('已计入' in item[0]['text'] for item in outputs),1)
        self.assertEqual(sum('已经计入' in item[0]['text'] for item in outputs),1)
        self.assertEqual(len(list((self.root/'state/quote_cards').glob('*.png'))),1)
        self.bot.store.set('g:44444','cap:quotes',True)
        self.bot.ob.call.return_value['group_id']=44444
        e3=event(reply=9001,group=44444,mid=3)
        self.assertIn('已计入',self.capture(e3)[0]['text'])

    def test_subject_optout_deletes_card_blocks_pending_delivery_and_future_capture(self):
        self.bot.store.set('g:33333','cap:quotes',True);self.capture()
        q=event('语录',user='44444',mentions=('22222',),mid=2);result=self.bot.process(q,self.job(q))
        image=Path(result[0]['path']);self.assertTrue(image.is_file())
        leave=event('/语录 退出',user='22222',mid=3)
        self.assertIn('已退出',self.bot.process(leave,self.job(leave))[0]['text'])
        self.assertFalse(image.exists())
        with self.assertRaises(Rejected):self.bot.deliver(q,'pending-quote',result)
        self.bot.ob.send.assert_not_called()
        self.assertIn('退出',self.capture(event(reply=9002,mid=4))[0]['text'])

    def test_delete_authorization_and_no_replay(self):
        self.bot.store.set('g:33333','cap:quotes',True)
        capture=event(reply=9001);ident=self.job(capture)
        result=self.bot.process(capture,ident)
        quote_id=result[0]['text'].split('编号：')[1].split('。')[0]
        unknown=event('/重发 '+ident,mid=2)
        self.bot.store.update(ident,'failed',output=result)
        self.assertIn('不可通过',self.bot.process(unknown,'replay')[0]['text'])
        other=event('/语录 删除 '+quote_id,user='44444',mid=3)
        self.assertIn('未找到',self.bot.process(other,'denied')[0]['text'])
        subject=event('/语录 删除 '+quote_id,user='22222',mid=4)
        self.assertIn('已删除',self.bot.process(subject,'own')[0]['text'])
        self.assertIsNone(self.bot.store.quote_by_source('g:33333','9001'))

    def test_card_validation_rejects_outside_and_missing_paths(self):
        from quotes import validate_card
        external=self.root/'secret.png';external.write_bytes(b'fake')
        with self.assertRaises(Rejected):validate_card(self.bot,external)
        card=self.root/'state/quote_cards'/'not-there.png'
        with self.assertRaises(Rejected):validate_card(self.bot,card)

    def test_card_generation_does_not_need_qq_or_model(self):
        p=self.root/'card.png';render_card('小鱼今天不摸鱼。','测试群友',time.time(),p)
        self.assertLess(p.stat().st_size,512*1024)
        with Image.open(p) as image:
            self.assertEqual(image.mode,'P')
            self.assertEqual(image.width,840)
        render_card('群'*240,'测试群友',time.time(),self.root/'long.png')
        self.bot.ob.send.assert_not_called();self.bot.llm.chat.assert_not_called()

if __name__=='__main__':unittest.main()
