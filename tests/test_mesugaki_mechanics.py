"""Mechanics of the mesugaki rework: sentence-level splitting, typing delay, poke gating, phrase repeat, tease levels."""
import sys
from pathlib import Path
from unittest.mock import Mock
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona
from app import GroupChatOutput
from persona import tease_settings
from persona_cards import build_prompt, classify, examples_for
from persona_cards.engine import style_fatigue_notes
from protocol import LLM
from reply_context import phrase_repeat
from share_reply import ReplyPolicy
from test_bot import LIMITS, Fixture

ROLE = persona.XIAOZAYU


def policy(rng=0.0):
    return ReplyPolicy(store=None, rng=lambda: rng)


class SentenceSplit(unittest.TestCase):
    def test_only_splits_at_finished_sentences(self):
        self.assertIsNone(policy().split('这件事先看第一步，接着观察第二步，最后再总结一下结果吧。'))
        self.assertEqual(policy().split('这件事先看第一步。接着观察第二步。'), ['这件事先看第一步。', '接着观察第二步。'])

    def test_short_parts_and_dependent_openers_are_not_split(self):
        self.assertIsNone(policy().split('好的。我知道了，等我想想怎么说才好吧。'))
        self.assertIsNone(policy().split('这事我先记下了。可是你得再等一会儿才行哦。'))

    def test_probability_is_low_by_default_and_respects_rng(self):
        text = '这件事先看第一步。接着观察第二步。'
        self.assertIsNone(policy(.5).split(text))
        self.assertIsNotNone(policy(.05).split(text))

    def test_second_part_gets_a_typing_delay_between_one_and_three_seconds(self):
        outputs = policy(0).format({'at': False, 'owner': '22222', 'text': '随便聊聊'}, '这件事先看第一步。接着观察第二步。', [], poke_probability=0)
        self.assertEqual(len(outputs), 2)
        self.assertNotIn('delay', outputs[0])
        self.assertTrue(1.0 <= outputs[1]['delay'] <= 3.0)


class PokeGating(unittest.TestCase):
    def outputs(self, intent, answer='随口接一句。'):
        event = {'at': False, 'owner': '22222', 'text': 'x'}
        if intent:
            event['_persona_intent'] = intent
        return policy(0).format(event, answer, [], poke_probability=1)

    def test_light_chat_can_be_poked(self):
        for intent in (None, 'chat', 'greeting', 'insult', 'flirt'):
            with self.subTest(intent=intent):
                self.assertEqual(self.outputs(intent)[-1]['action']['type'], 'poke')

    def test_serious_replies_are_never_poked(self):
        for intent in ('tech_help', 'emotional', 'correction', 'identity', 'memory', 'boundary', 'unclear'):
            with self.subTest(intent=intent):
                self.assertFalse(any(o.get('kind') == 'share_action' for o in self.outputs(intent)))

    def test_long_answers_are_not_poked(self):
        self.assertFalse(any(o.get('kind') == 'share_action' for o in self.outputs('chat', '很长的回答。' * 10)))


class PhraseRepeat(unittest.TestCase):
    def test_stock_phrase_seen_twice_recently_is_flagged(self):
        self.assertTrue(phrase_repeat('我看你还是先管好自己吧', ['先管好自己那张嘴吧', '你先管好自己再说', '今天天气不错']))

    def test_single_earlier_use_or_short_overlap_is_fine(self):
        self.assertFalse(phrase_repeat('我看你还是先管好自己吧', ['先管好自己那张嘴吧', '今天天气不错']))
        self.assertFalse(phrase_repeat('杂鱼~就这？', ['杂鱼~你好', '杂鱼~再见']))


class PhraseRepeatIntegration(Fixture):
    def answer(self, *outputs, recent):
        self.bot.llm.chat.side_effect = list(outputs)
        messages = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': '今天天气不错'}]
        return self.bot.persona_answer('g:33333', messages, ROLE, 'chat', [], recent_replies=recent)[0]

    def test_repeated_stock_phrase_triggers_exactly_one_rewrite(self):
        result = self.answer('哼，别以为我会理你', '诶，随你怎么说啦', recent=['哼，别以为我会记住你', '别以为我会原谅你哦'])
        self.assertEqual(result, '诶，随你怎么说啦')
        self.assertEqual(self.bot.llm.chat.call_count, 2)

    def test_no_rewrite_when_the_phrase_was_used_only_once(self):
        result = self.answer('哼，别以为我会理你', recent=['哼，别以为我会记住你', '今天天气不错'])
        self.assertEqual(result, '哼，别以为我会理你')
        self.assertEqual(self.bot.llm.chat.call_count, 1)


class TeaseLevels(Fixture):
    def prompt(self, **context):
        ctx = dict({'intent': 'chat'}, **context)
        return build_prompt(ROLE, {'mode': 'normal', 'left': 0}, {'a': 0, 'n': 2, 'last': '2026-09-30'}, ctx)[0]

    def test_default_is_mild_and_unknown_levels_fall_back(self):
        key, label, _ = tease_settings(ROLE)
        self.assertEqual((key, label), ('mild', '温和'))
        self.assertIn('当前是温和档', self.prompt())
        self.assertIn('当前是辛辣档', self.prompt(tease_level='spicy'))
        self.assertIn('当前是温和档', self.prompt(tease_level='nonsense'))

    def test_roles_without_the_setting_have_none(self):
        self.assertEqual(tease_settings(persona.CATALOG.roles['normal']), (None, '', ''))

    def test_mild_prefers_mild_reference_lines(self):
        lines = ROLE.corpus['provenance']['lines']
        provocation = ROLE.corpus['categories']['provocation']
        seen_strong = False
        for seed in range(len(provocation) + 2):
            _, _, mild = examples_for(ROLE, 'normal', [], 'chat', None, seed, 'mild')
            self.assertTrue(all(lines[line]['strength'] == 'mild' for line in mild if line in provocation))
            _, _, spicy = examples_for(ROLE, 'normal', [], 'chat', None, seed, 'spicy')
            seen_strong = seen_strong or any(lines[line]['strength'] != 'mild' for line in spicy if line in provocation)
        self.assertTrue(seen_strong)

    def test_admin_command_sets_reads_and_resets_the_level(self):
        say = lambda text, ident, **kw: self.bot.process(self.e(user='11111', text=text, **kw), ident)[0]['text']
        self.assertIn('温和（全局默认）', say('/嘲讽', 'tease-1'))
        self.assertIn('本群嘲讽强度已设置为：辛辣', say('/嘲讽 辛辣', 'tease-2'))
        self.assertEqual(self.bot.store.get('g:33333', 'tease_level'), 'spicy')
        self.assertIn('辛辣（本群覆盖）', say('/嘲讽', 'tease-3'))
        self.assertIn('已恢复', say('/嘲讽 默认', 'tease-4'))
        self.assertIsNone(self.bot.store.get('g:33333', 'tease_level'))
        self.assertIn('用法', say('/嘲讽 离谱', 'tease-5'))

    def test_non_admin_cannot_change_the_level(self):
        reply = self.bot.process(self.e(user='22222', text='/嘲讽 辛辣'), 'tease-6')[0]['text']
        self.assertIn('指定管理员', reply)
        self.assertIsNone(self.bot.store.get('g:33333', 'tease_level'))

    def test_private_chat_sets_the_global_default(self):
        self.bot.process(self.e(user='11111', group=None, text='/嘲讽 标准'), 'tease-7')
        self.assertEqual(self.bot.store.get('*', 'tease_level'), 'standard')
        self.assertIn('标准（全局默认）', self.bot.process(self.e(user='11111', text='/嘲讽'), 'tease-8')[0]['text'])

    def test_status_command_shows_the_level(self):
        self.assertIn('嘲讽强度：温和', self.bot.process(self.e(user='11111', text='/人格状态'), 'tease-9')[0]['text'])

    def test_level_reaches_the_model_prompt(self):
        self.bot.process(self.e(user='11111', text='/嘲讽 辛辣'), 'tease-10')
        self.bot.llm.chat.return_value = '哼，就这？'
        self.bot.process(self.e(text='今天天气不错'), 'tease-11')
        self.assertIn('当前是辛辣档', self.bot.llm.chat.call_args[0][1][0]['content'])

    def test_family_insults_route_to_the_insult_intent(self):
        for text in ('你妈知道你在群里吗', '我操你', '日你'):
            with self.subTest(text=text):
                self.assertEqual(classify(ROLE, text), 'insult')


class DeliveryPause(Fixture):
    def test_pause_happens_between_split_parts_only(self):
        self.cfg['share_reply_enabled'] = True
        self.bot.typing_pause = Mock()
        self.bot.ob.send.return_value = {'message_id': 1}
        e = self.e(text='你好')
        outputs = [{'kind': 'text', 'text': '第一句。', 'share_chat': True},
                   {'kind': 'text', 'text': '第二句。', 'share_chat': True, 'delay': 1.5}]
        ident = self.bot.store.accept(e, LIMITS)
        self.bot.deliver(e, ident, GroupChatOutput(outputs))
        self.bot.typing_pause.assert_called_once_with(1.5)
        self.assertEqual(self.bot.ob.send.call_count, 2)


class SamplingPayload(unittest.TestCase):
    def llm(self):
        llm = LLM({'base_url': 'http://127.0.0.1:1/v1', 'key_file': 'unused', 'default_model': 'm'})
        llm.request = Mock(return_value={'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
        return llm

    def test_sampling_is_clamped_and_allow_listed(self):
        llm = self.llm()
        self.assertEqual(llm.chat('m', [], max_tokens=50, sampling={'temperature': 5, 'top_p': .9, 'frequency_penalty': -9, 'seed': 1, 'stop': ['x']}), 'ok')
        payload = llm.request.call_args.args[1]
        self.assertEqual((payload['temperature'], payload['top_p'], payload['frequency_penalty']), (2.0, .9, -2.0))
        self.assertNotIn('seed', payload)
        self.assertNotIn('stop', payload)

    def test_no_sampling_keeps_the_old_payload(self):
        llm = self.llm()
        llm.chat('m', [], max_tokens=50)
        self.assertEqual(llm.request.call_args.args[1], {'model': 'm', 'messages': [], 'stream': False, 'max_tokens': 50})


class StyleFatigue(unittest.TestCase):
    def prompt(self, recent):
        return build_prompt(ROLE, {'mode': 'normal', 'left': 0}, {'a': 0, 'n': 2, 'last': '2026-09-30'},
                            {'intent': 'chat', 'recent_replies': recent})[0]

    def test_overused_address_word_gets_a_nudge(self):
        prompt = self.prompt(['杂鱼你好', '今天不错', '杂鱼酱又来了'])
        self.assertIn('不要再用“杂鱼”称呼', prompt)
        self.assertNotIn('不要再用“杂鱼”称呼', self.prompt(['杂鱼你好', '今天不错', '随便聊聊']))

    def test_other_habits_are_rationed_too(self):
        self.assertIn('不要用“~”拖腔', self.prompt(['哈~', '随便', '诶~']))
        self.assertNotIn('不要用“~”拖腔', self.prompt(['哈~', '随便', '今天不错']))
        self.assertIn('自称用“我”', self.prompt(['本小姐不想理你']))
        self.assertIn('不要用“嘻嘻”', self.prompt(['好啊嘻嘻', '随便', '嗯', '行']))
        self.assertNotIn('不要用“嘻嘻”', self.prompt(['好啊嘻嘻', '嗯', '随便', '行', '再见']))

    def test_senpai_is_suggested_only_in_light_talk_and_only_when_unused(self):
        suggestion = '最近几条回复没用过“前辈”'
        self.assertIn(suggestion, self.prompt(['随便', '嗯']))
        self.assertNotIn(suggestion, self.prompt(['前辈你好', '嗯']))
        serious = build_prompt(ROLE, {'mode': 'normal', 'left': 0}, {'a': 0, 'n': 2, 'last': '2026-09-30'},
                               {'intent': 'emotional', 'recent_replies': ['随便', '嗯']})[0]
        self.assertNotIn(suggestion, serious)

    def test_repeated_opening_gets_a_nudge(self):
        self.assertIn('最近几条都以“哈？”开头', self.prompt(['哈？你说什么', '今天不错', '哈？真的假的']))
        self.assertNotIn('开头，这条换个开头', self.prompt(['哈？你说什么', '今天不错', '诶？真的假的']))

    def test_no_history_or_roles_without_the_config_get_no_nudge(self):
        self.assertEqual(style_fatigue_notes(ROLE, []), [])
        self.assertEqual(style_fatigue_notes(persona.CATALOG.roles['normal'], ['哈？a', '哈？b']), [])


if __name__ == '__main__':
    unittest.main()
