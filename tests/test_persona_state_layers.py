import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from test_bot import Fixture


class PersonaStateLayers(Fixture):
    def kw(self, text='瑟瑟', user='22222', ident='job-state'):
        return self.bot.process(self.e(text=text, user=user), ident)[0]['text']

    def prompt_of(self):
        return self.bot.llm.chat.call_args[0][1][0]['content']

    def test_frail_is_per_owner_and_legacy_key_is_mirrored(self):
        self.bot.llm.chat.return_value = '诶？！'
        self.kw(text='瑟瑟 你真可爱', user='22222', ident='state-a')
        reacts = self.bot.store.get('g:33333', 'persona_react:xiaozayu')
        self.assertEqual(reacts['22222'], {'mode': 'frail', 'left': 3})
        self.assertEqual(self.bot.store.get('g:33333', 'persona_state'), {'mode': 'frail', 'left': 3})
        self.assertIsNone(self.bot.store.get('g:33333', 'persona_react:normal'))

        self.bot.llm.chat.return_value = '嗯。'
        self.kw(text='今天天气不错', user='33333', ident='state-b')
        reacts = self.bot.store.get('g:33333', 'persona_react:xiaozayu')
        self.assertEqual(reacts['22222'], {'mode': 'frail', 'left': 3})
        self.assertEqual(reacts['33333'], {'mode': 'normal', 'left': 0})
        self.assertIn('日常态', self.prompt_of())
        self.assertNotIn('当前是脆弱态', self.prompt_of())

    def test_group_mood_decays_after_two_replies(self):
        self.bot.llm.chat.return_value = '诶？！'
        self.kw(text='瑟瑟 你真可爱', user='22222', ident='mood-a')
        self.assertEqual(self.bot.store.get('g:33333', 'persona_mood:xiaozayu'), {'vibe': 'flustered', 'left': 2})
        self.bot.llm.chat.return_value = '嗯。'
        self.kw(text='今天天气不错', user='33333', ident='mood-b')
        self.assertEqual(self.bot.store.get('g:33333', 'persona_mood:xiaozayu'), {'vibe': 'flustered', 'left': 1})
        self.assertIn('耳朵还热着', self.prompt_of())
        self.kw(text='嗯', user='44444', ident='mood-c')
        self.assertEqual(self.bot.store.get('g:33333', 'persona_mood:xiaozayu'), {'vibe': 'calm', 'left': 0})
        self.kw(text='嗯', user='44444', ident='mood-d')
        self.assertNotIn('耳朵还热着', self.prompt_of())

    def test_legacy_persona_state_migrates_to_owner_bucket(self):
        role = persona.XIAOZAYU
        self.bot.store.set('g:33333', 'persona_state', {'mode': 'frail', 'left': 2})
        state, used = persona.load_runtime(self.bot.store, 'g:33333', role, owner='22222')
        self.assertEqual(state, {'mode': 'frail', 'left': 2})
        persona.save_runtime(self.bot.store, 'g:33333', role, state, used, owner='22222')
        self.assertEqual(self.bot.store.get('g:33333', 'persona_react:xiaozayu')['22222'], {'mode': 'frail', 'left': 2})
        self.assertEqual(self.bot.store.get('g:33333', 'persona_state'), {'mode': 'frail', 'left': 2})
        later, _ = persona.load_runtime(self.bot.store, 'g:33333', role, owner='33333')
        self.assertEqual(later, {'mode': 'normal', 'left': 0})

    def test_private_chat_does_not_write_group_persona_state(self):
        self.bot.llm.chat.return_value = '私聊回答'
        self.bot.process(self.e(group=None, text='你好'), 'state-private')
        self.assertIsNone(self.bot.store.get('p:22222', 'persona_react:xiaozayu'))
        self.assertIsNone(self.bot.store.get('p:22222', 'persona_state'))


if __name__ == '__main__':
    unittest.main()
