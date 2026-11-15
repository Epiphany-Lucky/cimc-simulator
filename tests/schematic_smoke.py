"""Schematic reader acceptance. Pass a live server URL as the optional argument."""
import hashlib
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765').rstrip('/')
PDF = ROOT / 'web/assets/schematics/GD32F470-V1.0-schematic.pdf'
PDF_SHA256 = '74c365aea16ddb43fc74b3f3b43707db5c079b9c07a3f8674321df9f1597e6ed'
assert hashlib.sha256(PDF.read_bytes()).hexdigest() == PDF_SHA256
(ROOT / 'artifacts').mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge' if sys.platform=='win32' else None, headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 720}, accept_downloads=True)
    errors, commands, file_choosers = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: commands.append(request.post_data_json)
            if request.method == 'POST' and request.url.endswith('/api/command') else None)
    page.on('filechooser', lambda chooser: file_choosers.append(chooser))
    page.goto(URL)
    expect(page.locator('#demo-button')).to_be_enabled()
    # A preceding suite may already have 12 wires. Wait for this load's response
    # before snapshotting IDs; the count alone does not prove it has completed.
    with page.expect_response(lambda response: response.url.endswith('/api/command')
                              and response.request.post_data_json.get('action') == 'demo') as loaded:
        page.locator('#demo-button').click()
    assert loaded.value.ok
    loaded.value.finished()
    expect(page.locator('#wire-count')).to_have_text('12')
    before = page.request.get(URL + '/api/state').json()
    opener = page.locator('#schematic-button')
    dialog = page.locator('#schematic-dialog')
    image = page.locator('#schematic-image')

    def ready_image(number):
        page.wait_for_function("n => { const i = document.querySelector('#schematic-image'); "
                               "return i.complete && i.naturalWidth === 3200 && i.naturalHeight === 2257 "
                               "&& i.src.endsWith('v1-page-' + n + '.png') && !i.hidden; }", arg=number)
        expect(image).to_be_visible()

    def contained():
        width, height = page.viewport_size['width'], page.viewport_size['height']
        box = dialog.bounding_box()
        assert box and 0 <= box['x'] and 0 <= box['y']
        assert box['x'] + box['width'] <= width and box['y'] + box['height'] <= height, box
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth + 1')

    opener.click()
    expect(dialog).to_be_visible()
    ready_image(1)
    expect(page.locator('#schematic-prev')).to_be_disabled()
    expect(page.locator('#schematic-page-count')).to_have_text('1 / 4')

    # The modal prevents firmware shortcuts, including Ctrl+O before the editing guard.
    commands.clear()
    page.locator('#schematic-viewport').focus()
    page.keyboard.press('Space')
    page.keyboard.press('1')
    page.keyboard.press('Control+o')
    after = page.request.get(URL + '/api/state').json()
    assert not commands, commands
    assert not file_choosers
    for field in ('status', 'firmware', 'wires', 'serialMode', 'keys'):
        assert before[field] == after[field], field

    for number in range(2, 5):
        page.locator('#schematic-next').click()
        ready_image(number)
        expect(page.locator('#schematic-page-count')).to_have_text(f'{number} / 4')
    expect(page.locator('#schematic-next')).to_be_disabled()
    page.locator('#schematic-prev').click()
    ready_image(3)
    page.locator('#schematic-page-select').select_option('2')
    ready_image(2)

    # Zoomed image scrolls only within the reader; Fit restores the page width.
    for width, height in ((1024, 600), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        for zoom in ('100', '200'):
            page.locator('#schematic-zoom').select_option(zoom)
            assert round(image.bounding_box()['width']) == 3200 * int(zoom) // 100
            assert page.locator('#schematic-viewport').evaluate('e => e.scrollWidth > e.clientWidth')
            contained()
        page.locator('#schematic-zoom').select_option('fit')
        assert page.locator('#schematic-viewport').evaluate('e => e.scrollWidth <= e.clientWidth + 1')
        contained()
        page.screenshot(path=str(ROOT / f'artifacts/schematic-{width}x{height}.png'))

    with page.expect_download() as download_event:
        page.locator('#schematic-download').click()
    saved = ROOT / 'artifacts/schematic-original-download.pdf'
    download_event.value.save_as(saved)
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == PDF_SHA256
    pdf_link = page.locator('#schematic-open-pdf')
    expect(pdf_link).to_have_attribute('target', '_blank')
    expect(pdf_link).to_have_attribute('rel', 'noopener')
    response = page.request.get(URL + '/' + pdf_link.get_attribute('href'))
    assert response.ok and hashlib.sha256(response.body()).hexdigest() == PDF_SHA256

    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    expect(opener).to_be_focused()
    expect(opener).to_have_attribute('aria-expanded', 'false')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    opener.click()
    ready_image(2)
    page.locator('.schematic-close').click()
    expect(dialog).not_to_be_visible()
    expect(opener).to_be_focused()
    assert not errors, errors
    print('PASS: four complete 3200px schematic pages; page navigation and 100%/200%/Fit zoom; '
          '1024x600 and 390px reader containment; original PDF SHA256 preserved; '
          'firmware shortcuts blocked; Escape/Close restore focus; no JS exceptions.')
    browser.close()
