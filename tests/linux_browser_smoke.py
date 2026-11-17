"""Run the installed Linux application through Chromium, including UI shutdown."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
package=Path(sys.argv[1] if len(sys.argv)>1 else '/opt/cimc-studio').resolve()
if sys.platform!='linux':raise SystemExit('Linux acceptance requires Linux')
with tempfile.TemporaryDirectory(prefix='cimc-browser-') as directory:
    runtime=Path(directory);runtime.chmod(0o700)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    environment={**os.environ,'XDG_RUNTIME_DIR':str(runtime),'CIMC_CONFIG_DIRECTORY':str(runtime/'preferences')}
    log=(ROOT/'artifacts/linux-browser-engine.log');log.parent.mkdir(exist_ok=True)
    with log.open('w',encoding='utf-8') as output:
        process=subprocess.Popen([str(package/'CIMC-Engine'),'--desktop','--no-open-browser',
                                  '--port',str(port),'--session-idle-seconds','180'],cwd=package,
                                 env=environment,stdout=output,stderr=subprocess.STDOUT)
        try:
            for _ in range(120):
                if process.poll() is not None:raise RuntimeError('Linux desktop session exited: '+log.read_text())
                try:
                    with urlopen(url+'/api/state',timeout=1) as r:state=json.load(r)
                    assert state['engine']['desktopSession'] is True
                    break
                except OSError:time.sleep(.25)
            else:raise RuntimeError('Linux desktop session startup timeout')
            for script in ('ui_smoke.py','key_ui_smoke.py','laptop_smoke.py','schematic_smoke.py','multifirmware_ui_smoke.py','update_ui_smoke.py','self_update_ui_smoke.py','v2_schematic_smoke.py','v2_ui_smoke.py','timer_ui_smoke.py','theme_ui_smoke.py'):
                subprocess.run([sys.executable,str(ROOT/'tests'/script),url],cwd=ROOT,check=True)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True)
                page=browser.new_page(viewport={'width':390,'height':844})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url)
                expect(page.locator('#exit-app-button')).to_be_visible()
                expect(page.locator('#exit-app-button')).to_be_enabled()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                page.locator('#exit-app-button').click()
                expect(page.locator('#connection-status')).to_have_text('应用已退出')
                expect(page.locator('#run-button')).to_be_disabled()
                expect(page.locator('#exit-app-button')).not_to_be_visible()
                page.screenshot(path=str(ROOT/'artifacts/linux-session-exited.png'),full_page=True)
                process.wait(timeout=10)
                assert process.returncode==0,log.read_text()
                assert not errors,errors
                browser.close()
            print('PASS: installed Linux Chromium workbench + laptop/OLED/ADC/SPI/schematic/multifirmware + UI-owned shutdown')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
