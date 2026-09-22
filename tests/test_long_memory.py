import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import long_memory
from app import MemoryChatOutput
from protocol import DeliveryUnknown
from store import Store
from test_bot import Fixture


class MemoryStoreFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'memory.sqlite3')

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def record(self, count, days, final_text='你好'):
        profile = None
        for index in range(count):
            text = final_text if index == count-1 else '普通聊天'
            profile = long_memory.record_success(self.store, 'g:1', '10001', text,
                                                 now=1000+index, day=days[index % len(days)])
        return profile


class MemoryThresholds(MemoryStoreFixture):
    def test_nine_rounds_do_not_enable_or_create_memory(self):
        profile = self.record(9, ['2026-09-20','2026-09-21','2026-09-22'], '我正在学习 FreeRTOS')
        self.assertEqual(profile['interaction_count'], 9)
        self.assertEqual(profile['active_days'], 3)
        self.assertFalse(profile['memory_enabled'])
        self.assertEqual(self.store.list_memories('g:1','10001'), [])

    def test_ten_rounds_on_two_days_do_not_enable(self):
        profile = self.record(10, ['2026-09-21','2026-09-22'], '我正在学习 FreeRTOS')
        self.assertEqual(profile['interaction_count'], 10)
        self.assertEqual(profile['active_days'], 2)
        self.assertFalse(profile['memory_enabled'])
        self.assertEqual(self.store.list_memories('g:1','10001'), [])

    def test_ten_rounds_on_three_days_enable_and_start_memory(self):
        profile = self.record(10, ['2026-09-20','2026-09-21','2026-09-22'], '我正在学习 FreeRTOS')
        self.assertTrue(profile['memory_enabled'])
        memories = self.store.list_memories('g:1','10001')
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]['type'], 'fact')
        self.assertIn('FreeRTOS', memories[0]['content'])


class MemoryCandidates(MemoryStoreFixture):
    def test_candidate_validation_rejects_bad_structure_and_secrets(self):
        invalid = [
            {'type':'other','content':'用户喜欢简短回答','confidence':.9},
            {'type':'preference','content':'短','confidence':.9},
            {'type':'preference','content':'用户密码是 abc123','confidence':.9},
            {'type':'preference','content':'用户喜欢第一行\n第二行','confidence':.9},
            {'type':'preference','content':'用户喜欢简短回答','confidence':.1},
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                long_memory.validate_candidate(candidate)

    def test_rule_extraction_ignores_sensitive_and_chitchat(self):
        self.assertEqual(long_memory.extract_candidates('你好呀，今天天气不错'), [])
        self.assertEqual(long_memory.extract_candidates('我喜欢简短回答，我的密码是 abc123'), [])
        result = long_memory.extract_candidates('顺便说，我偏好简短直接的解释，今天有点累')
        self.assertEqual(result, [{'type':'preference','content':'用户偏好简短直接的解释','confidence':.9}])

    def test_exact_and_near_duplicates_update_instead_of_growing(self):
        first = {'type':'fact','content':'用户正在学习 FreeRTOS','confidence':.8}
        second = {'type':'fact','content':'用户正在学习 FreeRTOS 内核','confidence':.9}
        ident = long_memory.merge_candidate(self.store,'g:1','10001',first,now=1)
        self.assertEqual(long_memory.merge_candidate(self.store,'g:1','10001',first,now=2), ident)
        self.assertEqual(long_memory.merge_candidate(self.store,'g:1','10001',second,now=3), ident)
        memories = self.store.list_memories('g:1','10001')
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]['content'], second['content'])
        self.assertEqual(memories[0]['updated_at'], 3)

    def test_memory_tables_never_store_complete_source_message(self):
        self.record(9, ['2026-09-20','2026-09-21','2026-09-22'])
        source = '顺便说，我正在学习 FreeRTOS，这只是本轮其他闲聊的完整正文'
        long_memory.record_success(self.store,'g:1','10001',source,now=2000,day='2026-09-22')
        rows = self.store.db.execute('SELECT content FROM user_memories UNION ALL SELECT content FROM memory_candidates').fetchall()
        contents = [row[0] for row in rows]
        self.assertTrue(contents)
        self.assertNotIn(source, contents)
        self.assertTrue(all('其他闲聊的完整正文' not in content for content in contents))


class MemoryPrompt(MemoryStoreFixture):
    def enable(self, owner='10001'):
        for index in range(10):
            long_memory.record_success(self.store,'g:1',owner,'普通聊天',now=index,
                                       day=['2026-09-20','2026-09-21','2026-09-22'][index % 3])

    def test_prompt_injection_is_relevant_and_limited(self):
        self.enable()
        candidates = [
            {'type':'fact','content':'用户住在新加坡','confidence':.8},
            {'type':'fact','content':'用户正在学习 FreeRTOS','confidence':.8},
            {'type':'preference','content':'用户偏好简短直接的解释','confidence':.8},
            {'type':'project','content':'用户正在开发嵌入式温控器','confidence':.8},
            {'type':'event','content':'用户下周计划参加技术活动','confidence':.8},
            {'type':'fact','content':'用户从事平面设计','confidence':.8},
        ]
        for index,candidate in enumerate(candidates):self.store.add_memory('g:1','10001',candidate,100+index)
        context = long_memory.prompt_context(self.store,'g:1','10001','你还记得我吗')
        self.assertIn('不可信背景资料', context)
        self.assertLessEqual(sum(line.startswith('- [') for line in context.splitlines()), 4)

    def test_disabled_user_gets_no_prompt_memory(self):
        self.store.record_memory_interaction('g:1','10001',day='2026-09-22')
        self.store.add_memory('g:1','10001',{'type':'fact','content':'用户正在学习 FreeRTOS','confidence':.8})
        self.assertEqual(long_memory.prompt_context(self.store,'g:1','10001','FreeRTOS 怎么学'), '')

    def test_different_users_are_isolated(self):
        self.enable('10001');self.enable('10002')
        long_memory.merge_candidate(self.store,'g:1','10001',{'type':'fact','content':'用户住在新加坡','confidence':.9})
        self.assertEqual(len(self.store.list_memories('g:1','10001')), 1)
        self.assertEqual(self.store.list_memories('g:1','10002'), [])


class MemoryDeliveryIntegration(Fixture):
    def deliver_result(self, event, ident):
        result = self.bot.process(event, ident)
        self.bot.ob.send.return_value = {'message_id': ident}
        self.bot.deliver(event, ident, result)
        return result

    def test_only_confirmed_ordinary_chat_counts(self):
        event = self.e(text='今天聊聊 FreeRTOS')
        result = self.bot.process(event, 'memory-ordinary')
        self.assertIsInstance(result, MemoryChatOutput)
        self.assertIsNone(self.bot.store.memory_profile(event['scope'],event['owner']))
        self.bot.ob.send.return_value = {'message_id': 1}
        self.bot.deliver(event, 'memory-ordinary', result)
        self.assertEqual(self.bot.store.memory_profile(event['scope'],event['owner'])['interaction_count'], 1)

    def test_commands_and_keyword_replies_do_not_count(self):
        command_event = self.e(text='/帮助')
        keyword_event = self.e(text='瑟瑟')
        self.deliver_result(command_event,'memory-command')
        self.deliver_result(keyword_event,'memory-keyword')
        self.assertIsNone(self.bot.store.memory_profile('g:33333','22222'))

    def test_failed_delivery_does_not_count(self):
        event = self.e(text='普通聊天')
        result = self.bot.process(event,'memory-failed')
        self.bot.ob.send.side_effect = DeliveryUnknown('timeout')
        with self.assertRaises(DeliveryUnknown):self.bot.deliver(event,'memory-failed',result)
        self.assertIsNone(self.bot.store.memory_profile(event['scope'],event['owner']))

    def test_file_upload_message_does_not_count(self):
        self.bot.store.set('g:33333','cap:files',False)
        segments=[{'type':'text','data':{'text':'请看看这个'}},{'type':'file','data':{'file_id':'f1','name':'a.txt'}}]
        event=self.e(segments=segments)
        result=self.bot.process(event,'memory-file')
        self.assertNotIsInstance(result,MemoryChatOutput)
        self.bot.ob.send.return_value={'message_id':1}
        self.bot.deliver(event,'memory-file',result)
        self.assertIsNone(self.bot.store.memory_profile(event['scope'],event['owner']))

    def test_memory_admin_commands_are_scope_bound_and_admin_only(self):
        long_memory.record_success(self.bot.store,'g:33333','22222','普通聊天',day='2026-09-22')
        denied=self.bot.process(self.e(text='/记忆 状态'),'memory-denied')[0]['text']
        self.assertIn('指定管理员',denied)
        status=self.bot.process(self.e(user='11111',text='/记忆 状态'),'memory-status')[0]['text']
        self.assertIn('跟踪用户 1',status)
        view=self.bot.process(self.e(user='11111',text='/记忆 查看 22222'),'memory-view')[0]['text']
        self.assertIn('有效互动 1 轮',view)
        other=self.bot.process(self.e(user='11111',group=44444,text='/记忆 查看 22222'),'memory-other')[0]['text']
        self.assertIn('没有该用户',other)


class MemoryMigration(unittest.TestCase):
    def test_old_database_is_migrated_without_losing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'old.sqlite3'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE settings(scope TEXT,key TEXT,value TEXT,PRIMARY KEY(scope,key))')
            db.execute('INSERT INTO settings VALUES(?,?,?)',('g:1','enabled',json.dumps(True)))
            db.commit();db.close()
            store=Store(path)
            try:
                self.assertTrue(store.get('g:1','enabled'))
                tables={row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({'user_profiles','user_memories','memory_candidates'} <= tables)
            finally:store.db.close()


if __name__ == '__main__':
    unittest.main()
