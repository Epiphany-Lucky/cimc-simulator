"""Run the distributed native engine, catching failures invisible in source tests."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request,urlopen

package=Path(sys.argv[1]).resolve()
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
url=f'http://127.0.0.1:{port}'
process=subprocess.Popen([str(package/'CIMC-Engine.exe'),'--port',str(port)],cwd=package,
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
def state():
    with urlopen(url+'/api/state',timeout=3) as r:return json.load(r)
def command(action,**fields):
    with urlopen(Request(url+'/api/command',data=json.dumps({'action':action,**fields}).encode(),headers={'Content-Type':'application/json'}),timeout=5) as r:return json.load(r)
try:
    for _ in range(120):
        if process.poll() is not None:raise RuntimeError('Packaged engine exited during startup: '+process.stderr.read().decode(errors='replace'))
        try:state();break
        except OSError:time.sleep(.25)
    else:raise RuntimeError('Packaged engine startup timeout')
    assert command('demo')['board']['id']=='cimc-v1'
    command('run')
    for _ in range(200):
        s=state()
        assert s['status']!='faulted',s['diagnostics']
        if any('OLED READY' in log['text'] for log in s['serial']):break
        time.sleep(.1)
    else:raise RuntimeError('No OLED startup output from packaged engine')
    assert sum(s['oled']['pixels'])>300
    command('serial',channel='ch340',data='TA==')
    for _ in range(100):
        s=state()
        if any('ACK L' in log['text'] for log in s['serial']):break
        time.sleep(.1)
    else:raise RuntimeError('Packaged engine did not execute UART reply')
    command('pause')
    print('PASS: packaged engine startup + real Keil execution + OLED + serial reply')
finally:
    if process.poll() is None:
        if sys.platform=='win32':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:process.terminate()
    process.wait(timeout=10)
    process.stdout.close();process.stderr.close()
