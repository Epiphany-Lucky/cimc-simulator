"""Interactive browser acceptance. Run with a fresh local server, not in unittest discovery."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765'
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge' if sys.platform=='win32' else None,headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url)
    expect(page.locator('#demo-button')).to_be_enabled()
    expect(page.locator('.pin')).to_have_count(109)
    page.locator('#demo-button').click()
    expect(page.locator('#wire-count')).to_have_text('12')
    page.locator('#run-button').click()
    expect(page.locator('#terminal')).to_contain_text('OLED READY',timeout=30000)
    page.wait_for_function("document.querySelector('#oled-live').classList.contains('on')")
    # Press and hold a real UI key until firmware updates GPIO.
    key=page.locator('#keys button').nth(1)
    key.dispatch_event('pointerdown',{'pointerId':1})
    expect(page.locator('#leds .led-light').nth(1)).to_have_class('led-light on',timeout=15000)
    key.dispatch_event('pointerup',{'pointerId':1})
    page.locator('#serial-newline').uncheck()
    page.locator('#serial-input').fill('L')
    page.locator('#serial-send').click()
    expect(page.locator('#terminal')).to_contain_text('ACK L',timeout=15000)
    page.locator('#run-button').click()
    expect(page.locator('#connection-status')).to_contain_text('已暂停')
    # Project v3 restores firmware and user jumpers. Remove a wire via actual UI.
    page.locator('[data-panel="wires"]').click()
    with page.expect_download() as event:page.locator('#save-project').click()
    saved=ROOT/'artifacts/ui-wiring.json';event.value.save_as(saved)
    project=json.loads(saved.read_text())
    assert project['boardId']=='cimc-v1' and len(project['wires'])==12 and project['version']==3
    page.locator('#wire-list .icon-button').first.click()
    expect(page.locator('#wire-count')).to_have_text('11')
    page.locator('#project-file').set_input_files(str(saved))
    expect(page.locator('#wire-count')).to_have_text('12')
    # Add by clicking two exposed pins, then delete just that added wire.
    page.locator('[data-pin="PD0"]').click()
    page.locator('[data-pin="PD1"]').click()
    expect(page.locator('#wire-count')).to_have_text('13')
    page.locator('#wire-list .icon-button').last.click()
    expect(page.locator('#wire-count')).to_have_text('12')
    # Exercise actual BIN file input and firmware reset.
    page.locator('#firmware-file').set_input_files(str(ROOT/'firmware/demo.bin'))
    page.locator('#import-confirm').click()
    expect(page.locator('#firmware-name')).to_have_text('demo.bin')
    page.locator('#step-button').click()
    page.locator('#reset-button').click()
    expect(page.locator('#cpu-instructions')).to_have_text('0')
    page.locator('[data-panel="serial"]').click()
    page.locator('#run-button').click()
    expect(page.locator('#terminal')).to_contain_text('OLED READY',timeout=30000)
    page.locator('#settings-button').click()
    page.locator('#setting-motion').check()
    page.locator('#settings-dialog [data-close]').last.click()
    expect(page.locator('body')).to_have_class('reduce-motion')
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(ROOT/'artifacts/ui-v1-running.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    page.screenshot(path=str(ROOT/'artifacts/ui-v1-mobile.png'),full_page=True)
    assert not errors,errors
    print('PASS: Edge UI demo, KEY/LED, OLED, serial, manual wire, project roundtrip, BIN import/reset, reduced motion, 390px layout. No JS exceptions.')
    browser.close()
