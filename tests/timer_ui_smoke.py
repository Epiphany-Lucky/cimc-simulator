"""Exercise all timer states through the ordinary browser workbench controls."""
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect
from browser_waits import wait_for_api_state

ROOT=Path(__file__).resolve().parents[1]
URL=(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765').rstrip('/')


def completed(snapshot):
    assert snapshot['status']!='faulted',snapshot['diagnostics']
    stream=b''.join(bytes.fromhex(item['hex']) for item in snapshot['serial']
                    if item['direction']=='tx' and item['channel']=='ch340')
    return b'ALL14 TIMER IRQ OK' in stream and snapshot['leds']==[True,False,True,False,True,True]


with sync_playwright() as playwright:
    browser=playwright.chromium.launch(channel='msedge' if sys.platform=='win32' else None,headless=True)
    context=browser.new_context(viewport={'width':1024,'height':600},accept_downloads=True)
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('dialog',lambda dialog:dialog.accept())
    page.goto(URL)
    expect(page.locator('#timer-demo-button')).to_be_enabled()
    evidence=[]
    for board in ('cimc-v1','cimc-v2'):
        if page.locator('#board-select').input_value()!=board:
            page.locator('#board-select').select_option(board)
            wait_for_api_state(page,URL,lambda state:state['board']['id']==board,description='board selection')
        page.locator('[data-panel="timers"]').click()
        expect(page.locator('#timer-table-body tr')).to_have_count(14)
        page.locator('#timer-demo-button').click()
        expect(page.locator('#firmware-name')).to_contain_text('TIMER0')
        page.locator('#run-button').click()
        snapshot=wait_for_api_state(page,URL,completed,description='all14 actual timer IRQs and LED output')
        assert len(snapshot['timers'])==14
        assert all(timer['clockEnabled'] and timer['updates']>=2 for timer in snapshot['timers'])
        expect(page.locator('.timer-system')).to_have_count(3)
        page.locator('#timer-detail-select').select_option('5')
        expect(page.locator('.timer-basic-note')).to_be_visible()
        page.locator('#timer-detail-select').select_option('0')
        expect(page.locator('.timer-channel')).to_have_count(4)
        expect(page.locator('#clear-button')).not_to_be_visible()
        with page.expect_download() as download:
            page.locator('#export-button').click()
        exported=json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        assert len(exported['timers'])==14 and len(exported['watchdogs'])>=2
        evidence.append({'board':board,'leds':snapshot['leds'],'timerUpdates':[timer['updates'] for timer in snapshot['timers']],
                         'timerExport':True,'instructions':snapshot['cpu']['instructions']})
    for width,height in ((1024,600),(390,844)):
        page.set_viewport_size({'width':width,'height':height})
        page.locator('[data-panel="timers"]').click()
        page.wait_for_function("() => !document.querySelector('#toast').classList.contains('visible')")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        table=page.locator('.timer-table-scroll').bounding_box()
        assert table and table['x']>=0 and table['x']+table['width']<=width+1
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(ROOT/f'artifacts/v06-timers-{width}.png'),full_page=True,animations='disabled')
    assert not errors,errors
    context.close()
    browser.close()
(ROOT/'artifacts/v06-timer-ui-smoke.json').write_text(json.dumps({'passed':True,'boards':evidence,'javascriptErrors':errors,
    'readonlyStatePanel':True,'nativeFirmwareLoadAndRun':True,'responsiveViewports':[1024,390]},indent=2),encoding='utf-8')
print('PASS: TIMER0..13 real firmware, both boards, read-only timer/channel/SysTick/watchdog state, export and responsive UI')
