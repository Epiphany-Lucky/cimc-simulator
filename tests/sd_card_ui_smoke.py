"""Exercise binary TF image upload and download in a fresh isolated workbench."""

import argparse
from pathlib import Path
import sys
from urllib.parse import urlencode

from playwright.sync_api import expect, sync_playwright


IMAGE_NAME = '验证 卡.img'

def card_state(page, url):
    reply = page.request.get(f'{url}/api/state')
    assert reply.ok, reply.text()
    state = reply.json()
    return state.get('state', state)['sdCard']


def select_image(page, url, data, read_only):
    upload = {'name': IMAGE_NAME, 'mimeType': 'application/octet-stream', 'buffer': data}
    query = urlencode({'readOnly': int(read_only), 'name': IMAGE_NAME})
    endpoint = f'{url}/api/sd-card?{query}'
    with page.expect_response(lambda reply: reply.url == endpoint and reply.request.method == 'POST') as pending:
        page.locator('#sd-card-file').set_input_files(upload)
    response = pending.value
    assert response.request.headers['content-type'] == 'application/octet-stream'
    return response


def verify_cancel_changed_card(page, url, panel, image):
    def simulate_writes(route):
        response = route.fetch()
        payload = response.json()
        payload.get('state', payload)['sdCard']['sectorsWritten'] = 2
        route.fulfill(response=response, json=payload)

    def dismiss(dialog):
        prompts.append(dialog.message)
        dialog.dismiss()

    prompts = []
    writes = panel.locator('#sd-card-writes')
    page.route('**/api/state', simulate_writes)
    try:
        expect(writes).to_have_text('2')
        page.once('dialog', dismiss)
        panel.get_by_role('button', name='弹出').click()
        page.once('dialog', dismiss)
        page.locator('#sd-card-file').set_input_files({
            'name': 'replacement.img', 'mimeType': 'application/octet-stream', 'buffer': image + bytes(512),
        })
        assert len(prompts) == 2 and all('请先导出' in message for message in prompts), prompts
        assert card_state(page, url)['capacityBytes'] == len(image)
    finally:
        page.unroute('**/api/state', simulate_writes)
    expect(writes).to_have_text('0')


def check(url, screenshot=None):
    image = bytes(range(256)) * 4096
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge' if sys.platform == 'win32' else None, headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/updates**', lambda request: request.abort())
            page.goto(url, wait_until='domcontentloaded')
            assert not card_state(page, url)['inserted'], 'Start a fresh isolated workbench without a mounted card'
            panel = page.get_by_role('article', name='TF 卡')
            mount = panel.get_by_role('button', name='挂载镜像')
            eject = panel.get_by_role('button', name='弹出')
            export = panel.get_by_role('button', name='导出镜像')
            option = panel.get_by_role('checkbox', name='只读挂载')
            status = panel.get_by_role('status')
            expect(mount).to_be_enabled()
            expect(eject).to_be_disabled()
            expect(export).to_be_disabled()
            expect(status).to_have_text('未挂载镜像')
            expect(option).not_to_be_checked()

            option.check()
            mounted = select_image(page, url, image, True)
            assert mounted.ok, mounted.text()
            expect(status).to_have_text('已挂载 · 只读')
            expect(panel.locator('#sd-card-capacity')).to_have_text('1.0 MB')
            expect(panel.locator('#sd-card-name')).to_have_text(IMAGE_NAME)
            card = card_state(page, url)
            assert card['inserted'] and card['readOnly']
            assert card['capacityBytes'] == len(image) and card['sectorsRead'] == card['sectorsWritten'] == 0
            expect(export).to_be_enabled()
            with page.expect_download() as pending:
                export.click()
            download = pending.value
            assert download.suggested_filename.lower().endswith('.img')
            assert Path(download.path()).read_bytes() == image

            invalid = select_image(page, url, image[:513], True)
            assert 400 <= invalid.status < 500
            expect(page.locator('#toast')).to_have_class('toast visible')
            expect(status).to_have_text('已挂载 · 只读')
            assert card_state(page, url)['capacityBytes'] == len(image)

            eject.click()
            expect(status).to_have_text('未挂载镜像')
            expect(export).to_be_disabled()
            assert not card_state(page, url)['inserted']
            option.uncheck()
            mounted = select_image(page, url, image, False)
            assert mounted.ok, mounted.text()
            expect(status).to_have_text('已挂载 · 可写')
            assert not card_state(page, url)['readOnly']
            verify_cancel_changed_card(page, url, panel, image)

            page.set_viewport_size({'width': 390, 'height': 844})
            expect(panel).to_be_visible()
            bounds = panel.bounding_box()
            assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if screenshot:
                expect(page.locator('#toast')).not_to_have_class('toast visible', timeout=8000)
                panel.evaluate("element => element.scrollIntoView({ block: 'center', behavior: 'instant' })")
                panel.screenshot(path=screenshot)
            eject.click()
            expect(status).to_have_text('未挂载镜像')
            assert not card_state(page, url)['inserted'] and not errors, errors
        finally:
            browser.close()
    print('PASS: raw TF image mount/export, read-only selection, invalid image, dirty-card confirmation, eject and layout')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='URL of a fresh isolated CIMC Studio engine')
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    check(args.url.rstrip('/'), args.screenshot)
