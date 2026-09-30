# -*- coding: utf-8 -*-
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from test_bot import Fixture


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

    def any_admit_in(self, prompt):
        return any(line in prompt for line in persona.CORPUS['honest_admit'])

    def test_casual_questions_deflect_until_the_third_ask(self):
        for ident, count in (('id-1', 1), ('id-2', 2)):
            self.ask('瑟瑟 你是 AI 吗？', ident=ident)
            prompt = self.prompt_of()
            self.assertTrue(self.any_deflect_in(prompt))
            self.assertFalse(self.any_admit_in(prompt))
            self.assertEqual(self.probe(), {'n': count, 'day': TODAY})

        self.ask('瑟瑟 你是 AI 吗？', ident='id-3')
        prompt = self.prompt_of()
        self.assertTrue(self.any_admit_in(prompt))
        self.assertFalse(self.any_deflect_in(prompt))
        self.assertEqual(self.probe(), {'n': 3, 'day': TODAY})

        self.ask('瑟瑟 你是 AI 吗？', user='33333', ident='id-4')
        prompt = self.prompt_of()
        self.assertTrue(self.any_deflect_in(prompt))
        self.assertFalse(self.any_admit_in(prompt))
        self.assertEqual(self.probe('33333'), {'n': 1, 'day': TODAY})
        self.assertEqual(self.probe('22222'), {'n': 3, 'day': TODAY})

    def test_serious_marker_admits_immediately(self):
        self.ask('瑟瑟 认真回答，你是不是机器人？', ident='id-s1')
        prompt = self.prompt_of()
        self.assertTrue(self.any_admit_in(prompt))
        self.assertFalse(self.any_deflect_in(prompt))
        self.assertEqual(self.probe(), {'n': 1, 'day': TODAY})

    def test_probe_resets_on_new_day(self):
        self.bot.store.set('g:33333', 'persona_identity_probe',
                           {'22222': {'n': 9, 'day': '2000-01-01'}})
        self.ask('瑟瑟 你是 AI 吗？', ident='id-d1')
        self.assertTrue(self.any_deflect_in(self.prompt_of()))
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
        forbidden = ('我是真人', '我不是机器人', '当然是真人', '我不是 AI', '是个程序', 'Bot 程序', '我是程序')
        for line in persona.CORPUS['identity_deflect']:
            for word in forbidden:
                self.assertNotIn(word, line)

    def test_serious_markers_come_from_card(self):
        markers = persona.XIAOZAYU.data['intents']['serious_markers']
        self.assertIn('认真', markers)
        self.assertTrue(persona.serious_marker_hit(persona.XIAOZAYU, '认真回答我'))
        self.assertFalse(persona.serious_marker_hit(persona.XIAOZAYU, '随便问问'))

    def test_identity_path_threshold_comes_from_card(self):
        from persona_cards.intents import identity_path
        role = persona.XIAOZAYU
        self.assertEqual(role.data['identity_policy']['admit_after_probes'], 2)
        self.assertEqual(identity_path(role, 0, '你是 AI 吗'), 'deflect')
        self.assertEqual(identity_path(role, 1, '你是 AI 吗'), 'deflect')
        self.assertEqual(identity_path(role, 2, '你是 AI 吗'), 'admit')
        self.assertEqual(identity_path(role, 0, '说真的，你是不是真人'), 'admit')
        # Roles without the policy keep the old behaviour: the second question admits.
        self.assertEqual(identity_path({'intents': {}}, 1, '你是 AI 吗'), 'admit')


if __name__ == '__main__':
    unittest.main()
