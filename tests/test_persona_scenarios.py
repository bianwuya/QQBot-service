# -*- coding: utf-8 -*-
"""Scenario-aware exemplar sampling and the 2026-09-30 reviewed corpus."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards import examples_for
from persona_cards.engine import scenario_categories


ROLE = persona.XIAOZAYU
CATS = ROLE.corpus['categories']


def picked(intent, text, mode='normal', seed=0):
    return examples_for(ROLE, mode, [], intent, None, seed, 'mild', text)[2]


class ScenarioSampling(unittest.TestCase):
    def test_keywords_select_the_matching_scenario(self):
        cases = (('greeting', '早安', 'morning'), ('greeting', '晚安啦', 'night'),
                 ('chat', '十连又歪了', 'lose'), ('chat', '今天我生日', 'festival'),
                 ('chat', '我先下线了拜拜', 'farewell'), ('chat', '谢谢你', 'smug'),
                 ('chat', '明天考试还不想复习', 'nudge'), ('insult', '你才是杂鱼', 'recover'))
        for intent, text, category in cases:
            with self.subTest(text=text):
                self.assertEqual(scenario_categories(ROLE, intent, text)[0], category)
                self.assertTrue(set(CATS[category]).intersection(picked(intent, text)))

    def test_scenario_lines_replace_generic_ones_without_growing_the_prompt(self):
        self.assertEqual(len(picked('chat', '今天天气不错')), 4)
        self.assertEqual(len(picked('chat', '十连又歪了')), 4)
        greeting = picked('greeting', '早安')
        self.assertEqual(len(greeting), 1)
        self.assertIn(greeting[0], CATS['morning'])
        self.assertEqual(picked('greeting', '你好')[0] in CATS['daily'], True)

    def test_at_most_two_scenarios_and_no_duplicates(self):
        chosen = picked('chat', '早安，昨天十连又歪了，今天我生日')
        self.assertEqual(len(chosen), 4)
        self.assertEqual(len(set(chosen)), len(chosen))
        self.assertLessEqual(len(scenario_categories(ROLE, 'chat', '早安，十连又歪了，今天我生日')), 2)

    def test_task_intents_ignore_scenarios(self):
        for intent in ('tech_help', 'emotional', 'identity', 'memory', 'correction', 'boundary', 'unclear'):
            with self.subTest(intent=intent):
                self.assertEqual(scenario_categories(ROLE, intent, '早安 十连又歪了'), [])
                self.assertEqual(picked(intent, '早安 十连又歪了'), picked(intent, None))

    def test_missing_text_or_rules_keep_the_old_plan(self):
        self.assertEqual(picked('chat', None), picked('chat', ''))
        self.assertEqual(scenario_categories(persona.CATALOG.roles['normal'], 'chat', '早安'), [])

    def test_build_prompt_uses_context_text(self):
        prompt, chosen = persona.build_prompt(ROLE, {'mode': 'normal', 'left': 0},
                                              {'a': 0, 'n': 2, 'last': '2026-09-30'},
                                              {'intent': 'chat', 'text': '十连又歪了'})
        self.assertTrue(set(CATS['lose']).intersection(chosen))
        self.assertIn('只学语气', prompt)


class ReviewedCorpus(unittest.TestCase):
    def test_every_line_has_provenance_and_rewrites_keep_their_origin(self):
        lines = ROLE.corpus['provenance']['lines']
        pools = list(CATS.values()) + list(ROLE.corpus['fallbacks'].values())
        for pool in pools:
            for line in pool:
                with self.subTest(line=line):
                    self.assertIn(line, lines)
                    info = lines[line]
                    self.assertIn(info['tier'], ('A', 'B', 'B-ja', 'self-edit', 'legacy-confirmed'))
                    if info['tier'] in ('self-edit', 'legacy-confirmed'):
                        self.assertTrue(info['based_on']['text'])

    def test_no_character_names_or_age_gap_addresses(self):
        pools = list(CATS.values()) + list(ROLE.corpus['fallbacks'].values())
        for pool in pools:
            for line in pool:
                for word in ('贝奇', '指挥官', '无名客', '大叔', '叔叔', 'おじさん'):
                    self.assertNotIn(word, line)

    def test_reference_only_lines_are_not_sampled(self):
        refs = {item['text'] for item in ROLE.corpus['reference_only']}
        pools = [line for pool in CATS.values() for line in pool]
        self.assertFalse(refs.intersection(pools))

    def test_combat_phrases_are_rewritten(self):
        for text in ('本小姐真骂起来怕你接不住', '这种话本小姐可不接啦', '先管好你自己吧，前辈~', '想嘴炮我奉陪'):
            with self.subTest(text=text):
                self.assertEqual(persona.ooc_scan(text, ROLE, 'chat')['kind'], 'service_tone')
        self.assertIsNone(persona.ooc_scan('嗯？再多说半句嘛，本小姐就能接住啦~', ROLE, 'unclear')['kind'])
        pools = [line for pool in CATS.values() for line in pool]
        self.assertFalse([line for line in pools if '管好你自己' in line])


if __name__ == '__main__':
    unittest.main()
