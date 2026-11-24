"""Exercise application update controls with intercepted local API responses."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765'
RELEASE = 'https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v9.0.0'


def fixture(can_install=True):
    return {'status': 'ok', 'message': '发现新版本 9.0.0', 'currentVersion': '0.9.0',
            'latestVersion': '9.0.0', 'available': True, 'releaseUrl': RELEASE,
            'platform': 'windows' if can_install else 'linux', 'assets': {},
            'updater': {'token': 'test-update-token', 'canInstall': can_install,
                        'mode': 'windowsInstaller' if can_install else 'linuxPortable',
                        'message': '下载校验后安装。'}}


def main():
    errors = []
    mutations = []
    state = {'status': 'idle', 'token': 'test-update-token', 'canInstall': True,
             'percent': 0, 'receivedBytes': 0, 'totalBytes': 1000, 'message': '下载校验后安装。'}
    metadata = fixture()
    install_attempts = 0
    def reply(route):
        nonlocal install_attempts
        path = urlsplit(route.request.url).path
        if route.request.method == 'POST':
            body = route.request.post_data_json
            assert body['token'] == 'test-update-token', body
            mutations.append((path, body))
            if path.endswith('/download'):
                assert body['version'] == '9.0.0'
                state.update(status='downloading', percent=67, receivedBytes=670,
                             message='正在下载并校验更新…')
            elif path.endswith('/install'):
                install_attempts += 1
                if install_attempts == 1:
                    route.fulfill(status=400, content_type='application/json',
                                  body=json.dumps({'error': '演练安装启动失败，请重试。'}))
                    return
                state.update(status='installing', willExit=True)
            result = state
        else:
            result = state if path.endswith('/status') else metadata
        route.fulfill(status=200, content_type='application/json', body=json.dumps(result))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge' if sys.platform == 'win32' else None, headless=True)
        context = browser.new_context(viewport={'width': 1024, 'height': 600}, accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/api/updates**', reply)
        page.goto(URL)
        expect(page.locator('#settings-button')).to_have_class('rail-button has-update')
        page.locator('#settings-button').click()
        expect(page.locator('#download-update')).to_be_enabled()
        expect(page.locator('#install-update')).to_be_hidden()
        page.locator('#download-update').click()
        expect(page.locator('#download-update')).to_be_disabled()
        expect(page.locator('#update-progress')).to_have_js_property('value', 67)
        expect(page.locator('#update-install-status')).to_contain_text('67%')
        state.update(status='error', message='更新文件未通过 SHA-256 校验，请重新下载。')
        expect(page.locator('#download-update')).to_have_text('重新下载')
        expect(page.locator('#download-update')).to_be_enabled()
        expect(page.locator('#update-install-status')).to_contain_text('SHA-256')
        page.locator('#download-update').click()
        expect(page.locator('#download-update')).to_be_disabled()
        state.update(status='ready', percent=100, receivedBytes=1000,
                     filePath=r'C:\CIMC update 中文\CIMC-Studio-9.0.0-Setup-x64.exe',
                     message='下载和 SHA-256 校验完成。请先保存工程，再安装更新。')
        expect(page.locator('#install-update')).to_have_text('安装并重启')
        expect(page.locator('#install-update')).to_be_visible()
        expect(page.locator('#update-install-status')).to_contain_text(state['filePath'])
        with page.expect_download() as pending_download:
            page.locator('#update-save-project').click()
        downloaded = pending_download.value
        assert downloaded.suggested_filename.endswith('.json')
        for width, height in ((1024, 600), (390, 844)):
            page.set_viewport_size({'width': width, 'height': height})
            box = page.locator('#settings-dialog').bounding_box()
            assert box and box['x'] >= 0 and box['y'] >= 0
            assert box['x']+box['width'] <= width+1 and box['y']+box['height'] <= height+1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path=str(ROOT/f'artifacts/self-update-ui-{width}.png'), animations='disabled')
        page.once('dialog', lambda dialog: dialog.dismiss())
        page.locator('#install-update').click()
        assert install_attempts == 0, 'Dismissed install confirmation launched an installer'
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('#install-update').click()
        expect(page.locator('#update-install-status')).to_contain_text('演练安装启动失败')
        expect(page.locator('#install-update')).to_be_enabled()
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('#install-update').click()
        expect(page.locator('#update-install-status')).to_contain_text('安装完成后将重新启动')
        assert install_attempts == 2
        context.close()

        metadata = fixture(False)
        state.update(status='ready', canInstall=False, willExit=False,
                     filePath='/home/test/.cache/cimc-studio/updates/CIMC-Studio-9.0.0-linux-x64.tar.gz')
        portable = browser.new_page(viewport={'width': 390, 'height': 844})
        portable.on('pageerror', lambda error: errors.append(str(error)))
        portable.route('**/api/updates**', reply)
        portable.goto(URL)
        expect(portable.locator('#settings-button')).to_have_class('rail-button has-update')
        portable.locator('#about-button').click()
        portable.locator('#about-settings-button').click()
        expect(portable.locator('#install-update')).to_have_text('打开已校验文件夹')
        portable.locator('#install-update').click()
        expect(portable.locator('#install-update')).to_be_enabled()
        assert mutations[-1][0] == '/api/updates/open'
        assert install_attempts == 2, 'Portable folder action launched an installer'
        assert not errors, errors
        browser.close()
    (ROOT/'artifacts/self-update-ui-smoke.json').write_text(json.dumps({
        'passed': True, 'downloadProgress': True, 'checksumErrorRetry': True,
        'projectExport': True, 'installConfirmationDismiss': True, 'installFailureRetry': True,
        'exitHandoff': True, 'portableOpenFolder': True, 'javascriptErrors': errors,
        'realInstallerLaunched': False}, indent=2)+'\n', encoding='utf-8')
    print('PASS: update progress, checksum error/retry, project export, install confirmation/failure/retry, exit handoff and portable-folder action')


if __name__ == '__main__':
    main()
