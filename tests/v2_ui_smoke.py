"""V2 browser acceptance through the actual firmware and workbench controls.

Run with a fresh local server URL. Windows uses Edge, Linux uses Chromium.
Protocol results are decoded from the machine-code-produced RS485 log.
"""
import json
from pathlib import Path
import struct
import sys

from playwright.sync_api import expect, sync_playwright

from browser_waits import wait_for_api_state

ROOT = Path(__file__).resolve().parents[1]
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765').rstrip('/')


def crc16(data):
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def request_frame(command, payload=b''):
    data = bytes((0xA5, 0xB6, 0, 1, 1, command >> 8, command & 255, len(payload), 2)) + payload
    return (data + crc16(data).to_bytes(2, 'big') + b'\xb6\xa5').hex().upper()


def response_data(snapshot, command, after_id):
    text = ''.join(entry['text'] for entry in snapshot['serial']
                   if entry['id'] > after_id and entry['direction'] == 'tx' and entry['channel'] == 'rs485')
    offset = 0
    while (offset := text.find('A5B6', offset)) >= 0:
        tail = text[offset:]
        if len(tail) < 26:
            return None
        try:
            length = 2 * (13 + int(tail[14:16], 16))
            if len(tail) < length:
                return None
            frame = bytes.fromhex(tail[:length])
        except ValueError:
            offset += 4
            continue
        if frame[-2:] == b'\xb6\xa5' and frame[5:7] == command.to_bytes(2, 'big'):
            assert frame[4] == 2, f'Firmware error response: {frame.hex()}'
            assert crc16(frame[:-4]) == int.from_bytes(frame[-4:-2], 'big')
            return frame[9:-4]
        offset += length
    return None


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='msedge' if sys.platform == 'win32' else None, headless=True)
    page = browser.new_page(viewport={'width': 1024, 'height': 600}, accept_downloads=True)
    page.add_init_script("localStorage.setItem('cimc.studio.preferences', JSON.stringify({autoUpdates:false}));")
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('dialog', lambda dialog: dialog.accept())
    page.goto(URL)
    expect(page.locator('#demo-button')).to_be_enabled()

    def state():
        response = page.request.get(URL + '/api/state')
        assert response.ok, response.text()
        return response.json()

    def wait(predicate, description, timeout=30000):
        def check(snapshot):
            assert snapshot['status'] != 'faulted', snapshot['diagnostics']
            return predicate(snapshot)
        return wait_for_api_state(page, URL, check, description=description, timeout_ms=timeout)

    def set_range(selector, value):
        page.locator(selector).evaluate("(input, value) => { input.value = value; input.dispatchEvent(new Event('input', {bubbles:true})); input.dispatchEvent(new Event('change', {bubbles:true})); }", str(value))

    def send(command, payload=b'', use_choice=False):
        anchor = max((entry['id'] for entry in state()['serial']), default=0)
        if use_choice:
            page.locator('#v2-command').select_option(f'{command:04x}')
            page.locator('#v2-send-command').click()
        else:
            page.locator('#serial-format').select_option('ascii')
            page.locator('#serial-newline').uncheck()
            page.locator('#serial-input').fill(request_frame(command, payload))
            page.locator('#serial-send').click()
        snapshot = wait(lambda snapshot: response_data(snapshot, command, anchor) is not None,
                        f'actual V2 firmware response 0x{command:04X}', 60000)
        return response_data(snapshot, command, anchor)

    # Board selection and ready state use the normal UI entry point.
    page.locator('#board-select').select_option('cimc-v2')
    wait(lambda snapshot: snapshot['board']['id'] == 'cimc-v2', 'V2 board selection')
    expect(page.locator('#v2-devices')).to_be_visible()
    expect(page.locator('#schematic-button')).to_be_enabled()
    expect(page.locator('#board-image')).to_have_attribute('src', 'assets/board-v2.svg')
    page.locator('#demo-button').click()
    wait(lambda snapshot: len(snapshot['firmwares']) == 2, 'actual V2 Bootloader and App loaded')
    original_fixed_nets = state()['board']['fixedNets']
    original_wire_count = len(state()['wires'])
    page.locator('[data-panel="wires"]').click()
    page.get_by_role('button', name='删除跳线 H10.1 至 H10.3', exact=True).click()
    wait(lambda snapshot: len(snapshot['wires']) == original_wire_count - 1, 'editable H10 jumper removed')
    assert state()['board']['fixedNets'] == original_fixed_nets
    page.locator('#wiring-example').click()
    wait(lambda snapshot: len(snapshot['wires']) == original_wire_count, 'H10 example jumper restored')
    page.get_by_role('button', name='删除跳线 PC1 至 ADC_IN1', exact=True).click()
    disconnected = wait(lambda snapshot: snapshot['adc']['channelConnections']['11'] is False,
                        'external PC1 example removed')
    assert disconnected['adc']['channelConnections']['10'] is True
    assert disconnected['board']['fixedNets'] == original_fixed_nets
    assert page.locator('#wire-list .fixed-wire-row .icon-button').count() == 0
    page.locator('#wiring-example').click()
    wait(lambda snapshot: snapshot['adc']['channelConnections']['11'] is True,
         'external PC1 example restored')
    page.locator('[data-panel="serial"]').click()
    page.locator('#run-button').click()
    initialized = wait(lambda snapshot: snapshot['currentVectorAddress'] == '0x08011000'
                       and snapshot['analog']['dac']['enabled']
                       and 'A5B6' in ''.join(entry['text'] for entry in snapshot['serial']
                                             if entry['direction'] == 'tx' and entry['channel'] == 'rs485'),
                       'Bootloader jumps to initialized real V2 App', 240000)
    assert initialized['bootAddress'] == '0x08000000'
    expect(page.locator('[data-channel="rs485"]')).to_have_class('active')
    assert send(0x0104, use_choice=True) == b'\x02\x00\x01\x00'

    # Analog controls change model inputs. Firmware commands perform the samples.
    set_range('#adc-slider', .825)
    wait(lambda snapshot: snapshot['adc']['inputVoltages']['10'] == .825, 'PC0 UI input')
    set_range('#adc1-slider', 2.475)
    wait(lambda snapshot: snapshot['adc']['inputVoltages']['11'] == 2.475, 'PC1 UI input')
    for command, expected, channel in ((0x0201, .825, '10'), (0x0202, 2.475, '11')):
        value = struct.unpack('>f', send(command, use_choice=True))[0]
        assert abs(value - expected) < .001, (command, value, expected)
        assert state()['adc']['channelValues'][channel] is not None

    set_range('#pt100-slider', 85)
    wait(lambda snapshot: snapshot['analog']['pt100']['temperature'] == 85, 'PT100 UI input')
    temperature = struct.unpack('>f', send(0x0221, use_choice=True))[0]
    assert abs(temperature - 85) < .05, temperature
    assert state()['analog']['pt100']['sampleCount'] >= 2
    assert send(0x0301, (3072).to_bytes(2, 'big')) == b'\xff'
    wait(lambda snapshot: snapshot['analog']['dac']['value'] == 3072, 'firmware DAC output')
    expect(page.locator('#dac-output')).to_contain_text('3072 / 4095')

    # Two complete restores retain wiring, model inputs and actual Flash writes.
    expected_dac = 3072
    for cycle in range(2):
        page.locator('#run-button').click()
        wait(lambda snapshot: snapshot['status'] == 'paused', 'pause before project export')
        page.locator('[data-panel="wires"]').click()
        with page.expect_download() as download:
            page.locator('#save-project').click()
        project_path = ROOT / f'artifacts/v2-project-restore-{cycle + 1}.json'
        download.value.save_as(project_path)
        saved = json.loads(project_path.read_text(encoding='utf-8'))
        assert saved['boardId'] == 'cimc-v2' and saved['version'] == 3
        assert saved['wires'] and saved['internalFlashData']
        page.locator('#board-select').select_option('cimc-v1')
        wait(lambda snapshot: snapshot['board']['id'] == 'cimc-v1' and not snapshot['firmwares'], 'switch back to V1')
        expect(page.locator('#v2-devices')).to_be_hidden()
        expect(page.locator('#schematic-button')).to_be_enabled()
        page.locator('#project-file').set_input_files(str(project_path))
        restored = wait(lambda snapshot: snapshot['board']['id'] == 'cimc-v2'
                        and len(snapshot['firmwares']) >= 1, 'import V2 project from V1')
        assert restored['adc']['inputVoltages'] == {'10': .825, '11': 2.475}
        assert restored['analog']['pt100']['temperature'] == 85
        assert restored['board']['fixedNets'] == original_fixed_nets
        assert len(restored['wires']) == original_wire_count
        page.locator('#run-button').click()
        wait(lambda snapshot: snapshot['currentVectorAddress'] == '0x08011000'
             and snapshot['analog']['dac']['enabled']
             and snapshot['analog']['dac']['value'] == expected_dac,
             'restored V2 firmware reads saved DAC value from actual Flash', 240000)
        page.locator('[data-panel="serial"]').click()
        assert send(0x0104, use_choice=True) == b'\x02\x00\x01\x00'
        for command, expected in ((0x0201, .825), (0x0202, 2.475), (0x0221, 85)):
            value = struct.unpack('>f', send(command, use_choice=True))[0]
            assert abs(value - expected) < (.05 if command == 0x0221 else .001), (cycle, command, value)
        expected_dac = 2048 if cycle == 0 else 3072
        assert send(0x0301, expected_dac.to_bytes(2, 'big')) == b'\xff'
        wait(lambda snapshot: snapshot['analog']['dac']['value'] == expected_dac,
             'restored firmware writes changed DAC value')

    snapshots = []
    for width, height in ((1024, 600), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        page.evaluate("window.scrollTo({top: 0, left: 0, behavior: 'instant'})")
        page.wait_for_timeout(100)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        for selector in ('#v2-devices', '#v2-protocol', '#serial-form'):
            box = page.locator(selector).bounding_box()
            assert box and box['x'] >= -1 and box['x'] + box['width'] <= width + 1, (selector, box)
        filename = ROOT / f'artifacts/v2-{width}x{height}.png'
        page.screenshot(path=str(filename), full_page=True, animations='disabled')
        snapshots.append(str(filename))
    assert not errors, errors
    (ROOT / 'artifacts/v2-ui-verification.json').write_text(json.dumps({
        'passed': True, 'versionResponse': [2, 0, 1, 0], 'pc0': .825, 'pc1': 2.475,
        'pt100': temperature, 'dac': 3072, 'projectRestored': True, 'restoreCycles': 2,
        'editableH10Jumper': True, 'editablePC1Input': True, 'fixedPC0VR1': True,
        'boardAsset': 'assets/board-v2.svg', 'fixedNetCount': len(original_fixed_nets),
        'screenshots': snapshots, 'javascriptErrors': errors,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    browser.close()
print('PASS: real V2 Boot/App, CRC-checked firmware protocol, PC0/PC1/PT100/DAC, project restore, V1/V2 switching and laptop/mobile layout')
