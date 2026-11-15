"""Linux desktop ownership, shutdown boundary and idle lifetime acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from desktop_session import DesktopSession, browser_environment


class BrowserEnvironmentTests(unittest.TestCase):
    def test_system_opener_does_not_inherit_frozen_library_path(self):
        source={'LD_LIBRARY_PATH':'/private/bundle','LD_LIBRARY_PATH_ORIG':'/user/libs','PATH':'/usr/bin'}
        clean=browser_environment(source)
        self.assertEqual(clean['LD_LIBRARY_PATH'],'/user/libs')
        self.assertNotIn('LD_LIBRARY_PATH_ORIG',clean)
        self.assertEqual(source['LD_LIBRARY_PATH'],'/private/bundle')
        self.assertNotIn('LD_LIBRARY_PATH',browser_environment({'LD_LIBRARY_PATH':'/private/bundle'}))


@unittest.skipUnless(sys.platform.startswith('linux'),'Linux flock/session permissions')
class DesktopOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='cimc-session-test-')
        self.directory=Path(self.temporary.name)
        self.sessions=[]

    def make(self,**kwargs):
        s=DesktopSession(self.directory,**kwargs);self.sessions.append(s);return s

    def tearDown(self):
        for s in self.sessions:s.close()
        self.temporary.cleanup()

    def test_only_one_owner_and_lock_inode_survives_cleanup(self):
        first=self.make();second=self.make()
        self.assertTrue(first.acquire());self.assertFalse(second.acquire())
        inode=(self.directory/'session.lock').stat().st_ino
        first.publish('http://127.0.0.1:12345/')
        self.assertEqual(stat.S_IMODE(first.record_path.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode),0o700)
        first.close()
        self.assertFalse(first.record_path.exists())
        self.assertEqual((self.directory/'session.lock').stat().st_ino,inode)
        self.assertTrue(second.acquire())

    def test_non_owner_cannot_publish_or_remove_record(self):
        first=self.make();second=self.make();first.acquire();first.publish('http://127.0.0.1:12345/')
        self.assertFalse(second.acquire())
        with self.assertRaises(RuntimeError):second.publish('http://127.0.0.1:12346/')
        second.close()
        self.assertEqual(json.loads(first.record_path.read_text())['instanceId'],first.instance_id)

    def test_stale_record_is_replaced_after_lock_owner_exits(self):
        s=self.make();s.acquire()
        s.record_path.write_text(json.dumps({'url':'http://127.0.0.1:1/','instanceId':'stale'*8}))
        s.publish('http://127.0.0.1:12345/')
        self.assertEqual(s._read_record()['instanceId'],s.instance_id)
        self.assertTrue(s.authorized(s.instance_id))
        for invalid in (None,0,[],s.instance_id+'x'):
            self.assertFalse(s.authorized(invalid))

    def test_unsafe_directory_and_symlink_lock_are_rejected(self):
        unsafe=self.directory/'public';unsafe.mkdir(mode=0o755)
        with self.assertRaises(RuntimeError):DesktopSession(unsafe)
        target=self.directory/'elsewhere';target.write_text('unrelated')
        (self.directory/'session.lock').symlink_to(target)
        with self.assertRaises(OSError):self.make().acquire()
        self.assertEqual(target.read_text(),'unrelated')

    def test_activity_renews_idle_deadline(self):
        s=self.make(idle_seconds=2)
        with patch('desktop_session.time.monotonic',return_value=100):s.touch()
        with patch('desktop_session.time.monotonic',return_value=101.9):self.assertFalse(s.expired())
        with patch('desktop_session.time.monotonic',return_value=102):self.assertTrue(s.expired())
        with patch('desktop_session.time.monotonic',return_value=103):s.touch()
        with patch('desktop_session.time.monotonic',return_value=104):self.assertFalse(s.expired())


@unittest.skipUnless(sys.platform.startswith('linux') and importlib.util.find_spec('unicorn'),
                     'Linux server integration requires Unicorn')
class DesktopServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cimc-desktop-http-')
        self.directory=Path(self.temp.name)
        self.env={**os.environ,'XDG_RUNTIME_DIR':str(self.directory)}
        self.processes=[];self.url=None;self.instance=None

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            process.stdout.close();process.stderr.close()
        self.temp.cleanup()

    def spawn(self,idle=20):
        p=subprocess.Popen([sys.executable,str(ROOT/'engine/server.py'),'--desktop','--no-open-browser',
                            '--port','0','--session-idle-seconds',str(idle)],cwd=ROOT,env=self.env,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.processes.append(p);return p

    def ready(self,p):
        end=time.monotonic()+10
        while time.monotonic()<end:
            if p.poll() is not None:self.fail(p.stderr.read())
            try:
                record=json.loads((self.directory/'cimc-studio/session.json').read_text())
                self.url=record['url'].rstrip('/');self.instance=record['instanceId']
                with urlopen(self.url+'/api/health',timeout=1) as r:
                    if json.load(r)['instanceId']==self.instance:return
            except (OSError,ValueError):pass
            time.sleep(.05)
        self.fail('Managed server startup timed out')

    def quit_request(self,instance,origin=True):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=self.url if origin is True else origin
        return Request(self.url+'/api/session/quit',json.dumps({'instanceId':instance}).encode(),headers)

    def test_duplicate_launch_reuses_instance_and_command_state(self):
        p=self.spawn();self.ready(p)
        duplicate=self.spawn();duplicate.wait(timeout=10)
        self.assertEqual(duplicate.returncode,0,duplicate.stderr.read())
        self.assertIn(self.url,duplicate.stdout.read())
        self.assertIsNone(p.poll())
        with urlopen(Request(self.url+'/api/command',b'{"action":"demo"}',{'Content-Type':'application/json'})) as r:
            state=json.load(r)
        self.assertTrue(state['engine']['desktopSession'])
        self.assertEqual(state['engine']['instanceId'],self.instance)

    def test_exit_requires_origin_and_correct_instance(self):
        p=self.spawn();self.ready(p)
        for token,origin in [(None,True),('wrong',True),(self.instance,False),(self.instance,'https://foreign.invalid')]:
            with self.assertRaises(HTTPError) as error:urlopen(self.quit_request(token,origin))
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            self.assertIsNone(p.poll())
        with urlopen(self.quit_request(self.instance)) as r:self.assertTrue(json.load(r)['ok'])
        p.wait(timeout=5);self.assertEqual(p.returncode,0)
        self.assertFalse((self.directory/'cimc-studio/session.json').exists())

    def test_no_client_exits_but_health_probes_do_not_extend_lifetime(self):
        p=self.spawn(idle=1);self.ready(p)
        started=time.monotonic()
        while p.poll() is None:
            try:
                with urlopen(self.url+'/api/health',timeout=.2):pass
            except OSError:pass
            time.sleep(.1)
            if time.monotonic()-started>4:self.fail('Idle service did not exit')
        self.assertEqual(p.returncode,0)

    def test_normal_service_does_not_expose_exit_control(self):
        p=subprocess.Popen([sys.executable,str(ROOT/'engine/server.py'),'--port','0'],cwd=ROOT,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.processes.append(p)
        self.url=p.stdout.readline().strip().split()[-1].rstrip('/')
        with urlopen(self.url+'/api/state') as r:state=json.load(r)
        self.assertFalse(state['engine']['desktopSession'])
        with self.assertRaises(HTTPError) as error:urlopen(self.quit_request('unused'))
        self.assertEqual(error.exception.code,404)
        error.exception.close()


if __name__=='__main__':unittest.main()
