"""Persona rework: sourced corpus, heart rules, heart cooldown and calibration text of the 小杂鱼 card."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards.engine import output_instruction, retry_guidance, soften_hearts
from test_bot import Fixture

ROLE = persona.XIAOZAYU
NORMAL = persona.CATALOG.roles['normal']
CORPUS = ROLE.corpus
PROV = CORPUS['provenance']['lines']
TIERS = {'A', 'B', 'B-ja', 'self-edit', 'legacy-confirmed'}


def all_lines():
    for category, lines in CORPUS['categories'].items():
        for line in lines:
            yield category, line
    fallbacks = CORPUS['fallbacks']
    for lines in (fallbacks.values() if isinstance(fallbacks, dict) else [fallbacks]):
        for line in lines:
            yield 'fallback', line


class SourcedCorpus(unittest.TestCase):
    def test_every_line_has_provenance(self):
        for category, line in all_lines():
            with self.subTest(category=category, line=line):
                self.assertIn(line, PROV)
                self.assertIn(PROV[line]['tier'], TIERS)

    def test_no_orphan_provenance(self):
        self.assertFalse(set(PROV) - {line for _, line in all_lines()})

    def test_sourced_tiers_carry_their_evidence(self):
        for line, info in PROV.items():
            with self.subTest(line=line):
                if info['tier'] in ('A', 'B', 'B-ja'):
                    self.assertIn(info['strength'], ('mild', 'standard', 'spicy'))
                    # Older research quotes carry a numeric source_id; the 2026-09-30 review uses candidate ids.
                    self.assertTrue(isinstance(info.get('source_id'), int) or info.get('candidate_id'))
                    self.assertTrue(info['url'].startswith('http'))
                if info['tier'] == 'B-ja':
                    self.assertTrue(info['original_ja'].strip())
                if info['tier'] in ('self-edit', 'legacy-confirmed'):
                    self.assertIn(info['strength'], ('mild', 'standard', 'spicy'))
                    self.assertTrue(info['based_on']['text'].strip())
                    self.assertTrue(info['note'].strip())

    def test_playful_categories_contain_only_sourced_lines(self):
        playful = set()
        for category in ('daily', 'provocation', 'smug', 'frail', 'recover', 'care', 'help'):
            playful.update(CORPUS['categories'][category])
        self.assertTrue(playful)
        self.assertTrue(all(PROV[line]['tier'] != 'legacy-confirmed' for line in playful))
        self.assertGreaterEqual(sum(1 for info in PROV.values() if info['tier'] in ('A', 'B', 'B-ja')), 15)

    def test_sourced_lines_pass_the_current_ooc_rules(self):
        for category, line in all_lines():
            info = PROV[line]
            if info['tier'] == 'legacy-confirmed':
                continue
            intent = 'emotional' if category == 'care' else 'chat'
            with self.subTest(category=category, line=line):
                self.assertFalse(persona.ooc_check(line, ROLE, intent))

    def test_reference_lines_carry_no_character_names_and_the_name_stays_banned(self):
        prompt, _ = persona.build_prompt(ROLE, {'mode': 'normal', 'left': 0},
                                         {'a': 0, 'n': 2, 'last': '2026-09-30'}, {'intent': 'chat'})
        self.assertFalse(any('贝奇' in line or '指挥官' in line for _, line in all_lines()))
        self.assertNotIn('贝奇', prompt.split('# 绝对禁止')[0])
        self.assertIn('贝奇', prompt.split('# 绝对禁止')[1])
        self.assertIn('# 语料', prompt)
        self.assertNotIn('傻白甜', prompt)


class HeartRules(unittest.TestCase):
    def test_hearts_are_allowed_in_teasing_but_not_in_comfort_or_affection(self):
        self.assertFalse(persona.ooc_check('杂鱼~这点事都做不好吗？那我来帮你吧♡', ROLE, 'tech_help'))
        self.assertFalse(persona.ooc_check('吼？杂鱼酱这么悠闲的吗♡嘻嘻~', ROLE, 'chat'))
        self.assertEqual(persona.ooc_scan('去喝口水啦♡', ROLE, 'emotional')['kind'], 'care_tone')
        self.assertEqual(persona.ooc_scan('哈？喜欢我？做梦吧♡', ROLE, 'flirt')['kind'], 'care_tone')

    def test_pleasing_aegyo_is_still_rejected_but_teasing_particles_are_not(self):
        self.assertEqual(persona.ooc_scan('好开心呀~来贴贴！', ROLE, 'chat')['kind'], 'sweet_tone')
        self.assertIsNone(persona.ooc_scan('诶~就这？好弱诶——！嘻嘻~', ROLE, 'chat')['kind'])

    def test_old_elder_and_debate_tone_is_rejected(self):
        for text in ('说说看，能帮就帮。', '有事说事，别光戳。', '先管好自己那张嘴吧', '先别急着赢，证据呢？', '你的前提站住了吗？'):
            with self.subTest(text=text):
                self.assertEqual(persona.ooc_scan(text, ROLE, 'chat')['kind'], 'service_tone')

    def test_cooldown_drops_hearts_after_a_recent_heart(self):
        self.assertEqual(soften_hearts(ROLE, '杂鱼~♡ 就这？', ['刚才那句♡']), '杂鱼~ 就这？')
        self.assertEqual(soften_hearts(ROLE, '杂鱼~♡ 就这？', ['没有爱心']), '杂鱼~♡ 就这？')
        self.assertEqual(soften_hearts(ROLE, '哼 ❤️ 好吧', ['x♡']), '哼 好吧')
        self.assertEqual(soften_hearts(ROLE, '杂鱼♡', ['a♡', 'b', 'c', 'd']), '杂鱼♡')
        self.assertEqual(soften_hearts(ROLE, '杂鱼♡', ['a', 'b♡', 'c', 'd']), '杂鱼')

    def test_roles_without_a_style_config_are_untouched(self):
        self.assertEqual(soften_hearts(NORMAL, 'a♡', ['b♡']), 'a♡')


class HeartCooldownIntegration(Fixture):
    def reply(self, *outputs, intent='chat', recent=()):
        if len(outputs) == 1:
            self.bot.llm.chat.side_effect = None
            self.bot.llm.chat.return_value = outputs[0]
        else:
            self.bot.llm.chat.side_effect = list(outputs)
        messages = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': '今天天气不错'}]
        return self.bot.persona_answer('g:33333', messages, ROLE, intent, [], recent_replies=list(recent))[0]

    def test_recent_heart_is_stripped_from_the_next_reply(self):
        self.assertIn('♡', self.reply('杂鱼~就这？♡', recent=['昨天的回复']))
        self.assertNotIn('♡', self.reply('杂鱼~就这？♡', recent=['刚才♡']))

    def test_heart_in_comfort_is_retried(self):
        result = self.reply('去喝口水啦♡', '才不是关心你呢，去喝口水啦！', intent='emotional')
        self.assertEqual(result, '才不是关心你呢，去喝口水啦！')
        self.assertEqual(self.bot.llm.chat.call_count, 2)


class CalibrationText(unittest.TestCase):
    def test_xiaozayu_no_longer_tells_the_model_to_answer_first(self):
        for intent in ('chat', 'tech_help', 'emotional'):
            with self.subTest(intent=intent):
                self.assertNotIn('先答对再带口吻', output_instruction(ROLE, intent))
        self.assertIn('语气外放', output_instruction(ROLE, 'chat'))
        self.assertIn('裹在她的口气里', output_instruction(ROLE, 'tech_help'))
        # Comfort replies must not be told to tease first (the long lead is shared with tech_help).
        self.assertNotIn('先嫌一句', output_instruction(ROLE, 'emotional'))

    def test_other_roles_keep_the_default_instruction(self):
        self.assertIn('先答对再带口吻', output_instruction(NORMAL, 'tech_help'))

    def test_retry_guidance_is_card_driven(self):
        self.assertIn('不要客服腔、长辈腔、说教或捧哏', retry_guidance(ROLE))
        self.assertNotIn('傻白甜', retry_guidance(ROLE))
        self.assertEqual(retry_guidance(NORMAL), '保持当前角色的行为规则。')


if __name__ == '__main__':
    unittest.main()
