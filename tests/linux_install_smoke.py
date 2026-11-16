"""Run after apt installs the DEB: python tests/linux_install_smoke.py /opt/cimc-studio.

Uses only the supplied frozen executable, temporary user state and owned processes.
No test changes the user's browser settings, installed files or real session files.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path,nargs='?',default=Path('/opt/cimc-studio'))
    parser.add_argument('--portable',action='store_true',help='Check a tar bundle without system menu entries')
    args=parser.parse_args()
    if not sys.platform.startswith('linux'):parser.error('Run this acceptance test on Linux')
    package=args.package.resolve()
    executable=package/'CIMC-Engine'
    assert executable.is_file() and os.access(executable,os.X_OK),executable
    for relative in ('web/index.html','web/board-v1.json','web/assets/schematics/GD32F470-V1.0-schematic.pdf',
                     'web/assets/schematics/v1-page-4.png','firmware/demo.hex','firmware/adc_probe.hex',
                     'firmware/spiflash_probe.bin','THIRD_PARTY_NOTICES.md','source/engine/server.py'):
        assert (package/relative).is_file(),relative
    if args.portable:
        launcher=package/'cimc-studio'
    else:
        launcher=Path('/usr/bin/cimc-studio')
        entry=Path('/usr/share/applications/cimc-studio.desktop').read_text()
        assert 'Exec=/usr/bin/cimc-studio' in entry and 'Terminal=false' in entry
        assert Path('/usr/share/icons/hicolor/scalable/apps/cimc-studio.svg').is_file()
    assert launcher.is_file() and os.access(launcher,os.X_OK)
    before={p.relative_to(package):p.stat().st_mtime_ns for p in package.rglob('*') if p.is_file()}
    processes=[]
    with tempfile.TemporaryDirectory(prefix='cimc-installed-session-') as temporary:
        runtime=Path(temporary);record=runtime/'cimc-studio/session.json'
        env={**os.environ,'XDG_RUNTIME_DIR':str(runtime)}

        def spawn(idle=30,headless=True,command=None,extra_env=None):
            argv=[str(command or launcher),'--session-idle-seconds',str(idle),'--port','0']
            if command:argv.insert(1,'--desktop')
            if headless:argv.append('--no-open-browser')
            p=subprocess.Popen(argv,cwd=temporary,env={**env,**(extra_env or {})},
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            processes.append(p);return p

        def ready(p):
            end=time.monotonic()+15
            while time.monotonic()<end:
                if p.poll() is not None:
                    stdout,stderr=p.communicate()
                    raise RuntimeError(f'Installed launcher exited {p.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}')
                try:
                    info=json.loads(record.read_text());url=info['url'].rstrip('/')
                    with urlopen(url+'/api/health',timeout=1) as r:health=json.load(r)
                    if health['instanceId']==info['instanceId']:
                        assert health['desktopSession'] is True
                        assert stat.S_IMODE(record.stat().st_mode)==0o600
                        assert stat.S_IMODE(record.parent.stat().st_mode)==0o700
                        return url,info['instanceId']
                except (OSError,ValueError):pass
                time.sleep(.1)
            raise RuntimeError('Installed managed session did not start')

        def finish(p,timeout=8,expected=0):
            try:stdout,stderr=p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill();stdout,stderr=p.communicate(timeout=5)
                raise AssertionError(f'Owned process did not exit within {timeout}s\nstdout:\n{stdout}\nstderr:\n{stderr}')
            if expected is not None:
                assert p.returncode==expected,(
                    f'Owned process exited {p.returncode}, expected {expected}\nstdout:\n{stdout}\nstderr:\n{stderr}')
            return stdout,stderr

        def post(url,path,payload,origin=True):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=url if origin is True else origin
            with urlopen(Request(url+path,json.dumps(payload).encode(),headers),timeout=5) as r:return json.load(r)

        try:
            first=spawn();url,instance=ready(first)
            duplicate=spawn();stdout,_=finish(duplicate,timeout=15)
            assert url in stdout,stdout
            assert first.poll() is None
            for token,origin in [('bad',True),(instance,False),(instance,'https://foreign.invalid')]:
                try:post(url,'/api/session/quit',{'instanceId':token},origin)
                except HTTPError as error:
                    assert error.code==403
                    error.close()
                else:raise AssertionError('An unauthorized request stopped the session')
            demo=post(url,'/api/command',{'action':'demo'})
            assert demo['engine']['desktopSession'] and demo['engine']['instanceId']==instance
            post(url,'/api/command',{'action':'run'})
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                with urlopen(url+'/api/state',timeout=3) as r:state=json.load(r)
                assert state['status']!='faulted',state['diagnostics']
                if 'OLED READY' in ''.join(row['text'] for row in state['serial'] if row['direction']=='tx' and row['channel']=='ch340'):break
                time.sleep(.1)
            else:raise AssertionError('Installed frozen engine did not run Keil firmware')
            assert sum(state['oled']['pixels'])>300
            post(url,'/api/session/quit',{'instanceId':instance})
            finish(first)
            assert not record.exists()

            # Health probes do not keep an abandoned desktop process alive.
            idle=spawn(idle=2);idle_url,_=ready(idle)
            finish(idle,timeout=7)
            assert not record.exists()
            try:urlopen(idle_url+'/api/health',timeout=.5)
            except (OSError,URLError):pass
            else:raise AssertionError('Abandoned desktop service is still listening')

            # A crashed owned process releases flock; stale metadata never blocks restart.
            crashed=spawn();_,old_instance=ready(crashed)
            crashed.kill();crashed.wait(timeout=5)
            assert record.exists()
            restarted=spawn();new_url,new_instance=ready(restarted)
            assert new_instance!=old_instance
            post(new_url,'/api/session/quit',{'instanceId':new_instance})
            finish(restarted)

            # Simulate no graphical opener without modifying system packages or settings.
            missing_browser=spawn(headless=False,command=executable,extra_env={'PATH':''})
            stdout,stderr=finish(missing_browser,expected=None)
            assert missing_browser.returncode!=0,f'Missing browser unexpectedly succeeded\nstdout:\n{stdout}\nstderr:\n{stderr}'
            assert 'No desktop URL opener' in stderr,stderr
            assert not record.exists()
        finally:
            for process in processes:
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                process.stdout.close();process.stderr.close()
    after={p.relative_to(package):p.stat().st_mtime_ns for p in package.rglob('*') if p.is_file()}
    assert before==after,'Managed session wrote into the installed program directory'
    print('PASS: installed payload/menu/launcher + frozen Keil execution + single-instance reuse + '
          'authorized exit + idle cleanup + crash recovery + missing-browser cleanup + read-only install tree')


if __name__=='__main__':main()
