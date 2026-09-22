# -*- coding: utf-8 -*-
"""safe_net DoH fallback: honour proxies running fake-IP/TUN system DNS."""
import unittest

from safe_net import Rejected, public_target


FAKE_SYSTEM_RESOLVER = lambda *a, **k: [(2, 1, 6, '', ('198.18.0.85', 443))]


class FakeIpFallback(unittest.TestCase):
    def test_system_fake_ip_rescued_by_doh(self):
        u, host, port, ip = public_target('https://v.douyin.com/abc/', doh=lambda h: ['104.244.46.57'])
        self.assertEqual(host, 'v.douyin.com')
        self.assertEqual(ip, '104.244.46.57')

    def test_fake_ip_still_blocked_when_doh_empty(self):
        with self.assertRaises(Rejected) as cm:
            public_target('https://v.douyin.com/abc/', doh=lambda h: [])
        self.assertIn('禁止访问', str(cm.exception))

    def test_doh_reserved_answer_never_used(self):
        with self.assertRaises(Rejected):
            public_target('https://v.douyin.com/abc/', doh=lambda h: ['169.254.169.254'])

    def test_custom_resolver_never_triggers_doh(self):
        # Injected resolvers (tests/embedding) keep the original strict behaviour.
        with self.assertRaises(Rejected):
            public_target('https://v.douyin.com/abc/', resolver=FAKE_SYSTEM_RESOLVER,
                          doh=lambda h: ['104.244.46.57'])

    def test_ip_literal_private_still_blocked(self):
        with self.assertRaises(Rejected):
            public_target('http://127.0.0.1/', doh=lambda h: ['104.244.46.57'])

    def test_ip_literal_blocked_even_if_doh_answers(self):
        with self.assertRaises(Rejected):
            public_target('http://169.254.169.254/latest/meta-data', doh=lambda h: ['104.244.46.57'])


if __name__ == '__main__':
    unittest.main()
