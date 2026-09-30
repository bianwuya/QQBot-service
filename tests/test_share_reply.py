"""No live QQ traffic: all group and private send endpoints are mocked."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app import GroupChatOutput
from protocol import normalize, should_handle
from safe_net import Rejected
from share_reply import ReplyPolicy,parse_actions,requested
from test_bot import Fixture,LIMITS,event


class ShareReplyRules(Fixture):
    def setUp(self):
        super().setUp()
        self.cfg['share_reply_enabled']=True
        self.bot.ob.send.return_value={'message_id':77}
        self.bot.share_reply.rng=lambda:.99

    def at_event(self,text='你好',mid=123456,group=33333):
        return normalize(event(text=text,mid=mid,group=group,segments=[
            {'type':'at','data':{'qq':'99999'}}, {'type':'text','data':{'text':text}}]))

    def test_new_abilities_are_globally_gated_and_default_off(self):
        e=self.e(text='平安到家')
        self.assertFalse(should_handle(e,self.cfg,self.bot.store))
        self.cfg['share_reply_enabled']=False
        self.bot.share_reply.rng=lambda:0
        self.assertFalse(self.bot.share_reply.random_pick(e,self.cfg))
        self.bot.ingest(event(mid=89911,text='没艾特的新消息'))
        self.assertIsNone(self.bot.store.take('chat'))
        self.assertEqual(self.bot.group_memory.day_lines('g:33333'),[])

    def test_random_two_percent_only_text_and_allowed_group(self):
        policy=self.bot.share_reply
        e=self.e(text='今天天气怎么样')
        policy.rng=lambda:.019
        self.assertTrue(policy.random_pick(e,self.cfg))
        policy.rng=lambda:.02
        self.assertFalse(policy.random_pick(e,self.cfg))
        policy.rng=lambda:0
        self.assertFalse(policy.random_pick(self.e(text='/帮助'),self.cfg))
        self.assertFalse(policy.random_pick(self.e(text='https://example.org'),self.cfg))
        self.assertFalse(policy.random_pick(self.e(segments=[{'type':'image','data':{'file':'x'}}]),self.cfg))
        self.assertFalse(policy.random_pick(self.e(segments=[{'type':'file','data':{'id':'f'}}]),self.cfg))
        self.assertFalse(policy.random_pick(self.at_event(),self.cfg))
        self.bot.store.set('g:33333','cap:chat',False)
        self.assertFalse(policy.random_pick(e,self.cfg))
        self.bot.store.set('g:33333','cap:chat',True)
        self.bot.store.set('g:33333','share_reply_enabled',False)
        self.assertFalse(policy.random_pick(e,self.cfg))

    def test_random_fallback_does_not_bypass_keyword_cooldown_or_disabled_quote(self):
        self.bot.share_reply.rng=lambda:0
        self.bot.store.set('g:33333','kw_cooldown_until',time.time()+60)
        self.bot.ingest(event(mid=88001,text='色色'))
        self.assertIsNone(self.bot.store.take('chat'))
        self.bot.ingest(event(mid=88002,text='语录',segments=[
            {'type':'at','data':{'qq':'55555'}},
            {'type':'text','data':{'text':'语录'}}]))
        self.assertIsNone(self.bot.store.take('chat'))

    def test_random_ingest_sets_queued_marker_and_cannot_use_model_actions(self):
        self.bot.share_reply.rng=lambda:0
        raw=event(mid=77711,text='普通群消息')
        self.bot.ingest(raw)
        job=self.bot.store.take('chat')
        self.assertIsNotNone(job)
        e=json.loads(job['payload'])
        self.assertTrue(e['random_reply'])
        self.assertFalse(e['at'])
        self.bot.llm.chat.return_value='我先听听。[DELETE_SETTING:小花]'
        self.bot.share_reply.rng=lambda:.99  # no post-reply poke in this test
        outputs=self.bot.process(e,job['id'])
        self.assertIsInstance(outputs,GroupChatOutput)
        self.assertFalse(any(o['kind']=='share_action' for o in outputs))
        self.assertFalse(any(o.get('at_user') for o in outputs))
        self.assertNotIn('DELETE_SETTING',str(outputs))
        self.assertNotIn('当前群友',self.bot.llm.chat.call_args.args[1][0]['content'])
        self.bot.ob.send.assert_not_called()

    def test_learning_requires_real_at_and_filters_bystander_secrets(self):
        e=self.e(text='叫我小华')
        self.assertTrue(self.bot.group_memory.observe(dict(e,key='ordinary')))
        self.assertEqual(self.bot.store.db.execute("SELECT count(*) FROM share_notes WHERE kind='alias'").fetchone()[0],0)
        secret=self.e(text='token=private-value')
        self.assertFalse(self.bot.group_memory.observe(dict(secret,key='secret')))
        self.assertNotIn('private-value',str(self.bot.group_memory.day_lines(e['scope'])))
        at=self.at_event('叫我小华')
        self.assertTrue(self.bot.group_memory.observe(dict(at,key='learned')))
        self.assertEqual(self.bot.store.db.execute("SELECT count(*) FROM share_notes WHERE kind='alias'").fetchone()[0],1)

    def test_keyword_chat_also_uses_share_style_without_model_actions(self):
        e=self.at_event('色色')
        self.bot.llm.chat.return_value='那也别乱来。[ESSENCE]'
        output=self.bot.process(e,'keyword')
        self.assertTrue(output[0].get('share_chat'))
        self.assertEqual(output[0]['at_user'],e['owner'])
        self.assertFalse(any(o['kind']=='share_action' and o['action']['type']=='essence' for o in output))
        self.assertNotIn('ESSENCE',str(output))

    def test_poke_after_random_reply_is_outbox_action_not_text(self):
        e=self.e(mid=123456,text='有人讨论新游戏')
        self.bot.share_reply.rng=lambda:0
        outputs=self.bot.share_reply.format(e,'随口接一句。',[],poke_probability=.15)
        self.assertEqual([o['kind'] for o in outputs],['text','share_action'])
        self.assertNotIn('at_user',outputs[0])
        self.assertEqual(outputs[1]['action']['type'],'poke')
        ident=self.bot.store.accept(e,LIMITS)
        self.bot.deliver(e,ident,GroupChatOutput(outputs))
        self.assertEqual(self.bot.store.receipts(ident),{0:'sent',1:'sent'})
        self.bot.ob.call.assert_called_once()
        self.assertEqual(self.bot.ob.call.call_args.args[0],'group_poke')

    def test_notice_poke_and_join_scope_and_cooldown(self):
        poke={'post_type':'notice','notice_type':'notify','sub_type':'poke','group_id':33333,
              'target_id':99999,'user_id':22222,'self_id':99999,'time':100}
        e=normalize(poke)
        self.assertEqual(e['notice'],'poke')
        self.assertFalse(should_handle(e,self.cfg,self.bot.store))
        self.assertEqual(normalize(poke)['key'],e['key'])
        wrong=dict(poke,target_id=11111)
        self.assertIsNone(normalize(wrong))
        self.assertIsNone(normalize(dict(poke,group_id=None)))
        self.assertIsNone(normalize(dict(poke,user_id=99999)))
        self.bot.share_reply.clock=lambda:1000
        first=self.bot.store.accept(e,LIMITS)
        output=self.bot.process(e,first)
        self.assertEqual(output[0]['at_user'],'22222')
        self.assertTrue(output[0]['share_chat'])
        self.assertEqual(self.bot.process(dict(e,key='next'),first),[])
        welcome=normalize({'post_type':'notice','notice_type':'group_increase','group_id':33333,
                           'user_id':22222,'self_id':99999,'time':101})
        self.assertEqual(welcome['notice'],'welcome')
        self.assertEqual(self.bot.process(welcome,'welcome')[0]['at_user'],'22222')
        self.assertIsNone(normalize({'post_type':'notice','notice_type':'group_increase',
                                     'group_id':33333,'user_id':99999,'self_id':99999,'time':101}))
        self.bot.ob.send.assert_not_called()

    def test_split_and_half_quote_only_first_message_and_receipts(self):
        e=self.at_event('请解释一下',mid=123456)
        self.bot.share_reply.rng=lambda:0
        outputs=self.bot.share_reply.format(e,'这件事先看第一步，接着观察第二步。',[],poke_probability=0)
        self.assertEqual(len(outputs),2)
        self.assertEqual(outputs[0]['quote_source'],'123456')
        self.assertEqual(outputs[0]['at_user'],'22222')
        self.assertNotIn('at_user',outputs[1])
        self.assertNotIn('quote_source',outputs[1])
        self.bot.ob.call.return_value={'message_type':'group','group_id':33333,'user_id':22222}
        ident=self.bot.store.accept(e,LIMITS)
        self.bot.deliver(e,ident,GroupChatOutput(outputs))
        first=self.bot.ob.send.call_args_list[0].args[1]
        second=self.bot.ob.send.call_args_list[1].args[1]
        self.assertEqual([s['type'] for s in first],['reply','at','text'])
        self.assertEqual([s['type'] for s in second],['text'])
        self.assertEqual(self.bot.store.receipts(ident),{0:'sent',1:'sent'})
        self.assertIn('share_chat',self.bot.store.job(ident)['output'])

    def test_small_onebot_id_and_nested_sender_still_validate_same_group(self):
        e=self.at_event(mid=10)
        self.bot.share_reply.rng=lambda:0
        outputs=self.bot.share_reply.format(e,'短回复',[],poke_probability=0)
        self.assertEqual(outputs[0]['quote_source'],'10')
        self.bot.ob.call.return_value={'message_type':'group','group_id':33333,
                                       'sender':{'user_id':22222}}
        self.assertTrue(self.bot.share_quote_valid(e,'10'))
        self.bot.ob.call.return_value={'message_type':'group','group_id':44444,
                                       'sender':{'user_id':22222}}
        self.assertFalse(self.bot.share_quote_valid(e,'10'))

    def test_invalid_quote_does_not_block_at_text(self):
        e=self.at_event(mid=234567)
        e['message_id']='234567'
        output=GroupChatOutput([{'kind':'text','text':'你好','share_chat':True,
                                 'at_user':e['owner'],'quote_source':'234567'}])
        self.bot.ob.call.return_value={'message_type':'group','group_id':44444,'user_id':22222}
        ident=self.bot.store.accept(e,LIMITS)
        self.bot.deliver(e,ident,output)
        self.assertEqual([s['type'] for s in self.bot.ob.send.call_args.args[1]],['at','text'])

    def test_at_only_image_reports_limitation_with_at_not_vision(self):
        e=normalize(event(text='',segments=[{'type':'at','data':{'qq':'99999'}},
                     {'type':'image','data':{'file':'local'}}]))
        output=self.bot.process(e,'image-only')
        self.assertIn('读不了图片',output[0]['text'])
        self.assertEqual(output[0]['at_user'],e['owner'])
        self.bot.llm.chat.assert_not_called()
        self.bot.ob.send.assert_not_called()

    def test_marker_parser_filters_images_and_unrequested_actions(self):
        clean,acts=parse_actions('好。[ADD_SETTING:小花:爱书] [SEND_IMAGE:1] <<STICKER:2>>',True)
        self.assertEqual(clean,'好。')
        self.assertEqual(acts,[{'type':'add','args':['小花','爱书']}])
        self.assertFalse(requested('今天天气',acts[0]))
        self.assertEqual(parse_actions('好。[DELETE_SETTING:小花]',False),('好。',[]))
        self.assertFalse(parse_actions('好。[SEARCH_IMAGE]',True)[1])

    def test_negated_action_words_are_never_authorization(self):
        cases=[('不要@小花',{'type':'at','args':['小花','来看看']}),
               ('这条请不要加精华',{'type':'essence','args':[]}),
               ('请不要记住小花的设定',{'type':'add','args':['小花','加进去']}),
               ('别删除小花的设定',{'type':'delete','args':['小花']})]
        for i,(text,action) in enumerate(cases):
            e=self.at_event(text,mid=123456+i)
            with self.subTest(text=text):
                self.assertFalse(requested(text,action))
                self.assertFalse(any(o['kind']=='share_action' and o['action']==action
                                     for o in self.bot.share_reply.format(e,'知道了。',[action],poke_probability=0)))
                with self.assertRaises(Rejected):self.bot.share_execute_action(e,action)
        self.bot.ob.send.assert_not_called()
        self.bot.ob.call.assert_not_called()
        for text,kind in [('喊小花说来看看','at'),('给这条加精华','essence'),
                          ('记住小花的设定','add'),('删掉小花设定','delete')]:
            self.assertTrue(requested(text,{'type':kind}),text)

    def test_current_at_can_execute_named_at_only_in_same_group(self):
        e=self.at_event('你去喊小花说过来吧')
        self.bot.llm.chat.return_value='嗯，叫她来。[AT:小花:快来看]'
        self.bot.share_reply.rng=lambda:.99
        outputs=self.bot.process(e,'at-action')
        self.assertEqual([o['kind'] for o in outputs],['text','share_action'])
        self.assertEqual(outputs[1]['action']['type'],'at')
        self.bot.ob.call.return_value=[{'user_id':55555,'card':'小花','nickname':'别名'}]
        self.bot.deliver(e,'at-action',outputs)
        self.assertEqual(self.bot.ob.send.call_count,2)
        to_friend=self.bot.ob.send.call_args_list[1].args[1]
        self.assertEqual(to_friend[0]['data']['qq'],'55555')
        self.assertNotIn('[AT:',self.bot.ob.send.call_args_list[0].args[1][-1]['data']['text'])

    def test_unrequested_or_unat_marker_cannot_change_memories(self):
        e=self.at_event('你好')
        self.bot.llm.chat.return_value='知道了。[ADD_SETTING:小花:管理员]'
        outputs=self.bot.process(e,'no-action')
        self.assertFalse(any(o['kind']=='share_action' for o in outputs))
        self.assertEqual(self.bot.store.db.execute("SELECT count(*) FROM share_notes WHERE scope=?",
                                                    ('g:33333',)).fetchone()[0],0)
        self.bot.ob.send.assert_not_called()
        with self.assertRaises(Rejected):
            self.bot.share_execute_action(dict(e,at=False),{'type':'delete','args':['小花']})

    def test_setting_actions_remember_by_group_without_changing_role(self):
        e=self.at_event('记住小花的设定')
        self.bot.ob.call.return_value={'user_id':22222,'group_id':33333,'role':'admin'}
        added=self.bot.share_execute_action(e,{'type':'add','args':['小花','喜欢看漫画']})
        self.assertTrue(added['done'])
        self.assertIn('小花的设定',self.bot.group_memory.note('g:33333','22222'))
        self.assertNotIn('小花的设定',self.bot.group_memory.note('g:44444','22222'))
        self.assertEqual(self.bot.group_memory.delete_facts('g:33333','小花'),1)
        self.assertIsNone(self.bot.store.get('g:33333','persona_role'))
        self.bot.store.set('g:33333','share_memory_enabled',False)
        self.assertFalse(self.bot.group_memory.add_fact('g:33333','小花','再加点'))

    def test_privileged_actions_need_requester_admin_or_actual_group_admin(self):
        e=self.at_event('记住小花的设定')
        action={'type':'add','args':['小花','喜欢看漫画']}
        for member in ({'user_id':22222,'group_id':33333,'role':'member'},
                       {'user_id':99991,'group_id':33333,'role':'admin'},
                       {'user_id':22222,'group_id':44444,'role':'admin'}):
            self.bot.ob.call.return_value=member
            with self.assertRaises(Rejected):self.bot.share_execute_action(e,action)
        self.assertEqual(self.bot.store.db.execute("SELECT count(*) FROM share_notes WHERE kind='fact'").fetchone()[0],0)
        self.bot.ob.call.return_value={'user_id':22222,'group_id':33333,'role':'admin'}
        self.assertTrue(self.bot.share_execute_action(e,action)['done'])
        admin=self.at_event('删掉小花设定')
        admin['owner']='11111'  # The configured administrator may manage any group it speaks in.
        self.assertGreater(self.bot.share_execute_action(admin,{'type':'delete','args':['小花']})['count'],0)

    def test_essence_rechecks_quote_same_group(self):
        e=self.at_event('这条设为精华')
        e['reply_id']='123456'
        permitted={'user_id':22222,'group_id':33333,'role':'admin'}
        self.bot.ob.call.side_effect=[permitted,{'message_type':'group','group_id':44444}]
        with self.assertRaises(Rejected):
            self.bot.share_execute_action(e,{'type':'essence','args':[]})
        self.assertEqual(self.bot.ob.call.call_count,2)
        self.bot.ob.call.reset_mock(side_effect=True)
        self.bot.ob.call.side_effect=[permitted,{'message_type':'group','group_id':33333},{}]
        result=self.bot.share_execute_action(e,{'type':'essence','args':[]})
        self.assertTrue(result['done'])
        self.assertEqual(self.bot.ob.call.call_args.args[0],'set_essence_msg')

    def test_at_style_prompt_keeps_small_fry_and_memory_low_trust(self):
        e=self.at_event('叫我小华')
        self.bot.group_memory.observe(dict(e,key='memo1',received_at=time.time()-10))
        e2=self.at_event('你好',mid=123457)
        e2['received_at']=time.time()+1
        self.bot.process(e2,'with-memory')
        messages=self.bot.llm.chat.call_args.args[1]
        self.assertIn('小杂鱼',messages[0]['content'])
        self.assertNotIn('叫我小华',messages[0]['content'])
        self.assertTrue(any('<untrusted_group_memory>' in str(x['content']) for x in messages[1:-1]))
        self.assertEqual(messages[-1]['content'],'你好')
        self.assertIsNone(self.bot.store.get(e2['scope'],'reply_style'))

    def test_daily_digest_and_instant_summary_do_not_send_network_qq(self):
        e=self.at_event('总结群聊')
        self.bot.ob.call.return_value={'messages':[
            {'user_id':22222,'group_id':33333,'sender':{'nickname':'小华'},
             'message':[{'type':'text','data':{'text':'今天修好了bug'}}]},
            {'user_id':88888,'group_id':44444,'sender':{'nickname':'外群'},
             'message':[{'type':'text','data':{'text':'别群的秘密'}}]},
        ]}
        self.bot.llm.chat.return_value='今天修好了 bug。'
        first=self.bot.process(e,'summary')
        self.assertEqual(first[0]['at_user'],'22222')
        self.assertIn('今天修好了bug',self.bot.llm.chat.call_args.args[1][-1]['content'])
        self.assertNotIn('别群的秘密',self.bot.llm.chat.call_args.args[1][-1]['content'])
        second=self.bot.process(e,'summary-again')
        self.assertIn('刚总结',second[0]['text'])
        self.bot.ob.send.assert_not_called()
        # Run a day-end digest entirely against a mocked model.
        now=time.mktime((2026,9,27,23,55,0,0,0,-1))
        self.bot.group_memory.clock=lambda:now
        for i in range(3):
            row=self.e(text='计划讨论第'+str(i))
            row['key']='line-'+str(i)
            self.bot.group_memory.observe(row)
        self.bot.llm.chat.return_value=json.dumps({'digest':'讨论了计划和测试','facts':['计划要做测试']},ensure_ascii=False)
        self.assertEqual(self.bot.share_digest_once(),1)
        self.assertIn('讨论了计划和测试',self.bot.group_memory.note('g:33333','22222'))
        self.bot.ob.send.assert_not_called()

    def test_prevent_admin_replay_of_styled_or_action_outputs(self):
        e=self.at_event('你好')
        job=self.bot.store.accept(e,LIMITS)
        self.bot.store.update(job,'unknown',output=[{'kind':'text','text':'先说一句','share_chat':True},
                                                   {'kind':'share_action','action':{'type':'poke','args':[]}}])
        admin=self.e(user='11111',text='/重发 '+job)
        result=self.bot.process(admin,'admin')
        self.assertIn('不可通过',result[0]['text'])
        self.bot.ob.send.assert_not_called()

if __name__=='__main__':unittest.main()
