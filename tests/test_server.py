"""Process-level checks for the shared local HTTP boundary."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.url = f'http://127.0.0.1:{cls.port}'
        cls.process = subprocess.Popen(
            [sys.executable, str(ROOT/'engine/server.py'), '--port', str(cls.port), '--web-root', str(ROOT/'web')],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError(cls.process.stderr.read().decode(errors='replace'))
            try:
                with urlopen(cls.url+'/api/health', timeout=1) as r:
                    if r.status == 200:
                        return
            except (URLError, TimeoutError):
                time.sleep(.05)
        cls.process.terminate()
        raise RuntimeError('Local HTTP server did not become ready')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.process.stderr.close()

    def test_browser_app_is_served_with_local_policy(self):
        with urlopen(self.url+'/', timeout=2) as response:
            page = response.read().decode('utf-8')
            self.assertIn('<html', page.lower())
            self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])

    def test_state_contains_real_model_not_running_without_firmware(self):
        with urlopen(self.url+'/api/state', timeout=2) as response:
            state = json.load(response)
        self.assertEqual(state['board']['id'], 'cimc-v1')
        self.assertNotEqual(state['status'], 'running')
        self.assertEqual(state['cpu']['instructions'], 0)

    def test_foreign_origin_cannot_issue_commands(self):
        request = Request(self.url+'/api/command', data=b'{"action":"demo"}',
                          headers={'Content-Type':'application/json', 'Origin':'https://example.invalid'})
        with self.assertRaises(HTTPError) as result:
            urlopen(request, timeout=2)
        self.assertEqual(result.exception.code, 403)

    def test_host_rebinding_is_rejected(self):
        request = Request(self.url+'/api/state', headers={'Host':'attacker.invalid'})
        with self.assertRaises(HTTPError) as result:
            urlopen(request, timeout=2)
        self.assertEqual(result.exception.code, 403)

    def test_path_traversal_does_not_expose_source(self):
        with self.assertRaises(HTTPError) as result:
            urlopen(self.url+'/%2e%2e/engine/simulator.py', timeout=2)
        self.assertEqual(result.exception.code, 404)

    def test_unknown_command_is_actionable_error(self):
        request = Request(self.url+'/api/command', data=b'{"action":"not_an_action"}',
                          headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as result:
            urlopen(request, timeout=2)
        self.assertEqual(result.exception.code, 400)
        self.assertIn('error', json.load(result.exception))


if __name__ == '__main__':
    unittest.main()
