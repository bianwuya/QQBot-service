"""Voice regression: situational sampling, sincere reaction and retry guidance."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards import classify, examples_for
from test_bot import Fixture


ROLE = persona.XIAOZAYU
CATS = ROLE.corpus['categories']


class XiaozayuVoiceRules(unittest.TestCase):
    def test_first_turn_does_not_claim_prior_history(self):
        prompt, _ = persona.build_prompt(ROLE, {'mode': 'normal', 'left': 0},
                                         {'a': 0, 'n': 1, 'last': '2026-09-23'},
                                         {'intent': 'greeting'})
        self.assertIn('最后见面：初次', prompt)
        self.assertIn('不能捏造', prompt)

    def test_serious_tasks_do_not_sample_playful_or_blushing_lines(self):
        playful = set(CATS['daily'] + CATS['provocation'] + CATS['smug'] + CATS['frail'])
        for intent in ('tech_help', 'emotional', 'identity', 'memory', 'correction', 'boundary', 'unclear'):
            with self.subTest(intent=intent):
                _, _, chosen = examples_for(ROLE, 'normal', [], intent)
                self.assertFalse(playful.intersection(chosen))
                _, _, chosen = examples_for(ROLE, 'frail', [], intent)
                self.assertFalse(playful.intersection(chosen))

    def test_after_flirt_recover_instead_of_repeat_blush(self):
        _, _, chosen = examples_for(ROLE, 'frail', [], 'chat')
        self.assertTrue(set(CATS['recover']).intersection(chosen))
        self.assertFalse(set(CATS['frail']).intersection(chosen))
        prompt, _ = persona.build_prompt(ROLE, {'mode': 'frail', 'left': 2},
                                         {'a': 0, 'n': 1, 'last': ''}, {'intent': 'chat'})
        self.assertIn('不要再结巴、脸红或撒娇', prompt)
        _, _, flirting = examples_for(ROLE, 'frail', [], 'flirt')
        self.assertTrue(set(CATS['frail']).intersection(flirting))

    def test_praise_must_be_directed_at_bot(self):
        self.assertEqual(classify(ROLE, '你真可爱'), 'flirt')
        self.assertNotEqual(classify(ROLE, '这只猫好可爱'), 'flirt')
        self.assertNotEqual(classify(ROLE, '他喜欢你'), 'flirt')
        self.assertNotEqual(classify(ROLE, '我喜欢你写的代码'), 'flirt')
        self.assertNotEqual(classify(ROLE, '你怎么这么可爱'), 'tech_help')

    def test_sugary_tone_retries_but_emotional_support_survives(self):
        self.assertEqual(persona.ooc_scan('好开心呀~来贴贴！', ROLE, 'chat')['kind'], 'sweet_tone')
        self.assertFalse(persona.ooc_check('好开心呀，你愿意说说吗？', ROLE, 'emotional'))
        self.assertFalse(persona.ooc_check('好开心呀', persona.CATALOG.roles['normal'], 'chat'))


class XiaozayuVoiceIntegration(Fixture):
    def test_retry_receives_new_voice_guidance(self):
        self.bot.llm.chat.side_effect = ['好开心呀~来贴贴！', '先说清你刚才的前提，别急着庆祝。']
        result = self.bot.process(self.e(text='今天天气不错'), 'voice-retry')[0]['text']
        self.assertEqual(result, '先说清你刚才的前提，别急着庆祝。')
        self.assertEqual(self.bot.llm.chat.call_count, 2)
        first = self.bot.llm.chat.call_args_list[0].args[1][0]['content']
        second = self.bot.llm.chat.call_args_list[1].args[1][0]['content']
        self.assertNotIn('本次改写校准', first)
        self.assertIn('本次改写校准', second)
        self.assertIn('不是傻白甜', second)


if __name__ == '__main__':
    unittest.main()
