import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards import build_prompt, load_role


XIAOZAYU = persona.XIAOZAYU
STATE = {'mode': 'normal', 'left': 0}
RELATION = {'a': 0, 'n': 0, 'last': ''}


class PersonaBehaviors(unittest.TestCase):
    def test_prompt_injects_current_behavior_rule(self):
        prompt, _ = build_prompt(XIAOZAYU, STATE, RELATION, {'used': [], 'intent': 'tech_help'})
        self.assertIn('禁止编造 API', prompt)
        self.assertIn('其他情境索引', prompt)
        self.assertIn('emotional：', prompt)
        prompt, _ = build_prompt(XIAOZAYU, STATE, RELATION, {'used': [], 'intent': 'emotional'})
        self.assertIn('不许拿对方的难过开玩笑', prompt)

    def test_template_without_behavior_placeholder_degrades(self):
        with tempfile.TemporaryDirectory() as directory:
            src = persona.ROLE_ROOT/'xiaozayu'
            dst = Path(directory)/'xiaozayu'
            dst.mkdir()
            shutil.copy(src/'card.json', dst/'card.json')
            shutil.copy(src/'corpus.json', dst/'corpus.json')
            prompt = '# 角色\n{display_name}\n# 社交行为\n{social_behavior}\n# 输出\n{output_instruction}'
            (dst/'prompt.md').write_text(prompt, encoding='utf-8')
            role = load_role(dst)
            prompt, _ = build_prompt(role, STATE, RELATION, {'used': [], 'intent': 'tech_help'})
            self.assertIn('先虚张声势', prompt)
            self.assertNotIn('禁止编造 API', prompt)

    def test_card_json_validates_behaviors(self):
        card = json.loads((persona.ROLE_ROOT/'xiaozayu'/'card.json').read_text('utf-8-sig'))
        self.assertGreaterEqual(len(card.get('behaviors', {})), 8)


if __name__ == '__main__':
    unittest.main()
