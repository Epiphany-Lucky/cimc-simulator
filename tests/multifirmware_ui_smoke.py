"""Multi-image workbench acceptance using real Keil binaries and the live API.

Run directly with an optional server URL; Windows uses Edge, Linux Chromium.
No unittest discovery and no mocked simulation output.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_waits import wait_for_terminal_text

ROOT = Path(__file__).resolve().parents[1]
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765').rstrip('/')
(ROOT / 'artifacts').mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge' if sys.platform == 'win32' else None, headless=True)
    page = browser.new_page(viewport={'width': 1024, 'height': 600}, accept_downloads=True)
    errors, uploads = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def capture_upload(request):
        if request.method == 'POST' and request.url.endswith('/api/command'):
            payload = request.post_data_json
            if payload.get('action') == 'load_set':
                uploads.append(payload)

    page.on('request', capture_upload)
    page.goto(URL)
    expect(page.locator('#demo-button')).to_be_enabled()
    # The demo supplies the actual user LED jumpers needed by both applications.
    page.locator('#demo-button').click()
    expect(page.locator('#wire-count')).to_have_text('12')

    def state():
        return page.request.get(URL + '/api/state').json()

    def wait_state(expression):
        # wait_for_function treats a returned Promise as truthy in this runtime;
        # request synchronously and evaluate a plain boolean from the response.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            snapshot = state()
            if page.evaluate('(s) => (' + expression + ')', snapshot):
                return snapshot
            page.wait_for_timeout(100)
        raise AssertionError(f'Timed out waiting for {expression}: {snapshot}')

    def apply():
        page.locator('#firmware-set-apply').click()
        expect(page.locator('#firmware-set-dialog')).not_to_be_visible(timeout=15000)

    def contained():
        width, height = page.viewport_size['width'], page.viewport_size['height']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        dialog = page.locator('#firmware-set-dialog')
        assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
        for selector in ('#firmware-set-dialog', '#firmware-set-add', '#firmware-set-apply'):
            box = page.locator(selector).bounding_box()
            assert box and box['x'] >= 0 and box['y'] >= 0, (selector, box)
            assert box['x'] + box['width'] <= width + 1 and box['y'] + box['height'] <= height + 1, (width, height, selector, box)

    def set_terminal_baud(baud):
        page.locator('#serial-settings-open').click()
        page.locator('#serial-settings-mode').select_option('manual' if baud else 'auto')
        if baud:
            page.locator('#serial-baud-rate').select_option(str(baud))
        page.locator('#serial-settings-apply').click()
        expect(page.locator('#serial-settings-dialog')).not_to_be_visible()

    def run_from_bootloader(number, letter, vector, led_index):
        page.locator('#run-button').click()
        wait_for_terminal_text(page, 'SELECT 1 OR 2')
        page.locator('#serial-newline').uncheck()
        if number == '1':
            set_terminal_baud(9600)
            wait_state("s.serialCompatibility.ch340 === false")
            page.locator('#serial-input').fill('2')
            page.locator('#serial-send').click()
            blocked = wait_state("s.diagnostics.some(entry => entry.code === 'serial-config' && entry.channel === 'ch340')")
            assert blocked['currentVectorAddress'] == '0x08000000'
            set_terminal_baud(115200)
            wait_state("s.serialCompatibility.ch340 === true")
        page.locator('#serial-input').fill(number)
        page.locator('#serial-send').click()
        wait_for_terminal_text(page, f'JUMP APP {letter}')
        wait_for_terminal_text(page, f'APP {letter} READY')
        wait_state(f"s.currentVectorAddress === '{vector}' && s.status === 'running'")
        expect(page.locator('#leds .led-light').nth(led_index)).to_have_class('led-light on')
        # The reset selection remains Bootloader; this VTOR change came from ARM code.
        assert state()['bootAddress'] == '0x08000000'
        if number == '1':
            set_terminal_baud(None)

    opener = page.locator('#firmware-set-open')
    dialog = page.locator('#firmware-set-dialog')
    opener.click()
    page.locator('.firmware-remove').first.click()
    expect(page.locator('.firmware-set-row')).to_have_count(0)
    expect(page.locator('#firmware-set-apply')).to_be_disabled()
    page.locator('#firmware-set-files').set_input_files([
        str(ROOT / 'firmware/bootloader_probe.bin'), str(ROOT / 'firmware/app_a_probe.bin')])
    # A later selection appends; it does not replace the first two files.
    page.locator('#firmware-set-files').set_input_files(str(ROOT / 'firmware/app_b_probe.bin'))
    expect(page.locator('.firmware-set-row')).to_have_count(3)
    for index, address in enumerate(('0x08000000', '0x08010000', '0x08020000')):
        page.locator('.firmware-image-address').nth(index).fill(address)
    for width, height in ((1024, 600), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        page.screenshot(path=str(ROOT / f'artifacts/multifirmware-{width}x{height}.png'), animations='disabled')
        contained()
    page.set_viewport_size({'width': 1024, 'height': 600})
    apply()
    programmed = state()
    assert len(programmed['firmwares']) == 3 and programmed['bootAddress'] == '0x08000000'
    assert [int(item['address'], 0) if isinstance(item['address'], str) else item['address']
            for item in programmed['firmwares']] == [0x08000000, 0x08010000, 0x08020000]
    expect(opener).to_have_text('多固件 · 3')

    run_from_bootloader('1', 'A', '0x08010000', 0)
    page.locator('#reset-button').click()
    wait_state("s.status === 'ready' && s.cpu.instructions === 0")
    assert len(state()['firmwares']) == 3
    run_from_bootloader('2', 'B', '0x08020000', 1)
    page.locator('#run-button').click()
    wait_state("s.status === 'paused'")

    # Existing immutable images are referenced by id. A bad set must retain both
    # the complete paused machine and all editable rows in the dialog.
    opener.click()
    expect(page.locator('.firmware-set-row')).to_have_count(3)
    expect(page.locator('.firmware-image-address')).to_have_count(0)
    page.locator('input[name="firmware-boot"]').nth(2).check()
    page.locator('#firmware-set-files').set_input_files(str(ROOT / 'firmware/app_b_probe.hex'))
    before = state()
    page.locator('#firmware-set-apply').click()
    expect(page.locator('#firmware-set-error')).to_be_visible()
    expect(page.locator('.firmware-set-row')).to_have_count(4)
    expect(page.locator('input[name="firmware-boot"]').nth(2)).to_be_checked()
    after = state()
    for field in ('firmwares', 'firmware', 'bootAddress', 'currentVectorAddress', 'cpu',
                  'status', 'serial', 'diagnostics', 'wires', 'keys', 'adc'):
        assert before[field] == after[field], field
    assert all(set(item) == {'id'} for item in uploads[-1]['images'][:3])
    assert uploads[-1]['bootIndex'] == 2
    page.locator('.firmware-remove').last.click()
    apply()
    assert state()['bootAddress'] == '0x08020000'
    assert all(set(item) == {'id'} for item in uploads[-1]['images'])
    page.locator('#run-button').click()
    wait_for_terminal_text(page, 'APP B READY')
    assert 'BOOT READY' not in page.locator('#terminal').inner_text()

    # Explicit vector address takes precedence only when selected in the UI;
    # the request contains exactly one selection mechanism.
    opener.click()
    page.locator('#firmware-set-advanced summary').click()
    page.locator('#firmware-set-custom').check()
    page.locator('#firmware-set-boot-address').fill('0x08010000')
    apply()
    assert uploads[-1]['bootAddress'] == '0x08010000' and 'bootIndex' not in uploads[-1]
    assert state()['bootAddress'] == '0x08010000'

    # Cancel applies none of a draft's removals or startup changes.
    before = state()
    opener.click()
    page.locator('.firmware-remove').first.click()
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    expect(opener).to_be_focused()
    after = state()
    for field in ('firmwares', 'bootAddress', 'cpu', 'status'):
        assert before[field] == after[field], field

    # No fixed two-slot limit: preserve three program images and add five data
    # images that deliberately contain no vectors, with independent addresses.
    opener.click()
    page.locator('input[name="firmware-boot"]').first.focus()
    page.keyboard.press('ArrowDown')
    expect(page.locator('input[name="firmware-boot"]').nth(1)).to_be_focused()
    expect(page.locator('input[name="firmware-boot"]').nth(1)).to_be_checked()
    page.locator('#firmware-set-files').set_input_files([
        {'name': f'data-{index}.bin', 'mimeType': 'application/octet-stream', 'buffer': bytes((index, 1, 2, 3))}
        for index in range(5)])
    expect(page.locator('.firmware-set-row')).to_have_count(8)
    for index in range(5):
        page.locator('.firmware-image-address').nth(index).fill(hex(0x08030000 + index * 0x1000))
    for width, height in ((1024, 600), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        contained()
        assert page.locator('#firmware-set-list').evaluate('e => e.scrollHeight > e.clientHeight')
    apply()
    eight = state()
    assert len(eight['firmwares']) == 8 and eight['bootAddress'] == '0x08010000'

    # Export v3 includes all images. The old import entry still replaces the
    # whole set, and opening the saved project restores all eight and startup.
    page.set_viewport_size({'width': 1024, 'height': 600})
    page.locator('[data-panel="wires"]').click()
    with page.expect_download() as event:
        page.locator('#save-project').click()
    saved = ROOT / 'artifacts/multifirmware-project.json'
    event.value.save_as(saved)
    project = json.loads(saved.read_text(encoding='utf-8'))
    assert project['version'] == 3 and len(project['firmwareSet']['images']) == 8
    page.locator('#firmware-file').set_input_files(str(ROOT / 'firmware/demo.bin'))
    page.locator('#import-confirm').click()
    expect(page.locator('#firmware-name')).to_have_text('demo.bin')
    assert len(state()['firmwares']) == 1
    page.locator('#project-file').set_input_files(str(saved))
    wait_state("s.firmwares.length === 8 && s.bootAddress === '0x08010000'")
    assert state()['firmwares'] == eight['firmwares']
    expect(page.locator('#wire-count')).to_have_text('12')

    # Legal whitespace does not add Flash bytes, but it exercises the transport
    # budget. This request exceeds the old 6 MiB UI limit while remaining within
    # the backend's 8 MiB portable set budget and 16 MiB HTTP request limit.
    opener.click()
    for _ in range(8):
        page.locator('.firmware-remove').first.click()
    padded = []
    for name in ('bootloader_probe', 'app_a_probe'):
        raw = (ROOT / f'firmware/{name}.hex').read_bytes() + b'\n' + b' ' * (5 * 1024 * 1024 // 2) + b'\n'
        padded.append({'name': f'{name}-padded.hex', 'mimeType': 'text/plain', 'buffer': raw})
    page.locator('#firmware-set-files').set_input_files(padded)
    apply()
    request_size = len(json.dumps(uploads[-1]).encode('utf-8'))
    assert 6 * 1024 * 1024 < request_size < 16 * 1024 * 1024
    assert len(state()['firmwares']) == 2 and state()['bootAddress'] == '0x08000000'
    assert not errors, errors
    print('PASS: real 3-BIN Bootloader/App A/App B with UART-selected execution and VTOR/LED evidence; '
          'id reuse; atomic conflict rejection; radio/custom startup; cancel; 8-image set; '
          '1024x600/390px scrolling dialog; v3 project roundtrip; legacy single import; '
          'valid upload above 6 MiB; no JS exceptions.')
    browser.close()
