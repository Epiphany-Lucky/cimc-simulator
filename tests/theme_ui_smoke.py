"""Theme controls, application preference persistence and visual semantics."""
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765').rstrip('/')
COLORS = {'blue': ('蓝色', 'rgb(0, 113, 227)'), 'teal': ('青色', 'rgb(0, 123, 127)'),
          'green': ('绿色', 'rgb(35, 122, 70)'), 'purple': ('紫色', 'rgb(117, 80, 180)'),
          'rose': ('玫红', 'rgb(181, 46, 104)'), 'amber': ('琥珀', 'rgb(154, 98, 0)')}


def contrast(first, second):
    def luminance(color):
        channels = [int(value) / 255 for value in re.findall(r'\d+', color)[:3]]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + .05) / (values[0] + .05)


def configure(context, errors, commands):
    context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
    context.on('request', lambda request: commands.append(request.url)
               if request.method == 'POST' and urlsplit(request.url).path == '/api/command' else None)
    context.route('**/api/updates**', lambda route: route.fulfill(content_type='application/json', body=json.dumps({
        'status': 'ok', 'message': '当前已是最新版本', 'currentVersion': '0.8.1',
        'latestVersion': '0.8.1', 'available': False, 'assets': {}})))


def set_server(context, color):
    response = context.request.post(URL + '/api/preferences', data={'themeColor': color}, headers={'Origin': URL})
    assert response.ok, response.text()
    assert response.json()['themeColor'] == color


def selected(page, color):
    page.wait_for_function('(color) => document.documentElement.dataset.themeColor === color', arg=color)
    expect(page.get_by_role('radio', name=COLORS[color][0], exact=True)).to_be_checked()


def open_settings(page):
    if not page.locator('#settings-dialog').is_visible():
        page.locator('#settings-button').click()
    expect(page.get_by_role('group', name='主题颜色')).to_be_visible()


def choose(page, color):
    radio = page.get_by_role('radio', name=COLORS[color][0], exact=True)
    if not radio.is_checked():
        with page.expect_response(lambda response: urlsplit(response.url).path == '/api/preferences'
                                  and response.request.method == 'POST'
                                  and response.request.post_data_json == {'themeColor': color}) as saved:
            radio.check()
        assert saved.value.ok
    selected(page, color)
    page.wait_for_function('''(expected) => getComputedStyle(
      document.querySelector('#settings-dialog > .button.primary')).backgroundColor === expected''', arg=COLORS[color][1])


def visual_style(page):
    return page.evaluate('''() => {
      const primary = getComputedStyle(document.querySelector('#settings-dialog > .button.primary'));
      const rail = getComputedStyle(document.querySelector('.rail-button.active'));
      return {background: primary.backgroundColor, text: primary.color,
        railBackground: rail.backgroundColor, railText: rail.color,
        logo: getComputedStyle(document.querySelector('.brand-mark')).backgroundImage,
        wires: [...document.querySelectorAll('#wire-layer path:not(.wire-hit)')].map(path => path.getAttribute('stroke'))};
    }''')


def main():
    errors, commands, evidence = [], [], []
    report = {'passed': False}
    previous = None
    browser = None
    with sync_playwright() as playwright, tempfile.TemporaryDirectory(prefix='cimc-theme-profile-') as profile:
        options = {'channel': 'msedge' if sys.platform == 'win32' else None, 'headless': True}
        context = playwright.chromium.launch_persistent_context(profile, viewport={'width': 1024, 'height': 600}, **options)
        configure(context, errors, commands)
        try:
            previous = context.request.get(URL + '/api/preferences').json()['themeColor']
            set_server(context, 'blue')
            page = context.new_page()
            page.goto(URL)
            open_settings(page)
            selected(page, 'blue')
            initial_wires = visual_style(page)['wires']
            for color in COLORS:
                choose(page, color)
                style = visual_style(page)
                assert style['background'] == COLORS[color][1], style
                primary_contrast = contrast(style['background'], style['text'])
                rail_contrast = contrast(style['railBackground'], style['railText'])
                assert primary_contrast >= 4.5 and rail_contrast >= 4.5, (color, primary_contrast, rail_contrast)
                assert style['wires'] == initial_wires
                assert page.evaluate("JSON.parse(localStorage.getItem('cimc.studio.preferences')).themeColor") == color
                evidence.append({'color': color, 'primaryContrast': round(primary_contrast, 3),
                                 'railContrast': round(rail_contrast, 3), 'logo': style['logo']})
                page.reload()
                open_settings(page)
                selected(page, color)
            assert len({item['logo'] for item in evidence}) == 6
            choose(page, 'purple')
            for width, height in ((1024, 600), (390, 844)):
                page.set_viewport_size({'width': width, 'height': height})
                page.get_by_role('group', name='主题颜色').scroll_into_view_if_needed()
                page.locator('#settings-dialog').evaluate('(dialog) => { dialog.scrollTop = 0; }')
                box = page.locator('#settings-dialog').bounding_box()
                assert box and box['x'] >= 0 and box['y'] >= 0
                assert box['x'] + box['width'] <= width + 1 and box['y'] + box['height'] <= height + 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(ROOT / f'artifacts/theme-ui-{width}.png'), animations='disabled')
            context.close()
            context = playwright.chromium.launch_persistent_context(profile, viewport={'width': 1024, 'height': 600}, **options)
            configure(context, errors, commands)
            page = context.new_page()
            page.goto(URL)
            open_settings(page)
            selected(page, 'purple')
            assert page.evaluate("JSON.parse(localStorage.getItem('cimc.studio.preferences')).themeColor") == 'purple'
            context.close()
            browser = playwright.chromium.launch(**options)
            context = browser.new_context(viewport={'width': 1024, 'height': 600})
            configure(context, errors, commands)
            page = context.new_page()
            other_origin = URL.replace('127.0.0.1', 'localhost')
            page.goto(other_origin)
            open_settings(page)
            selected(page, 'purple')
            page.get_by_role('radio', name='紫色', exact=True).focus()
            with page.expect_response(lambda response: urlsplit(response.url).path == '/api/preferences'
                                      and response.request.method == 'POST') as saved:
                page.keyboard.press('ArrowRight')
            assert saved.value.ok
            selected(page, 'rose')
            with page.expect_response(lambda response: urlsplit(response.url).path == '/api/preferences'
                                      and response.request.method == 'POST'
                                      and response.request.post_data_json == {'themeColor': 'blue'}) as saved:
                for color in ('teal', 'green', 'purple', 'rose', 'amber', 'blue'):
                    page.get_by_role('radio', name=COLORS[color][0], exact=True).check()
            assert saved.value.ok
            assert context.request.get(URL + '/api/preferences').json()['themeColor'] == 'blue'
            selected(page, 'blue')
            set_server(context, 'blue')
            for invalid in ('{"themeColor":"unknown"}', '"old-invalid-value"', '[]', '{invalid json'):
                page.evaluate('(value) => localStorage.setItem("cimc.studio.preferences", value)', invalid)
                page.reload()
                open_settings(page)
                selected(page, 'blue')
            race_context = browser.new_context(viewport={'width': 1024, 'height': 600})
            configure(race_context, errors, commands)
            race_page = race_context.new_page()
            held = []
            def hold_initial_state(route):
                if not held:
                    held.append((route, route.fetch().json()))
                else:
                    route.continue_()
            race_page.route('**/api/state', hold_initial_state)
            with race_page.expect_request(lambda request: urlsplit(request.url).path == '/api/state'):
                race_page.goto(URL)
            open_settings(race_page)
            choose(race_page, 'teal')
            assert held[0][1]['preferences']['themeColor'] == 'blue'
            held[0][0].fulfill(json=held[0][1])
            race_page.wait_for_function("() => document.getElementById('connection-notice').hidden")
            selected(race_page, 'teal')
            race_context.close()
            assert not errors, errors
            assert not commands, commands
            report = {'passed': True, 'colors': evidence, 'reloadPersistence': True,
                      'persistentBrowserRestart': True, 'differentOriginAndNewContext': True,
                      'keyboardRadioSelection': True, 'invalidStorageFallback': True,
                      'rapidSelectionOrder': True, 'staleInitialStateDoesNotOverrideClick': True,
                      'hardwareWireColorsPreserved': True, 'engineCommandsSent': 0, 'javascriptErrors': errors}
        finally:
            if previous in COLORS:
                with urlopen(Request(URL + '/api/preferences', data=json.dumps({'themeColor': previous}).encode(),
                                     headers={'Origin': URL, 'Content-Type': 'application/json'}), timeout=10):
                    pass
            context.close()
            if browser:
                browser.close()
        (ROOT / 'artifacts/theme-ui-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: six accessible accent colors + live application + profile/server persistence + keyboard/mobile + safe legacy preferences')


if __name__ == '__main__':
    main()
