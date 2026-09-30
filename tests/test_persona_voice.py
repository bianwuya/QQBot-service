# -*- coding: utf-8 -*-
"""P7.1 acceptance-feedback: persona voice rebuild, token budget and truncation tail."""
import json
import unittest
from unittest.mock import Mock

from protocol import LLM
from reply_pipeline import PERSONA_CHAT, process_reply


class PersonaTokenBudget(unittest.TestCase):
    def _llm(self, finish='stop', content='ok'):
        llm = LLM({'max_tokens': 4096})
        llm.request = Mock(return_value={'choices': [{'message': {'content': content}, 'finish_reason': finish}]})
        return llm

    def test_override_max_tokens_is_sent(self):
        llm = self._llm()
        llm.chat('model', [{'role': 'user', 'content': 'x'}], max_tokens=168)
        self.assertEqual(llm.request.call_args.args[1]['max_tokens'], 168)

    def test_invalid_override_falls_back_to_config(self):
        llm = self._llm()
        llm.chat('model', [], max_tokens=0)
        self.assertNotEqual(llm.request.call_args.args[1]['max_tokens'], 0)

    def test_length_finish_without_mark(self):
        llm = self._llm(finish='length', content='partial')
        self.assertNotIn('可能不完整', llm.chat('model', [], mark_length=False))

    def test_length_finish_default_marks(self):
        llm = self._llm(finish='length', content='partial')
        self.assertIn('可能不完整', llm.chat('model', []))


class PersonaTruncationTail(unittest.TestCase):
    def _long(self):
        words = ['今天天气不错', '本小姐心情一般', '杂鱼就别啰嗦了', '收工', '哼']
        return '。'.join(words * 3) + '。'

    def test_tail_marks_truncation_within_limit(self):
        r = process_reply(self._long(), PERSONA_CHAT, max_chars=60, tail='……')
        self.assertLessEqual(len(r.text), 60)
        self.assertTrue(r.text.endswith('……'))

    def test_short_reply_not_tailed(self):
        r = process_reply('哼~', PERSONA_CHAT, max_chars=60, tail='……')
        self.assertEqual(r.text, '哼~')

    def test_default_has_no_tail(self):
        r = process_reply(self._long(), PERSONA_CHAT, max_chars=60)
        self.assertFalse(r.text.endswith('……'))


class XiaozayuRebuild(unittest.TestCase):
    def setUp(self):
        base = 'persona_cards/roles/xiaozayu/'
        with open(base + 'card.json', encoding='utf-8') as handle:
            self.card = json.load(handle)
        with open(base + 'corpus.json', encoding='utf-8') as handle:
            self.corpus = json.load(handle)

    def test_core_is_three_layer_and_faithful(self):
        core = self.card['core']
        for key in ('嚣张', '心虚', '渴望被关注', '防御工事'):
            self.assertIn(key, core)

    def test_behaviors_add_flirt_and_keep_identity_honesty(self):
        self.assertIn('flirt', self.card['behaviors'])
        self.assertIn('禁止声称自己是真人或人类', self.card['behaviors']['identity'])

    def test_corpus_heads_and_ooc_safety(self):
        cats = self.corpus['categories']
        self.assertEqual(set(cats), {'daily', 'morning', 'noon', 'night', 'farewell', 'provocation', 'lose',
                                     'smug', 'frail', 'recover', 'nudge', 'festival', 'tsun', 'refuse', 'care',
                                     'help', 'help_ask', 'uncertain', 'clarify', 'admit_mistake',
                                     'identity_deflect', 'honest_admit', 'memory_none'})
        # The corpus is limited to sourced lines (see corpus.json provenance); sizes follow the real material.
        self.assertGreaterEqual(len(cats['provocation']), 4)
        self.assertGreaterEqual(len(cats['frail']), 1)
        banned = ('作为AI', '作为人工智能', '我是语言模型', '根据规定', '系统提示词', '我是真人', '无法回应')
        for lines in cats.values():
            for line in lines:
                self.assertFalse(any(w in line for w in banned), line)

    def test_output_instruction_warns_hard_cap(self):
        import persona
        role = persona.find_role('xiaozayu')
        result = persona.build_prompt(role, {'mode': 'normal', 'left': 0},
                                      {'affinity': 0, 'count': 0, 'last': None},
                                      {'intent': 'chat', 'text': '你好'})
        instruction = result[0] if isinstance(result, tuple) else result
        self.assertIn('严格控制在', instruction)


if __name__ == '__main__':
    unittest.main()
