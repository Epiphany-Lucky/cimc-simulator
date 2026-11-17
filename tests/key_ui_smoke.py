"""Ordered physical key events, immediate feedback and release safety."""
import json
from pathlib import Path
import sys

from playwright.sync_api import expect, sync_playwright
from browser_waits import wait_for_api_state

ROOT = Path(__file__).resolve().parents[1]
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765').rstrip('/')

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='msedge' if sys.platform == 'win32' else None, headless=True)
    context = browser.new_context()
    context.add_init_script('''(() => {
      const originalFetch = window.fetch;
      window.keyEventProbe = { delayNextDown: false, sent: [] };
      window.fetch = async function(url, options) {
        const body = options?.body ? JSON.parse(options.body) : {};
        if (body.action === 'key') {
          if (body.pressed && window.keyEventProbe.delayNextDown) {
            window.keyEventProbe.delayNextDown = false;
            await new Promise(resolve => setTimeout(resolve, 350));
          }
          window.keyEventProbe.sent.push({ index: body.index, pressed: body.pressed });
        }
        return originalFetch.call(this, url, options);
      };
    })();''')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('dialog', lambda dialog: dialog.accept())
    page.goto(URL)
    expect(page.locator('#demo-button')).to_be_enabled()
    if page.locator('#board-select').input_value() != 'cimc-v1':
        page.locator('#board-select').select_option('cimc-v1')
        wait_for_api_state(page, URL, lambda state: state['board']['id'] == 'cimc-v1')
    page.locator('#demo-button').click()
    key = page.locator('#keys button').first
    expect(key).to_be_enabled()
    # Delay the first down request across a complete short tap. The resulting
    # network dispatch must retain down/up order and the UI must respond locally.
    immediate = page.evaluate('''async () => {
      const key = document.querySelector('#keys button');
      window.keyEventProbe.delayNextDown = true;
      key.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      const down = key.classList.contains('pressed');
      await new Promise(resolve => setTimeout(resolve, 30));
      key.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
      return { down, up: !key.classList.contains('pressed') };
    }''')
    assert immediate == {'down': True, 'up': True}, immediate
    page.wait_for_function('() => window.keyEventProbe.sent.length === 2')
    wait_for_api_state(page, URL, lambda state: not any(state['keys']))
    assert page.evaluate('window.keyEventProbe.sent') == [
        {'index': 0, 'pressed': True}, {'index': 0, 'pressed': False}]
    # Use actual mouse capture and keyboard focus release through the same UI.
    key.scroll_into_view_if_needed()
    box = key.bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.mouse.down()
    wait_for_api_state(page, URL, lambda state: state['keys'][0])
    page.mouse.up()
    wait_for_api_state(page, URL, lambda state: not any(state['keys']))
    key.focus()
    page.keyboard.down('Space')
    wait_for_api_state(page, URL, lambda state: state['keys'][0])
    page.locator('#settings-button').focus()
    page.keyboard.up('Space')
    wait_for_api_state(page, URL, lambda state: not any(state['keys']))
    assert not errors, errors
    context.close()
    browser.close()

(ROOT / 'artifacts/key-ui-smoke.json').write_text(json.dumps({
    'passed': True, 'delayedDownMs': 350, 'shortTapMs': 30,
    'immediateFeedback': immediate, 'orderedDownUp': True,
    'mouseCaptureRelease': True, 'keyboardBlurRelease': True,
    'javascriptErrors': errors}, indent=2), encoding='utf-8')
print('PASS: ordered short key events, immediate feedback, mouse capture and keyboard focus release')
