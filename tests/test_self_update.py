"""Offline download integrity, concurrency and installer-exit handshake regressions."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from self_update import SelfUpdater, _AssetRedirect, MAX_INSTALLER_BYTES

PAYLOAD = b'MZ' + b'test installation bytes' * 17
NAME = 'CIMC-Studio-9.0.0-Setup-x64.exe'
PREFIX = 'https://github.com/Epiphany-Lucky/cimc-simulator/releases/download/v9.0.0/'


def metadata(*, digest=True):
    return {'status': 'ok', 'available': True, 'latestVersion': '9.0.0',
            'assetDetails': {'windowsInstaller': {'name': NAME, 'url': PREFIX + NAME,
                'size': len(PAYLOAD), 'sha256': hashlib.sha256(PAYLOAD).hexdigest() if digest else None}},
            'checksumsUrl': PREFIX + 'SHA256SUMS-9.0.0.txt'}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cimc-update-test-')
        self.directory = Path(self.temporary.name)
        self.checker = Mock()
        self.checker.check.return_value = metadata()
        self.launcher = Mock()
        self.opener = Mock(return_value=io.BytesIO(PAYLOAD))
        self.updater = SelfUpdater(self.checker, self.directory, opener=self.opener,
                                  cache_root=self.directory/'cache', platform='win32', launcher=self.launcher)

    def tearDown(self):
        if self.updater.thread:
            self.updater.thread.join(timeout=5)
            self.assertFalse(self.updater.thread.is_alive())
        self.temporary.cleanup()

    def finish(self):
        self.updater.start('9.0.0')
        self.updater.thread.join(timeout=5)
        self.assertFalse(self.updater.thread.is_alive())
        return self.updater.state()

    def test_download_progress_digest_and_private_complete_file(self):
        state = self.finish()
        self.assertEqual(state['status'], 'ready', state)
        self.assertEqual(state['receivedBytes'], len(PAYLOAD))
        self.assertEqual(state['totalBytes'], len(PAYLOAD))
        self.assertEqual(state['percent'], 100)
        self.assertEqual(Path(state['filePath']).read_bytes(), PAYLOAD)
        self.assertFalse(list(self.directory.rglob('*.part')))
        if sys.platform != 'win32':
            self.assertEqual(Path(state['filePath']).stat().st_mode & 0o777, 0o600)
        state['status'] = 'corrupted'
        self.assertEqual(self.updater.state()['status'], 'ready')

    def test_release_checksum_fallback(self):
        self.checker.check.return_value = metadata(digest=False)
        checksum = f'{hashlib.sha256(PAYLOAD).hexdigest()}  {NAME}\n'.encode('ascii')
        self.opener.side_effect = [io.BytesIO(checksum), io.BytesIO(PAYLOAD)]
        self.assertEqual(self.finish()['status'], 'ready')
        self.assertEqual(self.opener.call_count, 2)

    def test_bad_or_duplicate_manifest_is_rejected(self):
        self.checker.check.return_value = metadata(digest=False)
        row = f'{hashlib.sha256(PAYLOAD).hexdigest()}  {NAME}\n'.encode('ascii')
        for content in (b'broken', row + row, b'a' * (64 * 1024 + 1)):
            with self.subTest(content=content[:10]):
                self.opener.side_effect = None
                self.opener.return_value = io.BytesIO(content)
                self.assertEqual(self.finish()['status'], 'error')
                self.assertIsNone(self.updater.state()['filePath'])

    def test_corrupt_truncated_oversized_and_offline_downloads_are_removed(self):
        for value in (PAYLOAD[:-1], PAYLOAD + b'!', b'?' * len(PAYLOAD), URLError('offline')):
            with self.subTest(value=str(value)[:30]):
                self.opener.side_effect = value if isinstance(value, Exception) else None
                if isinstance(value, bytes):
                    self.opener.return_value = io.BytesIO(value)
                state = self.finish()
                self.assertEqual(state['status'], 'error', state)
                self.assertIsNone(state['filePath'])
                self.assertFalse(list(self.directory.rglob('*.part')))
                self.assertFalse(list(self.directory.rglob(NAME)))
                self.launcher.assert_not_called()
        self.opener.side_effect = None
        self.opener.return_value = io.BytesIO(PAYLOAD)
        self.assertEqual(self.finish()['status'], 'ready')

    def test_unpublished_changed_missing_checksum_and_oversized_are_rejected(self):
        base = metadata()
        cases = [dict(base, available=False), dict(base, latestVersion='9.0.1'),
                 dict(base, assetDetails={}), dict(base, status='error')]
        too_large = deepcopy(base)
        too_large['assetDetails']['windowsInstaller']['size'] = MAX_INSTALLER_BYTES + 1
        cases.append(too_large)
        missing = metadata(digest=False)
        missing['checksumsUrl'] = None
        cases.append(missing)
        for result in cases:
            self.checker.check.return_value = result
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.updater.start('9.0.0')
        self.opener.assert_not_called()

    def test_concurrent_requests_share_one_download_and_install_handoff(self):
        started, release = threading.Event(), threading.Event()
        def blocked_open(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(5))
            return io.BytesIO(PAYLOAD)
        self.opener.side_effect = blocked_open
        self.updater.start('9.0.0')
        self.assertTrue(started.wait(5))
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.updater.start('9.0.0'))) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertTrue(all(result['status'] == 'downloading' for result in results))
        release.set()
        self.updater.thread.join(5)
        self.assertEqual(self.opener.call_count, 1)
        self.assertEqual(self.updater.install()['status'], 'installing')
        self.assertEqual(self.updater.install()['status'], 'installing')
        self.assertEqual(self.launcher.call_count, 1)

    def test_install_rechecks_digest_and_never_launches_tampered_file(self):
        state = self.finish()
        Path(state['filePath']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.updater.install()
        self.assertEqual(self.updater.state()['errorCode'], 'checksum_mismatch')
        self.launcher.assert_not_called()

    def test_installer_waits_for_owned_processes_and_retains_custom_install_directory(self):
        self.finish()
        self.updater.destination = self.directory / 'CIMC Studio 中文'
        with patch.dict(os.environ, {'CIMC_DESKTOP_PID': '12345'}):
            state = self.updater.install()
        self.assertTrue(state['willExit'])
        command, options = self.launcher.call_args
        arguments = command[0]
        self.assertIn(str(self.updater.destination), arguments)
        self.assertEqual(arguments[-2:], ['-DesktopProcessId', '12345'])
        self.assertNotIn('shell', options)
        helper = Path(arguments[arguments.index('-File') + 1]).read_text(encoding='utf-8-sig')
        self.assertLess(helper.index('WaitForExit'), helper.index('Start-Process'))
        self.assertLess(helper.index('ComputeHash'), helper.index('Start-Process'))
        self.assertIn('/VERYSILENT', helper)
        self.assertIn('Installer exit code', helper)

    def test_spawn_failure_preserves_ready_state_for_retry(self):
        self.finish()
        self.launcher.side_effect = OSError('cannot launch')
        with self.assertRaises(OSError):
            self.updater.install()
        self.assertEqual(self.updater.state()['status'], 'ready')
        self.assertFalse(self.updater.state()['willExit'])

    def test_installer_requests_fresh_frozen_environment_without_mutating_parent(self):
        self.finish()
        inherited = {'_PYI_ARCHIVE_FILE': r'C:\CIMC Studio\CIMC-Engine.exe',
                     '_PYI_APPLICATION_HOME_DIR': r'C:\Temp\_MEI_old_removed',
                     '_PYI_PARENT_PROCESS_LEVEL': '1', 'PYINSTALLER_RESET_ENVIRONMENT': '0'}
        with patch.dict(os.environ, inherited):
            self.updater.install()
            environment = self.launcher.call_args.kwargs['env']
            self.assertEqual(environment['PYINSTALLER_RESET_ENVIRONMENT'], '1')
            for name, value in inherited.items():
                self.assertEqual(os.environ[name], value)
                if name.startswith('_PYI_'):
                    self.assertEqual(environment[name], value)

    def test_missing_verified_file_allows_redownload(self):
        state = self.finish()
        Path(state['filePath']).unlink()
        with self.assertRaises(ValueError):
            self.updater.install()
        self.assertEqual(self.updater.state()['errorCode'], 'installer_missing')
        self.opener.return_value = io.BytesIO(PAYLOAD)
        self.assertEqual(self.finish()['status'], 'ready')

    def test_linux_portable_and_system_installer_capabilities(self):
        portable = SelfUpdater(self.checker, self.directory, platform='linux')
        self.assertEqual(portable.mode, 'linuxPortable')
        self.assertFalse(portable.can_install)
        with patch('self_update.shutil.which', side_effect=lambda name: '/usr/bin/' + name):
            system = SelfUpdater(self.checker, '/opt/cimc-studio', platform='linux')
        self.assertEqual(system.mode, 'linuxDeb')
        self.assertTrue(system.can_install)
        with self.assertRaises(ValueError):
            portable.install()

    def test_update_token_and_redirect_boundaries(self):
        self.assertTrue(self.updater.authorized(self.updater.token))
        for token in (None, {}, '', self.updater.token + 'x'):
            self.assertFalse(self.updater.authorized(token))
        handler = _AssetRedirect()
        request = Request(PREFIX + NAME)
        for target in ('http://release-assets.githubusercontent.com/a', 'https://attacker.invalid/a',
                       'https://github.com@attacker.invalid/a', 'https://github.com:443/a'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, '', {}, target)


class UpdateHttpTests(unittest.TestCase):
    def test_same_origin_token_boundary_and_installer_shutdown(self):
        import server
        updater = Mock()
        updater.info = {'token': 'test-token', 'canInstall': True}
        updater.authorized.side_effect = lambda token: token == 'test-token'
        updater.install.return_value = {'status': 'installing', 'willExit': True}
        simulator = Mock()
        with socket.socket() as socket_instance:
            socket_instance.bind(('127.0.0.1', 0))
            port = socket_instance.getsockname()[1]
        args = SimpleNamespace(root=ROOT, web_root=ROOT/'web', port=port, open_browser=False)
        url = f'http://127.0.0.1:{port}'
        with patch.object(server, 'SelfUpdater', return_value=updater), patch.object(server, 'Simulator', return_value=simulator):
            thread = threading.Thread(target=server.serve, args=(args, None), daemon=True)
            thread.start()
            for _ in range(100):
                try:
                    with urlopen(url+'/api/health', timeout=.2):
                        break
                except URLError:
                    time.sleep(.02)
            for origin, token in ((None, 'test-token'), ('https://foreign.invalid', 'test-token'), (url, 'wrong')):
                headers = {'Content-Type': 'application/json'}
                if origin:
                    headers['Origin'] = origin
                # Origin rejection happens before the body is read. An empty
                # POST avoids racing a refused response against unread TCP data.
                body = json.dumps({'token': token}).encode() if origin == url else b''
                request = Request(url+'/api/updates/install', body, headers)
                with self.subTest(origin=origin, token=token):
                    with self.assertRaises(HTTPError) as result:
                        urlopen(request, timeout=2)
                    self.assertEqual(result.exception.code, 403)
            updater.install.assert_not_called()
            request = Request(url+'/api/updates/install', b'{"token":"test-token"}',
                              {'Content-Type': 'application/json', 'Origin': url})
            with urlopen(request, timeout=2) as response:
                self.assertTrue(json.load(response)['willExit'])
            thread.join(5)
            self.assertFalse(thread.is_alive(), 'Engine did not exit after installer handoff')
            updater.install.assert_called_once()
            simulator.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
