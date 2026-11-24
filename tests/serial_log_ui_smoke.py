"""Ensure arbitrary transport chunks stay on one TX row in the workbench."""
from pathlib import Path
import sys

from playwright.sync_api import expect, sync_playwright


def fragment(index, payload, *, direction='tx', channel='ch340'):
    return {'id': index, 'channel': channel, 'direction': direction, 'time': '09:30:00',
            'hex': payload.hex(' ').upper(), 'text': payload.decode('utf-8', errors='replace')}


def main(url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel='msedge' if sys.platform == 'win32' else None)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            response = page.request.get(f'{url}/api/state')
            assert response.ok, response.status
            snapshot = response.json()
            serial = [fragment(1, b'DMA data: Hel')]
            page.route('**/api/state', lambda route: route.fulfill(json={**snapshot, 'serial': serial}))
            page.route('**/api/updates**', lambda route: route.abort())
            page.goto(url)
            rows = page.locator('#terminal .log-line')
            content = rows.locator('.log-content')
            expect(content).to_have_text(['DMA data: Hel'])

            serial.append(fragment(2, b'lo\r'))
            serial.append(fragment(3, b'\nNext\n'))
            expect(content).to_have_text(['DMA data: Hello', 'Next'])

            utf8 = '串口🙂'.encode()
            serial.append(fragment(4, b'\x00' + utf8[:2]))
            serial.append(fragment(5, b'unrelated\n', channel='rs485'))
            serial.append(fragment(6, utf8[2:] + b'\n'))
            expect(rows).to_have_count(3)
            assert content.all_text_contents()[-1] == '\x00串口🙂'

            page.locator('#serial-format').select_option('hex')
            expect(content.last).to_have_text((b'\x00' + utf8 + b'\n').hex(' ').upper())
            page.locator('[data-channel="rs485"]').click()
            expect(content).to_have_text([b'unrelated\n'.hex(' ').upper()])
            page.locator('[data-channel="ch340"]').click()
            page.locator('#serial-format').select_option('ascii')
            with page.expect_download() as download:
                page.locator('#export-button').click()
            exported = Path(download.value.path()).read_text(encoding='utf-8')
            assert 'DMA data: Hello\n' in exported and '串口🙂\n' in exported, exported
            assert '[rs485] [tx] unrelated' in exported and '\ufffd' not in exported, exported

            serial.append(fragment(7, b'old partial'))
            expect(content.last).to_have_text('old partial')
            page.locator('#clear-button').click()
            expect(rows).to_have_count(0)
            serial.append(fragment(8, b'new partial'))
            serial.append(fragment(9, b'host', direction='rx'))
            serial.append(fragment(10, b'new line\n'))
            expect(content).to_have_text(['new partial', 'host', 'new line'])
            assert rows.locator('.log-direction').all_text_contents() == ['TX', 'RX', 'TX']
            assert not errors, errors
        finally:
            browser.close()
    print('PASS: UART TX grouping, partial rows, CRLF, UTF-8, HEX, export and log clearing')


if __name__ == '__main__':
    main(sys.argv[1].rstrip('/'))
