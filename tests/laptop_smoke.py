"""V0.2 Edge acceptance against a fresh local server; not unittest discovery.

Run: .venv/Scripts/python.exe tests/laptop_smoke.py http://127.0.0.1:8765
The ADC and SPI assertions use actual ARM firmware and the live local API.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765').rstrip('/')


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 660})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(URL)
    expect(page.locator('#demo-button')).to_be_enabled()

    def state():
        return page.request.get(URL + '/api/state').json()

    def wait_state(expression):
        page.wait_for_function(
            "() => fetch('/api/state').then(r => r.json()).then(s => (" + expression + "))",
            timeout=30000)

    # A fresh load leaves ADC readings empty until firmware requests conversion.
    page.locator('#demo-button').click()
    expect(page.locator('#wire-count')).to_have_text('12')
    expect(page.locator('#adc-slider')).to_be_enabled()
    expect(page.locator('#adc-sample')).to_have_text('待固件采样')
    assert state()['adc']['sampleCount'] == 0 and state()['adc']['value'] is None
    flash_baseline = state()['flash']

    for pin in ('PC0', 'PB12', 'PB13', 'PB14', 'PB15', 'H6.1', 'H7.1'):
        expect(page.locator(f'[data-pin="{pin}"]')).to_be_disabled()
    expect(page.locator('[data-pin="PD10"]')).to_be_enabled()
    assert '固定' in page.locator('[data-pin="PC0"]').get_attribute('title')

    # OLED power/I2C routes are visible original board nets, never user jumpers.
    oled_pairs = {('OLED.1', 'U2.33'), ('OLED.2', 'U2.34'), ('OLED.3', 'PB8'), ('OLED.4', 'PB9')}
    paths = page.locator('#wire-layer .fixed-board-wire')
    expect(paths).to_have_count(4)
    actual_pairs = set()
    for path in paths.all():
        expect(path).to_be_visible()
        actual_pairs.add((path.get_attribute('data-from'), path.get_attribute('data-to')))
        assert path.evaluate("e => getComputedStyle(e).pointerEvents") == 'none'
    assert actual_pairs == oled_pairs
    for pair in oled_pairs:
        for pin in pair:
            expect(page.locator(f'[data-pin="{pin}"]')).to_be_disabled()
    page.locator('[data-pin="PD10"]').click()
    expect(page.locator('[data-pin="PD10"]')).to_have_class('pin selected')
    page.keyboard.press('Escape')

    # Both accessible keyboard input and pointer dragging reach the analog model.
    knob = page.locator('#adc-knob')
    knob.focus()
    page.keyboard.press('End')
    wait_state('s.adc.voltage === 3.3')
    expect(page.locator('#adc-voltage')).to_have_text('3.300 V')
    assert state()['adc']['value'] is None
    page.keyboard.press('Home')
    wait_state('s.adc.voltage === 0')
    page.keyboard.press('PageUp')
    wait_state('s.adc.voltage === 0.1')
    bounds = knob.bounding_box()
    x, y = bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 20, y - 15, steps=6)
    page.mouse.up()
    wait_state('s.adc.voltage > 0.1 && s.adc.voltage <= 3.3')

    page.locator('#run-button').click()
    expect(page.locator('#terminal')).to_contain_text('OLED READY', timeout=30000)
    wait_state('s.adc.sampleCount > 0')
    page.wait_for_function("() => document.querySelector('#oled-live').classList.contains('on')")
    expect(page.locator('#flash-command')).to_contain_text('0x9F')
    expect(page.locator('#flash-writes')).to_have_text(f"{flash_baseline['writeCount']:,} 次")

    # The range is a second input to the same real ADC; verify both rails.
    slider = page.locator('#adc-slider')
    slider.focus()
    page.keyboard.press('End')
    wait_state('s.adc.value === 4095')
    expect(page.locator('#adc-sample')).to_have_text('采样 4095 / 4095')
    page.keyboard.press('Home')
    wait_state('s.adc.value === 0')
    expect(page.locator('#adc-sample')).to_have_text('采样 0 / 4095')
    page.keyboard.press('ArrowRight')
    wait_state('s.adc.voltage === 0.001 && s.adc.value === 1')

    # Changing H6 mode changes only managed routes. Terminal tabs remain views.
    before_wires = state()['wires']
    page.locator('#serial-mode').select_option('rs232')
    wait_state("s.serialMode === 'rs232'")
    h6 = {(wire['from'], wire['to']) for wire in state()['managedWires']
          if wire['from'].startswith('H6.')}
    assert h6 == {('H6.3', 'H6.5'), ('H6.4', 'H6.6')}, h6
    assert state()['wires'] == before_wires
    page.locator('[data-channel="rs485"]').click()
    assert state()['serialMode'] == 'rs232'
    page.locator('[data-channel="rs232"]').click()
    page.locator('#serial-newline').uncheck()
    page.locator('#serial-input').fill('A')
    page.locator('#serial-send').click()
    expect(page.locator('#terminal')).to_contain_text('ADC 0001 PC0', timeout=30000)
    page.locator('[data-panel="wires"]').click()
    expect(page.locator('#wire-list .icon-button')).to_have_count(12)
    expect(page.locator('#wire-list .managed-wire-label')).to_have_count(4)
    expect(page.locator('#wire-list .fixed-wire-row')).to_have_count(4)
    expect(page.locator('#wire-list .fixed-wire-row button')).to_have_count(0)
    for label in page.locator('#wire-list .fixed-wire-label').all():
        expect(label).to_contain_text('原板固定线')
    page.locator('[data-panel="serial"]').click()
    page.locator('[data-channel="ch340"]').click()
    page.wait_for_function("() => !document.querySelector('#toast').classList.contains('visible')", timeout=8000)

    # The full board, key bank, ADC dial, OLED and Run control stay above the fold.
    # Device scale factor does not alter CSS dimensions; these are logical sizes
    # including representative 125% DPI laptop work areas.
    layouts = []
    for width, height in ((1536, 740), (1366, 768), (1280, 720),
                          (1280, 660), (1093, 614), (1024, 600)):
        page.set_viewport_size({'width': width, 'height': height})
        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        bottoms = {}
        for selector in ('#run-button', '#keys', '#adc-knob', '#oled-canvas', '#board-card'):
            box = page.locator(selector).bounding_box()
            assert box and box['y'] >= 0 and box['y'] + box['height'] <= height, (width, height, selector, box)
            bottoms[selector] = round(box['y'] + box['height'])
        layouts.append({'width': width, 'height': height, 'bottoms': bottoms})
        if width in (1280, 1024) and height in (660, 600):
            page.screenshot(path=str(ROOT / f'artifacts/laptop-{width}x{height}-v02.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.screenshot(path=str(ROOT / 'artifacts/laptop-390x844-v02.png'), full_page=True)

    # SPI counters must change only after real firmware performs transactions.
    page.set_viewport_size({'width': 1280, 'height': 660})
    page.locator('#run-button').click()
    expect(page.locator('#connection-status')).to_contain_text('已暂停')
    page.locator('#firmware-file').set_input_files(str(ROOT / 'firmware/spiflash_probe.hex'))
    page.locator('#import-confirm').click()
    expect(page.locator('#firmware-name')).to_have_text('spiflash_probe.hex')
    page.locator('#run-button').click()
    writes = flash_baseline['writeCount'] + 2
    erases = flash_baseline['eraseCount'] + 2
    reads = flash_baseline['readCount'] + 5
    wait_state(f's.flash.writeCount === {writes} && s.flash.eraseCount === {erases} && s.flash.readCount === {reads}')
    expect(page.locator('#flash-writes')).to_have_text(f'{writes:,} 次')
    expect(page.locator('#flash-erases')).to_have_text(f'{erases:,} 次')
    expect(page.locator('#flash-reads')).to_have_text(f'{reads:,} B')
    expect(page.locator('#flash-state')).to_have_text('就绪')
    assert bytes(state()['flash']['preview'][:10]) == b'CIMC FLASH'
    page.locator('#run-button').click()

    assert not errors, errors
    print(json.dumps(layouts, ensure_ascii=False))
    print('PASS: six laptop viewports and mobile; real ADC keyboard/pointer/range input and conversions; '
          'four readonly OLED routes; fixed pins; managed H6 routes and RS232 RX/TX; '
          'real SPI read/write/erase UI counters; no JS exceptions.')
    browser.close()
