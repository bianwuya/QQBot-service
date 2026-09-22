# -*- coding: utf-8 -*-
import json
import shutil
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards import RoleCardError, load_role
from test_bot import Fixture


XIAOZAYU = persona.XIAOZAYU
NORMAL = persona.CATALOG.roles['normal']


class PersonaOocRules(unittest.TestCase):
    def test_hard_words_force_retry(self):
        self.assertTrue(persona.ooc_check('作为AI，我不能回答。'))
        self.assertTrue(persona.ooc_check('我是语言模型，无法回应。'))
        scan = persona.ooc_scan('作为AI，我不能回答。')
        self.assertTrue(scan['retry'])
        self.assertEqual(scan['kind'], 'hard')

    def test_service_tone_forces_retry(self):
        for line in ('很高兴为您服务，请问还有什么可以帮到您？',
                     '感谢您的理解，建议您咨询官方文档。'):
            scan = persona.ooc_scan(line)
            self.assertTrue(scan['retry'], line)
            self.assertEqual(scan['kind'], 'service_tone', line)
            self.assertTrue(persona.ooc_check(line), line)

    def test_soft_words_warn_without_retry(self):
        scan = persona.ooc_scan('抱歉，这个我还真没把握。')
        self.assertFalse(scan['retry'])
        self.assertTrue(scan['soft'])
        self.assertEqual(scan['kind'], 'soft')
        self.assertFalse(persona.ooc_check('抱歉，这个我还真没把握。'))

    def test_soft_allow_keeps_honest_limits_clean(self):
        for line in ('我不能确定这个字段一定会返回。',
                     '我不能保证结果，先跑一遍看看。',
                     '抱歉，我现在帮你看看配置。',
                     '抱歉，我确认一下再说。'):
            scan = persona.ooc_scan(line)
            self.assertFalse(scan['retry'], line)
            self.assertFalse(scan['soft'], line)

    def test_identity_honest_admit_is_not_killed(self):
        for line in ('行吧，被你抓到了，我是 Bot 程序一个。',
                     '认真说，我是 Bot，不是人。'):
            self.assertFalse(persona.ooc_check(line), line)

    def test_normal_role_uses_structured_ooc(self):
        self.assertTrue(persona.ooc_check('作为人工智能，建议您咨询官方。', role=NORMAL))
        scan = persona.ooc_scan('抱歉，这个我不确定。', role=NORMAL)
        self.assertFalse(scan['retry'])
        self.assertTrue(scan['soft'])

    def test_legacy_flat_ooc_words_still_load_as_hard(self):
        with tempfile.TemporaryDirectory() as directory:
            src = persona.ROLE_ROOT/'xiaozayu'
            dst = Path(directory)/'xiaozayu'
            dst.mkdir()
            shutil.copy(src/'corpus.json', dst/'corpus.json')
            shutil.copy(src/'prompt.md', dst/'prompt.md')
            card = json.loads((src/'card.json').read_text('utf-8-sig'))
            card.pop('ooc', None)
            card['ooc_words'] = ['作为AI', '客服小姐姐']
            (dst/'card.json').write_text(json.dumps(card, ensure_ascii=False, indent=2),
                                         encoding='utf-8')
            role = load_role(dst)
            line = '别的先不说，客服小姐姐上线。'
            self.assertTrue(persona.ooc_check(line, role=role))
            self.assertEqual(persona.ooc_scan(line, role=role)['kind'], 'hard')

    def test_malformed_ooc_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            src = persona.ROLE_ROOT/'xiaozayu'
            dst = Path(directory)/'xiaozayu'
            dst.mkdir()
            shutil.copy(src/'corpus.json', dst/'corpus.json')
            shutil.copy(src/'prompt.md', dst/'prompt.md')
            card = json.loads((src/'card.json').read_text('utf-8-sig'))
            card['ooc'] = {'hard': '作为AI'}
            (dst/'card.json').write_text(json.dumps(card, ensure_ascii=False, indent=2),
                                         encoding='utf-8')
            with self.assertRaises(RoleCardError):
                load_role(dst)


class PersonaOocIntegration(Fixture):
    def test_soft_allow_answer_is_not_retried(self):
        self.bot.llm.chat.return_value = '抱歉，我现在帮你看看配置。'
        answer = self.bot.process(self.e(text='瑟瑟', group=33333), 'ooc-soft')[0]['text']
        self.assertEqual(answer, '抱歉，我现在帮你看看配置。')
        self.assertEqual(self.bot.llm.chat.call_count, 1)

    def test_hard_answer_still_retries(self):
        self.bot.llm.chat.side_effect = ['作为AI，我不能回答。', '**哼！才不告诉你。**']
        answer = self.bot.process(self.e(text='瑟瑟', group=33333), 'ooc-hard')[0]['text']
        self.assertEqual(answer, '哼！才不告诉你。')
        self.assertEqual(self.bot.llm.chat.call_count, 2)


if __name__ == '__main__':
    unittest.main()
