import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('login_helper', ROOT / 'tools/check-login.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def response(data, code=0):
    r = Mock()
    r.json.return_value = {'code': code, 'data': data}
    return r


class LoginHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'napcat/config').mkdir(parents=True)
        (self.root / 'napcat/config/webui.json').write_text(json.dumps({'host': '127.0.0.1', 'port': 6099, 'token': 'fake-only-test-token'}), encoding='utf-8')
        self.nap_patch = patch.object(helper, 'NAP', self.root)
        self.nap_patch.start()
        self.session = Mock()
        self.session.headers = {}
        self.session_patch = patch.object(helper.requests, 'Session', return_value=self.session)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.nap_patch.stop()
        self.temp.cleanup()

    def replies(self, *data):
        self.session.post.side_effect = [response({'Credential': 'fake-signed-credential'})] + [response(d) for d in data]

    def test_read_only_qr_check(self):
        self.replies({'isLogin': False, 'loginPhase': 'waiting_qrcode'}, {'qrcode': 'fake-qr-url'})
        result = helper.inspect_login()
        self.assertTrue(result['qr_available'])
        self.assertFalse(result['qr_refreshed'])
        self.assertNotIn('fake-qr-url', json.dumps(result))
        self.assertNotIn('fake-signed-credential', json.dumps(result))
        self.assertNotIn('fake-only-test-token', json.dumps(result))

    def test_waiting_qr_can_be_refreshed(self):
        self.replies({'isLogin': False, 'loginPhase': 'waiting_qrcode'}, {'qrcodeurl': 'fake-new-url'},
                     {'isLogin': False, 'loginPhase': 'waiting_qrcode'}, {'qrcode': 'fake-new-url'})
        result = helper.inspect_login(refresh=True)
        self.assertTrue(result['qr_refreshed'])
        self.assertTrue(result['needs_user_scan'])

    def test_online_does_not_refresh_or_request_qr(self):
        self.replies({'isLogin': True, 'loginPhase': 'online'})
        result = helper.inspect_login(refresh=True)
        self.assertTrue(result['qq_online'])
        self.assertFalse(result['qr_refreshed'])
        self.assertEqual(self.session.post.call_count, 2)

    def test_scanned_qr_does_not_interrupt_login(self):
        self.replies({'isLogin': False, 'loginPhase': 'initializing', 'qrLoginAccepted': True})
        result = helper.inspect_login(refresh=True)
        self.assertTrue(result['scan_accepted'])
        self.assertFalse(result['qr_refreshed'])
        self.assertEqual(self.session.post.call_count, 2)

    def test_auth_failure_closed(self):
        self.session.post.return_value = response({}, code=-1)
        with self.assertRaisesRegex(RuntimeError, 'authentication failed'):
            helper.inspect_login()
        self.session.close.assert_called_once()

    def test_refuse_remote_host(self):
        config = self.root / 'napcat/config/webui.json'
        config.write_text(json.dumps({'host': '0.0.0.0', 'port': 6099, 'token': 'fake'}))
        with self.assertRaisesRegex(RuntimeError, 'Unexpected WebUI'):
            helper.inspect_login()
        self.session.post.assert_not_called()

    def test_generating_qr_does_not_trigger_second_generation(self):
        self.replies({'isLogin': False, 'loginPhase': 'generating_qrcode'}, {'qrcode': 'fake-qr-url'})
        self.assertFalse(helper.inspect_login(refresh=True)['qr_refreshed'])
        self.assertFalse(any('RefreshQRcode' in c.args[0] for c in self.session.post.call_args_list))


if __name__ == '__main__':
    unittest.main()
