import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from service_instance import ServiceLease,health_listener


class ServiceLeaseTests(unittest.TestCase):
    def test_second_process_rejected_and_lock_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'service.lock'
            code='from service_instance import ServiceLease,ServiceAlreadyRunning; import sys\ntry:\n with ServiceLease(sys.argv[1]): print("acquired")\nexcept ServiceAlreadyRunning: sys.exit(3)'
            with ServiceLease(path):
                blocked=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=5)
                self.assertEqual(blocked.returncode,3)
            ok=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=5)
            self.assertEqual(ok.returncode,0)

    def test_main_takes_lease_before_bot_constructor(self):
        import inspect,app
        source=inspect.getsource(app.main)
        self.assertIn("with ServiceLease(ROOT/'state/service.lock'):",source)
        self.assertIn("with health_listener(cfg['health_port']) as listener:Bot().serve(listener)",source)

    def test_existing_legacy_listener_prevents_new_store_start(self):
        entered=False
        with health_listener(0) as first:
            with self.assertRaises(OSError):
                with health_listener(first.getsockname()[1]):entered=True
        self.assertFalse(entered)


from test_bot import Fixture
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor
import socket
import json


class HealthHandoffTests(Fixture):
    def test_prebound_health_socket_serves_without_starting_real_workers(self):
        for name in ('worker','events','housekeeping','model_probes','social_worker'):
            setattr(self.bot,name,Mock())
        received=[]
        def serve_once(server):
            def client():
                with socket.create_connection(server.server_address,timeout=3) as connection:
                    connection.sendall(b'GET /healthz HTTP/1.0\r\nHost: localhost\r\n\r\n')
                    parts=[]
                    while True:
                        data=connection.recv(4096)
                        if not data:break
                        parts.append(data)
                    return b''.join(parts)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(client);server.handle_request();received.append(future.result(3))
        with health_listener(0) as listener,patch('app.ThreadingHTTPServer.serve_forever',new=serve_once):
            self.bot.serve(listener)
        self.assertIn(b'200 OK',received[0])
        body=json.loads(received[0].split(b'\r\n\r\n',1)[1])
        self.assertEqual(body['service'],'qqbot-service')
        self.bot.llm.chat.assert_not_called();self.bot.ob.send.assert_not_called()
