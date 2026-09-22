import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from reply_pipeline import (CUSTOM_GEN, NORMAL_CHAT, PERSONA_CHAT, clean_reply,
                            process_reply)
from test_bot import Fixture


class ReplyPipelineUnit(unittest.TestCase):
    def test_markdown_emphasis_and_heading_are_cleaned(self):
        self.assertEqual(clean_reply('# 标题\n**粗体**与__强调__'), '标题\n粗体与强调')

    def test_fenced_and_inline_code_are_preserved(self):
        text = "**说明**\n```python\nvalue = '**keep**'\n```\n`__init__`"
        result = clean_reply(text)
        self.assertIn("```python\nvalue = '**keep**'\n```", result)
        self.assertIn('`__init__`', result)
        self.assertTrue(result.startswith('说明\n'))

    def test_url_and_file_path_are_preserved(self):
        text = '**链接** https://example.com/a_b?q=**x** C:\\Work\\a_b\\file.py'
        result = clean_reply(text)
        self.assertEqual(result, '链接 https://example.com/a_b?q=**x** C:\\Work\\a_b\\file.py')

    def test_json_line_is_not_modified(self):
        payload = '{"label":"**keep**","method":"__init__","count":2}'
        self.assertEqual(clean_reply(payload+'\n**说明**'), payload+'\n说明')

    def test_python_dunder_is_not_mistaken_for_emphasis(self):
        self.assertEqual(clean_reply('调用 __init__，查看 **说明**。'), '调用 __init__，查看 说明。')

    def test_blank_lines_and_trailing_spaces_are_normalized(self):
        self.assertEqual(clean_reply('第一行   \n\n\n\n第二行  '), '第一行\n\n第二行')

    def test_consecutive_duplicate_sentences_are_removed(self):
        self.assertEqual(clean_reply('重复。重复。下一句！下一句！'), '重复。下一句！')

    def test_obvious_ai_tone_is_identified_and_removed(self):
        result = process_reply('作为AI，以下是我的回答：**内容**', NORMAL_CHAT)
        self.assertEqual(result.text, '内容')
        self.assertFalse(result.retry)
        self.assertEqual(result.reason, 'ai_self_reference')

    def test_context_policy_does_not_apply_ai_tone_rules_to_custom_gen(self):
        result = process_reply('以下是我的回答：**内容**', CUSTOM_GEN)
        self.assertEqual(result.text, '以下是我的回答：内容')


class OutputPipelineIntegration(Fixture):
    def test_normal_chat_uses_pipeline_and_stores_clean_text(self):
        self.bot.llm.chat.return_value = '**普通回答**'
        output = self.bot.process(self.e(), 'pipeline-normal')
        self.assertEqual(output[0]['text'], '普通回答')
        self.assertEqual(self.bot.store.context('g:33333', '22222')[-1]['content'], '普通回答')

    def test_custom_gen_uses_pipeline(self):
        self.bot.store.set('g:33333', 'custom_commands', {'/生成': {'mode': 'gen', 'content': '测试'}})
        self.bot.llm.chat.return_value = '**生成回答**'
        self.assertEqual(self.bot.process(self.e(text='/生成'), 'pipeline-gen')[0]['text'], '生成回答')

    def test_persona_uses_pipeline(self):
        self.bot.llm.chat.return_value = '**哼！**'
        self.assertEqual(self.bot.process(self.e(text='瑟瑟'), 'pipeline-persona')[0]['text'], '哼！')

    def test_persona_ooc_retries_once(self):
        self.bot.llm.chat.side_effect = ['作为AI，我不能回答。', '**哼！才不告诉你。**']
        answer = self.bot.process(self.e(text='瑟瑟'), 'pipeline-retry')[0]['text']
        self.assertEqual(answer, '哼！才不告诉你。')
        self.assertEqual(self.bot.llm.chat.call_count, 2)

    def test_persona_second_ooc_uses_existing_fallback(self):
        self.bot.llm.chat.side_effect = ['作为AI，我不能回答。', '我是语言模型，无法回应。']
        answer = self.bot.process(self.e(text='瑟瑟'), 'pipeline-fallback')[0]['text']
        self.assertIn(answer, persona.FALLBACKS)
        self.assertEqual(self.bot.llm.chat.call_count, 2)

    def test_fixed_text_command_is_unchanged(self):
        fixed = '**固定文本**'
        self.bot.store.set('g:33333', 'custom_commands', {'/固定': {'mode': 'text', 'content': fixed}})
        self.assertEqual(self.bot.process(self.e(text='/固定'), 'pipeline-fixed')[0]['text'], fixed)
        self.bot.llm.chat.assert_not_called()

    def test_long_reply_remains_for_forward_send_layer(self):
        answer = '这是一段需要由发送层处理的长回答内容'*100
        self.bot.llm.chat.return_value = answer
        output = self.bot.process(self.e(), 'pipeline-long')
        self.assertEqual(output[0]['text'], answer)
        expanded = self.bot.expand(output, '99999')
        self.assertTrue(expanded)
        self.assertTrue(all(item['kind'] == 'forward' for item in expanded))


if __name__ == '__main__':
    unittest.main()
