"""Privacy routing and per-scope video suppression regressions; no QQ/network calls."""
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Bot
from media import video_identity
from protocol import DeliveryUnknown,normalize,should_handle
from safe_net import Rejected
from store import Store

LIMITS={'max_pending':40,'max_pending_per_user':3,'cooldown_seconds':0,'daily_requests_per_user':100,
        'max_input_chars':12000,'file_bytes':30*1024*1024,'extract_chars':40000,'work_retention_hours':24}
CFG={'admins':['11111'],'onebot':{'base_url':'http://127.0.0.1:3000','token':'test'},
     'llm':{'base_url':'http://127.0.0.1:7866/v1','key_file':'unused','default_model':'test'},
     'limits':LIMITS,'group_require_at':True}
VIDEO='https://www.bilibili.com/video/BV1aa411c7mD'

def event(text,owner='22222',group=33333,mid=1,segments=None):
    raw={'post_type':'message','self_id':99999,'user_id':int(owner),'message_id':mid,
         'message':segments if segments is not None else [{'type':'text','data':{'text':text}}]}
    if group:raw['group_id']=group
    return normalize(raw)

class PrivacyVideo(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.cfg=copy.deepcopy(CFG)
        self.bot=Bot(self.root,lambda:self.cfg);self.bot.ob=Mock();self.bot.ob.send.return_value={'message_id':100}
        self.bot.llm=Mock()
    def tearDown(self):
        self.bot.store.db.close();self.temp.cleanup()
    def enqueue(self,e):return self.bot.store.accept(e,LIMITS)

    def test_memory_status_and_view_only_go_to_requesting_admin_private_chat(self):
        self.bot.store.record_memory_interaction('g:33333','22222')
        for mid,text in enumerate(('/记忆 状态','/记忆 查看 22222','/记忆 帮助'),1):
            e=event(text,owner='11111',mid=mid);ident=self.enqueue(e)
            outputs=self.bot.process(e,ident)
            self.assertEqual(outputs[0]['recipient'],'p:11111')
            self.bot.deliver(e,ident,outputs)
        self.assertEqual([call.args[0] for call in self.bot.ob.send.call_args_list],['p:11111']*3)

    def test_memory_legacy_sensitive_rows_are_hidden(self):
        e=event('/记忆 查看 22222',owner='11111')
        self.bot.store.record_memory_interaction(e['scope'],'22222')
        self.bot.store.add_memory(e['scope'],'22222',{'type':'preference','content':'用户喜欢 password=hunter2','confidence':.9})
        text=self.bot.process(e,'memory-safe')[0]['text']
        self.assertIn('[内容已隐藏]',text);self.assertNotIn('hunter2',text)

    def test_memory_delivery_failure_and_revocation_have_no_group_fallback(self):
        e=event('/记忆 状态',owner='11111');ident=self.enqueue(e)
        self.bot.ob.send.side_effect=Rejected('私聊不可达')
        self.bot._run_job(self.bot.store.take('tool'))
        self.assertEqual([call.args[0] for call in self.bot.ob.send.call_args_list],['p:11111'])
        self.cfg['admins']=[]
        self.bot.ob.send.reset_mock();self.bot.ob.send.side_effect=None
        with self.assertRaises(Rejected):self.bot.deliver(e,'revoked',self.bot.private_memory(e,'秘密'))
        self.bot.ob.send.assert_not_called()

    def test_memory_old_group_outbox_cannot_be_replayed(self):
        old=event('/记忆 查看 22222',owner='11111');ident=self.enqueue(old)
        self.bot.store.update(ident,'unknown',output=[{'kind':'text','text':'旧版群记忆'}])
        e=event('/重发 '+ident,owner='11111',mid=2)
        result=self.bot.process(e,'replay')[0]['text']
        self.assertIn('不可通过',result);self.assertNotIn('旧版群记忆',result)

    def test_platform_switches_are_independent_and_master_wins(self):
        scope='g:33333'
        self.assertTrue(should_handle(event(VIDEO),self.cfg,self.bot.store))
        self.bot.process(event('/关 B站转发',owner='11111',mid=8),'switch')
        self.assertFalse(should_handle(event(VIDEO),self.cfg,self.bot.store))
        self.assertTrue(should_handle(event('https://www.xiaohongshu.com/explore/abcdef123456abcdef123456'),self.cfg,self.bot.store))
        self.assertTrue(should_handle(event('https://www.douyin.com/video/1234567890'),self.cfg,self.bot.store))
        self.bot.process(event('/关 视频',owner='11111',mid=9),'master')
        self.assertFalse(should_handle(event('https://www.douyin.com/video/1234567890'),self.cfg,self.bot.store))
        self.bot.process(event('/开 B站转发',owner='11111',mid=10),'child')
        self.assertFalse(should_handle(event(VIDEO),self.cfg,self.bot.store))
        self.assertTrue(should_handle(event(VIDEO,group=44444),self.cfg,self.bot.store))
        self.assertIn('B站转发 ✗',self.bot.process(event('/能力',owner='11111',mid=11),'caps')[0]['text'])

    def test_disabled_json_share_is_silent_and_mixed_share_uses_enabled_platform(self):
        self.bot.store.set('g:33333','cap:video:bilibili',False)
        e=event('',segments=[{'type':'json','data':{'data':'{"url":"'+VIDEO+'"}'}}])
        self.assertFalse(should_handle(e,self.cfg,self.bot.store))
        self.assertEqual(self.bot.process(e,'json-disabled'),[])
        self.bot.store.set('g:33333','cap:videos',False)
        two=event(VIDEO+' https://www.douyin.com/video/1234567890',mid=21)
        self.assertFalse(should_handle(two,self.cfg,self.bot.store))
        self.assertEqual(self.bot.process(two,'two-disabled'),[])
        self.bot.store.set('g:33333','cap:videos',True)
        mixed=event(VIDEO+' https://www.douyin.com/video/1234567890',mid=2)
        with patch('app.video_identity',return_value=('douyin','unique')),patch('app.get_video') as get_video:
            get_video.side_effect=lambda url,directory,cfg: directory/'stub.mp4'
            result=self.bot.process(mixed,'mixed')
        self.assertEqual(result[0]['platform'],'douyin')
        self.assertIn('douyin.com',get_video.call_args.args[0])

    def test_canonical_short_and_long_links_share_an_identity(self):
        with patch('media.resolve_public',return_value=VIDEO):
            self.assertEqual(video_identity('https://b23.tv/abc')[1],video_identity(VIDEO+'?tracking=1')[1])

    def test_two_users_in_one_group_send_once_other_group_is_independent(self):
        calls=[]
        def get_video(url,directory,cfg):
            calls.append(directory);directory.mkdir(exist_ok=True)
            file=directory/'stub.mp4';file.write_bytes(b'video');return file
        e1=event(VIDEO,mid=1);e2=event(VIDEO,owner='44444',mid=2)
        with patch('app.video_identity',return_value=('bilibili','same-key')),patch('app.get_video',side_effect=get_video):
            first=self.enqueue(e1);second=self.enqueue(e2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                a,b=list(pool.map(lambda pair:self.bot.process(*pair),[(e1,first),(e2,second)]))
            self.assertEqual([len(a),len(b)].count(1),1)
            for e,ident,output in ((e1,first,a),(e2,second,b)):self.bot.deliver(e,ident,output)
            self.assertEqual(len(calls),1);self.assertEqual(self.bot.ob.send.call_count,1)
            e3=event(VIDEO,group=44444,mid=3)
            self.assertEqual(len(self.bot.process(e3,self.enqueue(e3))),1)

    def test_confirmed_processing_failure_releases_claim_unknown_delivery_keeps_it(self):
        e1=event(VIDEO,mid=1);e2=event(VIDEO,owner='44444',mid=2)
        with patch('app.video_identity',return_value=('bilibili','same-key')):
            with patch('app.get_video',side_effect=Rejected('无法解析')):
                with self.assertRaises(Rejected):self.bot.process(e1,self.enqueue(e1))
            path=self.root/'work'/'stub.mp4';path.write_bytes(b'video')
            with patch('app.get_video',return_value=path):
                ident=self.enqueue(e2);result=self.bot.process(e2,ident)
            self.bot.ob.send.side_effect=DeliveryUnknown('超时')
            with self.assertRaises(DeliveryUnknown):self.bot.deliver(e2,ident,result)
            e3=event(VIDEO,owner='55555',mid=3)
            with patch('app.get_video',return_value=path) as download:
                self.assertEqual(self.bot.process(e3,self.enqueue(e3)),[])
                download.assert_not_called()

    def test_switch_off_after_processing_prevents_video_delivery(self):
        e=event(VIDEO);ident=self.enqueue(e)
        path=self.root/'work'/'stub.mp4';path.write_bytes(b'video')
        with patch('app.video_identity',return_value=('bilibili','same-key')),patch('app.get_video',return_value=path):
            output=self.bot.process(e,ident)
        self.bot.store.set(e['scope'],'cap:video:bilibili',False)
        with self.assertRaises(Rejected):self.bot.deliver(e,ident,output)
        self.bot.ob.send.assert_not_called()

    def test_window_persists_across_reopen_and_expires(self):
        e=event(VIDEO);ident=self.enqueue(e)
        self.assertTrue(self.bot.store.claim_video(e['scope'],'hash',ident))
        self.bot.store.update(ident,'done')
        reopened=Store(self.root/'state/bot.sqlite3')
        try:
            self.assertFalse(reopened.claim_video(e['scope'],'hash','next'))
            self.assertTrue(reopened.claim_video(e['scope'],'hash','next',now=time.time()+601))
        finally:reopened.db.close()

if __name__=='__main__':unittest.main()
