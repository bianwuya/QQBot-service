"""P8 regression: fake clock, temporary SQLite and mocked network only."""
import copy
from datetime import datetime
from unittest.mock import Mock
import unittest

from test_bot import Fixture, event
import persona
from protocol import normalize, DeliveryUnknown
from social_engine import SocialEngine, messages_for, options, role_policy, safe_text
from social_scheduler import SocialScheduler


class SocialFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 9, 22, 12).timestamp()
        self.engine = SocialEngine(self.bot.store, clock=lambda: self.now, rng=lambda: 0)
        self.bot.social = self.engine
        self.scope = 'g:33333'
        self.role = persona.role_for(self.bot.store, self.scope)
        self.bot.connected = self.bot.online = True
        self.bot.self_id = '99999'
        self.bot.ob.send.return_value = {'message_id': 101}
        self.seq = 1000

    def enable(self):
        self.engine.set_enabled(self.scope, True)

    def observe(self, user='22222', text='今天聊聊普通话题', **kwargs):
        self.seq += 1
        e = self.e(user=user, text=text, mid=self.seq, **kwargs)
        self.engine.observe(e)
        return e

    def topic(self):
        for i in range(4):
            self.observe(user='22222' if i % 2 else '44444')
        return self.engine.choose(self.scope, self.role)


class SocialRules(SocialFixture):
    def test_default_off_and_private_ignored(self):
        self.assertIsNone(self.topic())
        self.assertEqual(self.engine.scopes(), [])
        self.enable()
        self.observe(group=None)
        self.assertEqual(self.engine.scopes(), [])

    def test_topic_and_single_speaker_gate(self):
        self.enable()
        for _ in range(4): self.observe()
        self.assertIsNone(self.engine.choose(self.scope, self.role))
        c = self.topic()
        self.assertEqual(c['reason'], 'topic')
        self.assertLessEqual(len(c['context']), 8)

    def test_daily_limit_and_group_isolation(self):
        self.enable()
        for _ in range(6):
            c = self.topic()
            self.assertIsNotNone(c)
            self.assertTrue(self.engine.reserve(c))
            self.now += 901
        self.assertIsNone(self.topic())
        self.assertEqual(self.engine.state(self.scope)['count'], 6)
        self.assertEqual(self.engine.state('g:44444')['count'], 0)

    def test_cooldown_boundary(self):
        self.enable()
        c = self.topic()
        self.assertTrue(self.engine.reserve(c))
        self.now += 899
        self.assertFalse(self.engine.reserve(c))
        self.now += 1
        self.assertTrue(self.engine.reserve(c))

    def test_quiet_hours_and_wrap(self):
        self.enable()
        for hour in (0, 7):
            self.now = datetime(2026, 9, 22, hour).timestamp()
            self.assertIsNone(self.topic())
        self.now = datetime(2026, 9, 22, 8).timestamp()
        self.assertIsNotNone(self.topic())
        self.engine.cfg.update(quiet_start=22, quiet_end=8)
        self.now = datetime(2026, 9, 22, 23).timestamp()
        self.assertIsNone(self.topic())

    def test_two_unanswered_reduce_probability(self):
        self.enable()
        self.bot.store.set(self.scope, 'social_budget', dict(self.engine.state(self.scope), unanswered=2))
        self.engine.rng = lambda: role_policy(self.role)['topic'] / 2
        self.assertIsNone(self.topic())
        self.now += 901
        self.engine.rng = lambda: 0
        self.assertIsNotNone(self.topic())

    def test_three_unanswered_pause_and_toggle_cannot_reset(self):
        self.enable()
        # No human messages between cold-start prompts.
        self.observe()
        for _ in range(3):
            self.engine.sent(self.scope)
            self.now += 901
        state = self.engine.state(self.scope)
        self.assertEqual(state['unanswered'], 3)
        self.assertTrue(state['paused'])
        self.engine.set_enabled(self.scope, False)
        self.enable()
        self.assertIsNone(self.topic())
        self.now += 86400
        self.assertIsNotNone(self.topic())

    def test_response_window_not_immediately_unanswered(self):
        self.enable()
        self.engine.sent(self.scope)
        self.assertEqual(self.engine.state(self.scope)['unanswered'], 0)
        self.now += 60
        self.observe()
        self.now += 901
        self.assertEqual(self.engine.state(self.scope)['unanswered'], 0)

    def test_third_message_can_still_receive_response(self):
        self.enable()
        self.bot.store.set(self.scope, 'social_budget', dict(self.engine.state(self.scope), unanswered=2))
        self.engine.sent(self.scope)
        self.now += 30
        self.observe()
        self.assertFalse(self.engine.state(self.scope).get('paused', False))
        self.assertEqual(self.engine.state(self.scope)['unanswered'], 0)

    def test_idle_after_activity_and_context_expires(self):
        self.enable()
        self.observe()
        self.now += 3601
        c = self.engine.choose(self.scope, self.role)
        self.assertEqual(c['reason'], 'idle')
        self.assertEqual(c['context'], [])

    def test_relationship_uses_same_scope_profile_only(self):
        self.enable()
        for i in range(10):
            self.bot.store.record_memory_interaction(self.scope, '22222', day=str(i % 3))
        self.observe()
        self.assertEqual(self.engine.choose(self.scope, self.role)['reason'], 'relationship')
        self.assertIsNone(self.bot.store.memory_profile('p:22222', '22222'))

    def test_duplicate_self_media_command_and_bounds(self):
        self.enable()
        e = self.observe()
        self.engine.observe(e)
        self.assertEqual(len(self.engine.groups[self.scope]['window']), 1)
        e = dict(e, owner=e['self_id'], key='self')
        self.engine.observe(e)
        self.assertEqual(len(self.engine.groups[self.scope]['window']), 1)
        for _ in range(20): self.observe(text='x' * 500)
        window = self.engine.groups[self.scope]['window']
        self.assertEqual(len(window), 8)
        self.assertTrue(all(len(m[2]) <= 160 for m in window))
        self.observe(text='/下载 https://example.com')
        self.assertTrue(all(not m[2].startswith('/') for m in window))
        self.now += 601
        self.engine.scopes()
        self.assertEqual(len(window), 0)

    def test_role_policy_and_behavior_are_data_driven(self):
        self.enable()
        normal = persona.find_role('normal')
        self.assertNotEqual(role_policy(normal), role_policy(self.role))
        c = self.topic()
        self.assertIn(normal.data['social_behavior'], messages_for(normal, c)[0]['content'])
        self.now += 901
        disabled = copy.deepcopy(self.role)
        disabled.data['social_policy'] = {'enabled': False}
        self.topic()  # consumes rule sample for original role
        self.now += 901
        for _ in range(4): self.observe()
        self.assertIsNone(self.engine.choose(self.scope, disabled))

    def test_failed_probability_throttled_without_model(self):
        self.enable()
        self.engine.rng = Mock(return_value=1)
        self.assertIsNone(self.topic())
        self.assertIsNone(self.topic())
        self.engine.rng.assert_called_once()
        self.bot.llm.chat.assert_not_called()

    def test_restart_persists_budget_not_window(self):
        self.enable()
        self.engine.reserve(self.topic())
        fresh = SocialEngine(self.bot.store, clock=lambda: self.now)
        self.assertEqual(fresh.state(self.scope)['count'], 1)
        self.assertEqual(fresh.scopes(), [])

    def test_inflight_reservation_is_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        self.enable()
        candidate = self.topic()
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: self.engine.reserve(candidate), range(8)))
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(self.engine.state(self.scope)['count'], 1)

    def test_group_window_global_bound(self):
        for gid in range(200):
            self.engine.set_enabled('g:'+str(gid+1), True)
            self.observe(group=gid+1)
        self.assertEqual(len(self.engine.groups), 128)

    def test_restart_keeps_unanswered_and_cooldown(self):
        from store import Store
        self.enable()
        candidate = self.topic()
        self.engine.reserve(candidate)
        self.engine.sent(self.scope)
        other = Store(self.root/'state/bot.sqlite3')
        try:
            fresh = SocialEngine(other, clock=lambda: self.now+901)
            self.assertTrue(fresh.enabled(self.scope))
            self.assertEqual(fresh.state(self.scope)['count'], 1)
            self.assertEqual(fresh.state(self.scope)['unanswered'], 1)
            self.assertEqual(fresh.scopes(), [])
        finally:
            other.db.close()

    def test_limits_fail_conservative(self):
        c = options({'daily_limit': 100, 'cooldown_seconds': 1, 'topic_min': 100})
        self.assertEqual(c['daily_limit'], 6)
        self.assertEqual(c['cooldown_seconds'], 900)
        self.assertEqual(c['topic_min'], 8)
        self.assertEqual(options('bad')['daily_limit'], 6)


class SocialIntegration(SocialFixture):
    def test_admin_only_group_commands(self):
        for role in ('owner', 'admin', 'member'):
            result = self.bot.process(self.e(text='/主动 开', role=role), 'deny-'+role)
            self.assertIn('指定管理员', result[0]['text'])
        self.assertFalse(self.engine.enabled(self.scope))
        self.bot.process(self.e(user='11111', text='/主动 开'), 'enable')
        self.assertTrue(self.engine.enabled(self.scope))
        result = self.bot.process(self.e(user='11111', group=None, text='/主动 开'), 'private')
        self.assertIn('请在群内', result[0]['text'])
        self.bot.process(self.e(user='11111', text='/主动 关'), 'disable')
        self.assertFalse(self.engine.enabled(self.scope))

    def test_ingest_observes_unaddressed_without_passive_job(self):
        self.enable()
        self.bot.ingest(event(text='今天聊聊', mid=123))
        self.assertEqual(len(self.engine.groups[self.scope]['window']), 1)
        self.assertEqual(self.bot.store.counts(), {})
        self.bot.ingest(event(user='99999', text='自己的主动消息', mid=124))
        self.assertEqual(len(self.engine.groups[self.scope]['window']), 1)

    def test_success_plain_text_outbox_no_memory_or_context_leak(self):
        self.enable()
        self.bot.store.remember('p:22222', '22222', 'PRIVATE_SECRET', 'secret')
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_called_once_with(self.scope, [{'type':'text','data':{'text':'测试回答'}}])
        self.assertEqual(self.bot.store.counts(), {'done': 1})
        self.assertEqual(self.bot.store.context(self.scope, '99999'), [])
        self.assertIsNone(self.bot.store.memory_profile(self.scope, '99999'))
        self.assertNotIn('PRIVATE_SECRET', str(self.bot.llm.chat.call_args))
        rows = self.bot.store.db.execute('SELECT payload FROM jobs').fetchall()
        self.assertNotIn('今天聊聊', rows[0][0])

    def test_model_skip_cost_reserved_and_no_send(self):
        self.enable()
        self.bot.llm.chat.return_value = '<SKIP>'
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_not_called()
        self.assertEqual(self.engine.state(self.scope)['count'], 1)
        self.assertEqual(self.engine.state(self.scope)['unanswered'], 0)

    def test_commands_cq_at_urls_never_sent_or_executed(self):
        for text in ('/停用', '[CQ:at,qq=all]', '@全体', 'https://example.com'):
            self.assertEqual(safe_text(text), '')
        self.enable()
        self.bot.llm.chat.return_value = '/下载 https://example.com'
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_not_called()
        self.assertIsNone(self.bot.store.get(self.scope, 'enabled'))

    def test_unknown_delivery_records_receipt_without_retry(self):
        self.enable()
        self.bot.ob.send.side_effect = DeliveryUnknown('test')
        self.bot.social_attempt(self.topic())
        self.assertEqual(self.bot.store.counts(), {'unknown': 1})
        self.bot.ob.send.assert_called_once()
        self.assertIsNone(self.topic())
        receipt = self.bot.store.db.execute('SELECT status FROM delivery').fetchone()[0]
        self.assertEqual(receipt, 'unknown')

    def test_model_failure_no_error_spam_and_no_refund(self):
        self.enable()
        self.bot.llm.chat.side_effect = RuntimeError('test')
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_not_called()
        self.assertEqual(self.engine.state(self.scope)['count'], 1)
        self.assertEqual(self.bot.store.counts(), {'failed': 1})

    def test_disable_or_role_change_during_generation_cancels(self):
        self.enable()
        def disable(*args, **kwargs):
            self.engine.set_enabled(self.scope, False)
            return '测试回答'
        self.bot.llm.chat.side_effect = disable
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_not_called()
        self.now += 901
        self.enable()
        def change(*args, **kwargs):
            self.bot.store.set(self.scope, 'persona_role', 'normal')
            return '测试回答'
        self.bot.llm.chat.side_effect = change
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_not_called()

    def test_new_activity_during_generation_discards_stale_prompt(self):
        self.enable()
        def new_message(*args, **kwargs):
            self.observe(text='换个话题')
            return '测试回答'
        self.bot.llm.chat.side_effect = new_message
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_not_called()

    def test_disabled_capability_and_offline_prevent_calls(self):
        self.enable()
        c = self.topic()
        self.bot.connected = False
        self.bot.social_attempt(c)
        self.bot.llm.chat.assert_not_called()
        self.bot.connected = True
        self.bot.store.set(self.scope, 'cap:chat', False)
        self.bot.social_attempt(c)
        self.bot.llm.chat.assert_not_called()

    def test_passive_unchanged_and_not_double_triggered(self):
        self.enable()
        e = self.e(text='普通问题')
        self.engine.observe(e, handled=True)
        self.assertIsNone(self.engine.choose(self.scope, self.role))
        self.assertEqual(self.bot.process(e, 'passive')[0]['text'], '测试回答')
        self.assertEqual(len(self.bot.store.context(self.scope, e['owner'])), 2)

    def test_quiet_boundary_during_generation_cancels(self):
        self.engine.cfg.update(quiet_start=13, quiet_end=14)
        self.enable()
        def cross_boundary(*args, **kwargs):
            self.now = datetime(2026, 9, 22, 13).timestamp()
            return '测试回答'
        self.bot.llm.chat.side_effect = cross_boundary
        self.bot.social_attempt(self.topic())
        self.bot.ob.send.assert_not_called()

    def test_budget_is_not_reset_by_disable_enable(self):
        self.enable()
        self.engine.reserve(self.topic())
        self.engine.set_enabled(self.scope, False)
        self.enable()
        self.assertEqual(self.engine.state(self.scope)['count'], 1)
        self.assertIsNone(self.topic())

    def test_ooc_dropped_without_paid_retry(self):
        self.enable()
        self.bot.llm.chat.return_value = '作为AI，我不能回答。'
        self.bot.social_attempt(self.topic())
        self.bot.llm.chat.assert_called_once()
        self.bot.ob.send.assert_not_called()

    def test_orphan_queued_social_job_never_replayed(self):
        e = dict(self.e(), social=True, owner='99999', text='')
        ident = self.bot.store.accept(e, self.cfg['limits'])
        self.bot.stop = Mock()
        self.bot.stop.wait.side_effect = [False, True]
        self.bot.worker()
        self.assertEqual(self.bot.store.job(ident)['status'], 'interrupted')
        self.bot.llm.chat.assert_not_called()
        self.bot.ob.send.assert_not_called()

    def test_processing_and_sending_social_jobs_recover_without_retry(self):
        from store import Store
        ids = []
        for n, status in enumerate(('processing', 'sending')):
            e = dict(self.e(mid=700+n), social=True, owner='99999', text='')
            ident = self.bot.store.accept(e, self.cfg['limits'])
            self.bot.store.update(ident, status)
            ids.append(ident)
        other = Store(self.root/'state/bot.sqlite3')
        try:
            self.assertEqual(other.job(ids[0])['status'], 'interrupted')
            self.assertEqual(other.job(ids[1])['status'], 'unknown')
            self.assertIsNone(other.take())
        finally:
            other.db.close()

    def test_late_disable_is_rechecked_at_delivery(self):
        from safe_net import Rejected
        self.enable()
        event=dict(self.e(),social=True,owner='99999')
        ident=self.bot.store.accept(event,self.cfg['limits'])
        self.engine.set_enabled(self.scope,False)
        with self.assertRaises(Rejected):self.bot.deliver(event,ident,[{'kind':'text','text':'late'}])
        self.bot.ob.send.assert_not_called()

    def test_scheduler_only_callback_and_throttle(self):
        self.enable()
        for i in range(4): self.observe(user='22222' if i % 2 else '44444')
        cb = Mock()
        sched = SocialScheduler(self.engine, lambda scope: self.role, cb, clock=lambda: self.now)
        sched.tick();sched.tick()
        cb.assert_called_once()
        self.bot.llm.chat.assert_not_called()


if __name__ == '__main__':
    unittest.main()
