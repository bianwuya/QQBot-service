import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards import classify, examples_for, fallback_line, load_role
from test_bot import Fixture


XIAOZAYU = persona.XIAOZAYU
CORPUS = XIAOZAYU.corpus
FALLBACKS = CORPUS['fallbacks']


class PersonaSampling(unittest.TestCase):
    def test_normal_plan_no_longer_injects_refusal(self):
        _, _, chosen = examples_for(XIAOZAYU, 'normal', [])
        self.assertTrue(chosen)
        self.assertFalse(any(line in CORPUS['categories']['refuse'] for line in chosen))
        self.assertTrue(any(line in CORPUS['categories']['daily'] for line in chosen))

    def test_intent_plan_adds_task_aware_examples(self):
        _, _, chosen = examples_for(XIAOZAYU, 'normal', [], 'tech_help')
        self.assertTrue(any(line in CORPUS['categories']['help'] for line in chosen))
        self.assertTrue(any(line in CORPUS['categories']['uncertain'] for line in chosen))
        _, _, emotional = examples_for(XIAOZAYU, 'normal', [], 'emotional')
        self.assertTrue(any(line in CORPUS['categories']['care'] for line in emotional))

    def test_lru_still_excludes_used_across_merged_plans(self):
        used = CORPUS['categories']['daily'][:2] + CORPUS['categories']['help'][:1]
        _, _, chosen = examples_for(XIAOZAYU, 'normal', used, 'tech_help')
        self.assertFalse(any(line in used for line in chosen))

    def test_fallbacks_are_selected_by_intent(self):
        self.assertIn(fallback_line(XIAOZAYU, [], 'tech_help'), FALLBACKS['tech_help'])
        self.assertIn(fallback_line(XIAOZAYU, [], 'emotional'), FALLBACKS['emotional'])
        self.assertIn(fallback_line(XIAOZAYU, [], 'boundary'), FALLBACKS['boundary'])
        self.assertIn(fallback_line(XIAOZAYU, [], 'missing'), FALLBACKS['generic'])

    def test_legacy_flat_fallback_array_still_loads(self):
        role = SimpleNamespace(corpus={'fallbacks': ['旧兜底'], 'categories': {}})
        self.assertEqual(fallback_line(role, [], 'tech_help'), '旧兜底')
        with tempfile.TemporaryDirectory() as directory:
            src = persona.ROLE_ROOT/'xiaozayu'
            dst = Path(directory)/'xiaozayu'
            dst.mkdir()
            shutil.copy(src/'card.json', dst/'card.json')
            shutil.copy(src/'prompt.md', dst/'prompt.md')
            corpus = json.loads((src/'corpus.json').read_text('utf-8-sig'))
            corpus['fallbacks'] = ['旧兜底']
            (dst/'corpus.json').write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding='utf-8')
            loaded = load_role(dst)
            self.assertEqual(fallback_line(loaded, [], 'tech_help'), '旧兜底')

    def test_insult_scenario_uses_role_trigger(self):
        self.assertEqual(classify(XIAOZAYU, '这破 Bot 真笨'), 'insult')


class PersonaFallbackIntegration(Fixture):
    def test_emotional_failure_uses_emotional_fallback(self):
        self.bot.llm.chat.side_effect = ['作为AI，我不能回答。', '我是语言模型，无法回应。']
        reply = self.bot.process(self.e(text='我今天很难受'), 'fallback-emotional')[0]['text']
        self.assertIn(reply, FALLBACKS['emotional'])

    def test_tech_failure_uses_tech_fallback(self):
        from safe_net import Rejected
        self.bot.llm.chat.side_effect = Rejected('HTTP 503')
        reply = self.bot.process(self.e(text='Python 报 KeyError 怎么查'), 'fallback-tech')[0]['text']
        self.assertIn(reply, FALLBACKS['tech_help'])


if __name__ == '__main__':
    unittest.main()
