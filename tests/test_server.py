"""Process-level checks for the shared local HTTP boundary."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
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
        cls.preferences_directory=tempfile.TemporaryDirectory(prefix='cimc-server-preferences-')
        cls.process = subprocess.Popen(
            [sys.executable, str(ROOT/'engine/server.py'), '--port', str(cls.port), '--web-root', str(ROOT/'web')],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            env={**os.environ,'CIMC_CONFIG_DIRECTORY':cls.preferences_directory.name})
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
        cls.preferences_directory.cleanup()

    def test_preferences_round_trip_and_state_visibility(self):
        request=Request(self.url+'/api/preferences',data=b'{"themeColor":"green"}',
                        headers={'Content-Type':'application/json','Origin':self.url})
        with urlopen(request,timeout=2) as response:
            self.assertEqual(json.load(response),{'themeColor':'green'})
        with urlopen(self.url+'/api/state',timeout=2) as response:
            self.assertEqual(json.load(response)['preferences'],{'themeColor':'green'})
        saved=Path(self.preferences_directory.name)/'preferences.json'
        self.assertEqual(json.loads(saved.read_text(encoding='utf-8')),{'themeColor':'green'})

    def test_preferences_require_same_origin_json_and_reject_invalid_color(self):
        for origin,content_type,value,code in (
                (None,'application/json','blue',403),
                ('https://example.invalid','application/json','blue',403),
                (self.url,'text/plain','blue',403),
                (self.url,'application/json','unknown',400)):
            headers={'Content-Type':content_type}
            if origin:headers['Origin']=origin
            request=Request(self.url+'/api/preferences',data=json.dumps({'themeColor':value}).encode(),headers=headers)
            with self.assertRaises(HTTPError) as result:urlopen(request,timeout=2)
            self.assertEqual(result.exception.code,code)

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

    def test_portable_firmware_set_has_transport_headroom(self):
        # The compact firmwareSet can occupy 8 MiB; project JSON needs room for
        # its outer fields. A valid large JSON body must reach command validation.
        body = b'{"action":"not_an_action"}' + b' ' * (8 * 1024 * 1024)
        request = Request(self.url+'/api/command', data=body,
                          headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as result:
            urlopen(request, timeout=10)
        self.assertEqual(result.exception.code, 400)
        self.assertIn('error', json.load(result.exception))

    def test_oversized_body_is_rejected_before_reading(self):
        request = Request(self.url+'/api/command', data=b'', headers={
            'Content-Type': 'application/json', 'Content-Length': str(16 * 1024 * 1024 + 1)})
        with self.assertRaises(HTTPError) as result:
            urlopen(request, timeout=2)
        self.assertEqual(result.exception.code, 413)


if __name__ == '__main__':
    unittest.main()
