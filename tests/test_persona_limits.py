import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards import limit_for, load_role
from test_bot import Fixture


class PersonaLimitTiers(unittest.TestCase):
    def test_xiaozayu_limit_for_intent(self):
        self.assertEqual(limit_for(persona.XIAOZAYU, 'tech_help'), 200)
        self.assertEqual(limit_for(persona.XIAOZAYU, 'emotional'), 160)
        self.assertEqual(limit_for(persona.XIAOZAYU, 'chat'), 60)
        self.assertEqual(persona.reply_limit(persona.XIAOZAYU, 'tech_help'), 200)
        self.assertEqual(persona.reply_limit(persona.XIAOZAYU), 60)

    def test_old_card_without_tiers_keeps_max_chars(self):
        with tempfile.TemporaryDirectory() as directory:
            src = persona.ROLE_ROOT/'xiaozayu'
            dst = Path(directory)/'xiaozayu'
            dst.mkdir()
            shutil.copy(src/'corpus.json', dst/'corpus.json')
            shutil.copy(src/'prompt.md', dst/'prompt.md')
            card = json.loads((src/'card.json').read_text('utf-8-sig'))
            card['reply_limits'] = {'max_chars': 60, 'instruction': '只输出回复本身。'}
            card.pop('behaviors', None)
            card.pop('intents', None)
            card.pop('ooc', None)
            (dst/'card.json').write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding='utf-8')
            role = load_role(dst)
            self.assertEqual(limit_for(role, 'tech_help'), 60)
            self.assertEqual(limit_for(role, 'chat'), 60)


class PersonaLimitIntegration(Fixture):
    def answer(self, text, value, ident):
        self.bot.llm.chat.return_value = value
        return self.bot.process(self.e(text=text, group=33333), ident)[0]['text']

    def test_chat_tier_still_truncates_at_60(self):
        reply = self.answer('你好', '衔'*150, 'limit-chat')
        self.assertLessEqual(len(reply), 60)

    def test_tech_help_can_exceed_60_but_stays_under_tier(self):
        value = '先检查报错的完整堆栈，确认 KeyError 缺的键；打印 dict.keys() 和访问处，给缺失键加默认值或改成 get。'*3
        reply = self.answer('Python 报 KeyError 怎么查', value, 'limit-tech')
        self.assertGreater(len(reply), 60)
        self.assertLessEqual(len(reply), 200)


if __name__ == '__main__':
    unittest.main()
