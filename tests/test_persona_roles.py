import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from persona_cards import RoleCardError, load_catalog, load_role
from test_bot import Fixture


class RoleCardLoading(unittest.TestCase):
    def test_default_role_is_xiaozayu(self):
        catalog = load_catalog(persona.ROLE_ROOT)
        self.assertEqual(catalog.default.id, 'xiaozayu')
        self.assertEqual(catalog.default.display_name, '小杂鱼')

    def test_normal_role_loads(self):
        role = load_role(persona.ROLE_ROOT/'normal')
        self.assertEqual(role.id, 'normal')
        self.assertIn('普通', role.display_name)
        self.assertEqual(role.states['default'], 'normal')

    def test_missing_role_falls_back_to_default(self):
        catalog = load_catalog(persona.ROLE_ROOT)
        self.assertEqual(catalog.get('missing').id, catalog.default.id)

    def test_damaged_card_does_not_break_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory)/'xiaozayu'
            broken.mkdir()
            (broken/'card.json').write_text('{}', encoding='utf-8')
            (broken/'corpus.json').write_text('{}', encoding='utf-8')
            (broken/'prompt.md').write_text('x', encoding='utf-8')
            catalog = load_catalog(directory)
            self.assertTrue(catalog.default)
            self.assertIn('xiaozayu', catalog.errors)

    def test_missing_fields_raise_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            role_dir = Path(directory)/'broken'
            role_dir.mkdir()
            (role_dir/'card.json').write_text(json.dumps({'id': 'broken'}), encoding='utf-8')
            (role_dir/'corpus.json').write_text('{}', encoding='utf-8')
            (role_dir/'prompt.md').write_text('x', encoding='utf-8')
            with self.assertRaisesRegex(RoleCardError, 'missing fields'):
                load_role(role_dir)

    def test_legacy_exports_use_migrated_card_data(self):
        self.assertEqual(persona.CORPUS, persona.XIAOZAYU.corpus['categories'])
        self.assertEqual(persona.FR_ROUNDS, 3)
        prompt, _ = persona.build_prompt('normal', {'a': 0, 'n': 0, 'last': ''}, [])
        self.assertIn('小杂鱼', prompt)


class RoleCommands(Fixture):
    def admin(self, text, group=33333, ident='role-command'):
        return self.bot.process(self.e(user='11111', group=group, text=text), ident)[0]['text']

    def test_role_list_contains_both_roles(self):
        text = self.admin('/角色列表')
        self.assertIn('xiaozayu', text)
        self.assertIn('normal', text)

    def test_role_command_names_cannot_be_overridden(self):
        reply = self.admin('/指令 添加 /角色 文字 假角色', ident='role-command-conflict')
        self.assertIn('占用', reply)

    def test_regular_user_cannot_change_role(self):
        reply = self.bot.process(self.e(text='/角色 normal'), 'role-denied')[0]['text']
        self.assertIn('指定管理员', reply)
        self.assertIsNone(self.bot.store.get('g:33333', 'persona_role'))

    def test_group_role_switch_and_prompt(self):
        self.admin('/角色 normal', ident='role-switch')
        self.assertEqual(persona.role_for(self.bot.store, 'g:33333').id, 'normal')
        self.bot.llm.chat.return_value = '普通回答'
        self.bot.process(self.e(text='瑟瑟'), 'role-normal-reply')
        prompt = self.bot.llm.chat.call_args[0][1][0]['content']
        self.assertIn('可靠、自然的中文QQ助手', prompt)

    def test_group_role_covers_ordinary_chat_without_keyword(self):
        self.bot.llm.chat.return_value = '杂鱼~连招呼都这么普通。'
        self.bot.process(self.e(text='你好'), 'role-ordinary-reply')
        prompt = self.bot.llm.chat.call_args[0][1][0]['content']
        self.assertIn('小杂鱼', prompt)
        self.assertIn('理论王者、实战青铜', prompt)

    def test_private_ordinary_chat_keeps_generic_assistant(self):
        self.bot.process(self.e(group=None, text='你好'), 'role-private-generic')
        prompt = self.bot.llm.chat.call_args[0][1][0]['content']
        self.assertIn('你是用户的中文QQ助手', prompt)
        self.assertNotIn('理论王者、实战青铜', prompt)

    def test_group_selection_is_isolated(self):
        self.admin('/角色 normal', group=33333, ident='role-a')
        self.assertEqual(persona.role_for(self.bot.store, 'g:33333').id, 'normal')
        self.assertEqual(persona.role_for(self.bot.store, 'g:44444').id, 'xiaozayu')

    def test_private_admin_sets_global_default_and_group_override_wins(self):
        self.admin('/角色 normal', group=None, ident='role-global')
        self.assertEqual(persona.role_for(self.bot.store, 'p:11111').id, 'normal')
        self.assertEqual(persona.role_for(self.bot.store, 'g:44444').id, 'normal')
        self.admin('/角色 xiaozayu', group=33333, ident='role-override')
        self.assertEqual(persona.role_for(self.bot.store, 'g:33333').id, 'xiaozayu')

    def test_group_default_removes_override(self):
        self.admin('/角色 normal', ident='role-set')
        text = self.admin('/角色 默认', ident='role-reset')
        self.assertIn('恢复全局默认', text)
        self.assertEqual(persona.role_for(self.bot.store, 'g:33333').id, 'xiaozayu')

    def test_invalid_stored_role_falls_back_without_crash(self):
        self.bot.store.set('g:33333', 'persona_role', 'not-present')
        self.assertEqual(persona.role_for(self.bot.store, 'g:33333').id, 'xiaozayu')

    def test_old_settings_without_role_are_compatible(self):
        self.assertIsNone(self.bot.store.get('*', 'persona_role'))
        self.assertEqual(persona.role_for(self.bot.store, 'p:22222').id, 'xiaozayu')

    def test_runtime_state_isolated_between_groups(self):
        self.bot.llm.chat.return_value = '诶？！'
        self.bot.process(self.e(group=33333, text='瑟瑟 你真可爱'), 'role-state-a')
        self.assertEqual(self.bot.store.get('g:33333', 'persona_state')['mode'], 'frail')
        self.assertIsNone(self.bot.store.get('g:44444', 'persona_state'))


if __name__ == '__main__':
    unittest.main()
