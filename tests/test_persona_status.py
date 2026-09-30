# -*- coding: utf-8 -*-
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from test_bot import Fixture


class PersonaStatusCommand(Fixture):
    def status(self, user='11111', ident='st-x'):
        return self.bot.process(self.e(user=user, text='/人格状态'), ident)[0]['text']

    def test_non_admin_is_rejected_by_gate(self):
        out = self.bot.process(self.e(text='/人格状态'), 'st-1')
        self.assertIn('只有 Bot 指定管理员', out[0]['text'])
        self.assertNotIn('群氛围', out[0]['text'])

    def test_admin_sees_state_mood_relation_and_counts(self):
        self.bot.llm.chat.return_value = '嗯。'
        self.bot.process(self.e(text='瑟瑟'), 'st-2')
        out = self.status(ident='st-3')
        self.assertIn('角色：小杂鱼', out)
        self.assertIn('你的状态：normal（剩余 0）', out)
        self.assertIn('群氛围：calm', out)
        self.assertIn('关系档位：一般', out)
        self.assertIn('OOC重试 0 次｜风格告警 0 次｜兜底 0 次', out)

    def test_frail_owner_and_group_mood_show_state_names(self):
        self.bot.llm.chat.return_value = '诶？！'
        self.bot.process(self.e(user='11111', text='瑟瑟 你真可爱'), 'st-4')
        out = self.status(ident='st-5')
        self.assertIn('你的状态：frail', out)
        self.assertIn('群氛围：flustered', out)

    def test_ooc_retry_and_fallback_counts(self):
        self.bot.llm.chat.side_effect = ['作为AI，我不能回答。', '哼！才不告诉你。']
        self.bot.process(self.e(text='瑟瑟'), 'st-6')
        self.bot.llm.chat.side_effect = ['作为AI，我不能回答。', '我是语言模型，无法回应。']
        self.bot.process(self.e(text='瑟瑟'), 'st-7')
        out = self.status(ident='st-8')
        self.assertIn('OOC重试 2 次', out)
        self.assertIn('兜底 1 次', out)

    def test_soft_tone_warn_count_without_retry(self):
        self.bot.llm.chat.return_value = '抱歉，这个我还真没把握。'
        self.bot.process(self.e(text='瑟瑟'), 'st-9')
        out = self.status(ident='st-10')
        self.assertIn('风格告警 1 次', out)
        self.assertIn('OOC重试 0 次', out)
        self.assertIn('兜底 0 次', out)


if __name__ == '__main__':
    unittest.main()
