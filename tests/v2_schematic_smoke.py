"""V2 diagram, editable reference wiring, and all five original PDF pages."""
import hashlib
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8871'
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='msedge' if sys.platform == 'win32' else None, headless=True)
    page = browser.new_page(viewport={'width': 1024, 'height': 600})
    page.add_init_script("localStorage.setItem('cimc.studio.preferences', JSON.stringify({autoUpdates:false}));")
    page.on('dialog', lambda dialog: dialog.accept())
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    expect(page.locator('#demo-button')).to_be_enabled()
    page.locator('#board-select').select_option('cimc-v2')
    expect(page.locator('#board-image')).to_have_attribute('src', 'assets/board-v2.svg')
    expect(page.locator('#schematic-button')).to_be_enabled()
    page.locator('#wiring-example').click()
    page.locator('[data-panel="wires"]').click()
    expect(page.locator('#wire-list .icon-button').first).to_be_visible()
    before = page.locator('#wire-list .icon-button').count()
    assert before > 0
    page.locator('#wire-list .icon-button').first.click()
    expect(page.locator('#wire-list .icon-button')).to_have_count(before - 1)
    page.locator('#wiring-example').click()
    expect(page.locator('#wire-list .icon-button')).to_have_count(before)
    page.locator('#schematic-button').click()
    for number in range(1, 6):
        page.locator('#schematic-page-select').select_option(str(number))
        expect(page.locator('#schematic-image')).to_be_visible()
        expect(page.locator('#schematic-image')).to_have_attribute('src', f'assets/schematics/v2-page-{number}.png')
        page.wait_for_function('document.querySelector("#schematic-image").complete && document.querySelector("#schematic-image").naturalWidth > 1000')
    original = (ROOT / 'web/assets/schematics/GD32F470-V2.0-schematic.pdf').read_bytes()
    response = page.request.get(url + '/assets/schematics/GD32F470-V2.0-schematic.pdf')
    assert response.ok and hashlib.sha256(response.body()).digest() == hashlib.sha256(original).digest()
    assert hashlib.sha256(original).hexdigest() == '6289165231ed57c3dc1b15c1ebc0b90172f9b805d441accecb619a906aacc1ef'
    page.locator('#schematic-dialog [data-close]').click()
    for width, height in ((1024, 600), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        page.evaluate('scrollTo(0,0)')
        page.wait_for_timeout(100)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.screenshot(path=str(ROOT / f'artifacts/v2-schematic-ui-{width}.png'), full_page=True)
    assert not errors, errors
    browser.close()
print('PASS: V2 SVG workbench, editable reference wires, five original schematic pages and byte-identical PDF')
