"""Verify update notices and controls with deterministic release responses."""
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
URL=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765'
RELEASE='https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.4.0'
fixture={'status':'ok','message':'发现新版本 0.4.0','currentVersion':'0.3.0',
         'latestVersion':'0.4.0','available':True,'releaseUrl':RELEASE,'platform':'windows',
         'assets':{'windowsInstaller':RELEASE.replace('/tag/','/download/')+'/CIMC-Studio-0.4.0-Setup-x64.exe',
                   'html':'https://untrusted.invalid/payload.zip'}}
requests=[]
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(channel='msedge' if sys.platform=='win32' else None,headless=True)
    page=browser.new_page(viewport={'width':1024,'height':600})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    def reply(route):
        requests.append(route.request.url)
        route.fulfill(status=200,content_type='application/json',body=json.dumps(fixture))
    page.route('**/api/updates*',reply)
    page.goto(URL)
    expect(page.locator('#settings-button')).to_have_class('rail-button has-update')
    expect(page.locator('#toast')).to_contain_text('0.4.0 已发布')
    assert len(requests)==1 and 'force=1' not in requests[0]
    page.locator('#settings-button').click()
    expect(page.locator('#update-current')).to_have_text('当前版本 0.3.0')
    expect(page.locator('#update-downloads a')).to_have_count(2)
    expect(page.get_by_role('link',name='Windows 安装包')).to_have_attribute('target','_blank')
    assert not page.locator('a[href*="untrusted.invalid"]').count()
    for width,height in ((1024,600),(390,844)):
        page.set_viewport_size({'width':width,'height':height})
        box=page.locator('#settings-dialog').bounding_box()
        assert box and box['x']>=0 and box['y']>=0
        assert box['x']+box['width']<=width+1 and box['y']+box['height']<=height+1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(ROOT/'artifacts/update-settings-mobile.png'),animations='disabled')
    fixture.update(status='error',message='暂时无法检查更新，请稍后重试。',available=False)
    page.locator('#check-updates').click()
    expect(page.locator('#update-status')).to_contain_text('暂时无法检查更新')
    expect(page.locator('#check-updates')).to_be_enabled()
    assert requests[-1].endswith('?force=1')
    expect(page.locator('#update-downloads')).to_be_hidden()
    page.locator('#setting-updates').uncheck()
    page.reload()
    expect(page.locator('#demo-button')).to_be_enabled()
    page.wait_for_timeout(500)
    assert len(requests)==2,'Automatic check ignored disabled preference'
    page.locator('#about-button').click()
    page.locator('#about-settings-button').click()
    expect(page.locator('#setting-updates')).not_to_be_checked()
    fixture.update(status='ok',available=False,latestVersion='0.3.0',message='当前已是最新版本。')
    page.locator('#check-updates').click()
    expect(page.locator('#update-status')).to_have_text('当前已是最新版本。')
    expect(page.locator('#settings-button')).not_to_have_class('rail-button has-update')
    assert not errors,errors
    browser.close()
print('PASS: automatic update notification, manual retry, safe download links, offline state, preference and laptop/mobile containment')
