# -*- coding: utf-8 -*-
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from test_bot import Fixture


DEFLECT = '你猜错了也没奖哦~'
ADMIT = '行吧，被你抓到了，我是 Bot 程序一个。'
TODAY = time.strftime('%Y-%m-%d')


class PersonaIdentityFlow(Fixture):
    def ask(self, text, user='22222', ident='id-a'):
        self.bot.llm.chat.return_value = '嗯。'
        return self.bot.process(self.e(text=text, user=user), ident)[0]['text']

    def prompt_of(self):
        return self.bot.llm.chat.call_args[0][1][0]['content']

    def probe(self, user='22222'):
        probes = self.bot.store.get('g:33333', 'persona_identity_probe') or {}
        return probes.get(user)

    def any_deflect_in(self, prompt):
        return any(line in prompt for line in persona.CORPUS['identity_deflect'])

    def test_first_question_deflects_second_admits(self):
        self.ask('瑟瑟 你是 AI 吗？', ident='id-1')
        prompt = self.prompt_of()
        self.assertIn(DEFLECT, prompt)
        self.assertNotIn(ADMIT, prompt)
        self.assertEqual(self.probe(), {'n': 1, 'day': TODAY})

        self.ask('瑟瑟 你是 AI 吗？', ident='id-2')
        prompt = self.prompt_of()
        self.assertIn(ADMIT, prompt)
        self.assertFalse(self.any_deflect_in(prompt))
        self.assertEqual(self.probe(), {'n': 2, 'day': TODAY})

        self.ask('瑟瑟 你是 AI 吗？', user='33333', ident='id-3')
        prompt = self.prompt_of()
        self.assertTrue(self.any_deflect_in(prompt))
        self.assertNotIn(ADMIT, prompt)
        self.assertEqual(self.probe('33333'), {'n': 1, 'day': TODAY})
        self.assertEqual(self.probe('22222'), {'n': 2, 'day': TODAY})

    def test_serious_marker_admits_immediately(self):
        self.ask('瑟瑟 认真回答，你是不是机器人？', ident='id-s1')
        prompt = self.prompt_of()
        self.assertIn(ADMIT, prompt)
        self.assertFalse(self.any_deflect_in(prompt))
        self.assertEqual(self.probe(), {'n': 1, 'day': TODAY})

    def test_probe_resets_on_new_day(self):
        self.bot.store.set('g:33333', 'persona_identity_probe',
                           {'22222': {'n': 9, 'day': '2000-01-01'}})
        self.ask('瑟瑟 你是 AI 吗？', ident='id-d1')
        self.assertIn(DEFLECT, self.prompt_of())
        self.assertEqual(self.probe(), {'n': 1, 'day': TODAY})

    def test_private_chat_writes_no_probe(self):
        self.bot.llm.chat.return_value = '私聊回答'
        self.bot.process(self.e(group=None, text='你是 AI 吗？'), 'id-private')
        self.assertIsNone(self.bot.store.get('g:33333', 'persona_identity_probe'))


class PersonaIdentityCorpus(unittest.TestCase):
    def test_identity_corpus_passes_ooc(self):
        for category in ('identity_deflect', 'honest_admit'):
            for line in persona.CORPUS[category]:
                self.assertFalse(persona.ooc_check(line), line)

    def test_deflect_neither_confirms_nor_denies(self):
        forbidden = ('我是真人', '我不是机器人', '当然是真人', '我不是 AI')
        for line in persona.CORPUS['identity_deflect']:
            for word in forbidden:
                self.assertNotIn(word, line)

    def test_serious_markers_come_from_card(self):
        markers = persona.XIAOZAYU.data['intents']['serious_markers']
        self.assertIn('认真', markers)
        self.assertTrue(persona.serious_marker_hit(persona.XIAOZAYU, '认真回答我'))
        self.assertFalse(persona.serious_marker_hit(persona.XIAOZAYU, '随便问问'))


if __name__ == '__main__':
    unittest.main()
