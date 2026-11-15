"""Native WPF acceptance: python tests/desktop_smoke.py ABSOLUTE_EXE_PATH.

Uses the real desktop size/DPI without changing display settings. Own process only.
WebView2's documented environment overrides isolate its profile and CDP listener:
https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/webview2-idl
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
import zlib

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


class MonitorInfo(C.Structure):
    _fields_=[('size',W.DWORD),('monitor',W.RECT),('work',W.RECT),('flags',W.DWORD)]


class BitmapHeader(C.Structure):
    _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),
              ('bits',W.WORD),('compression',W.DWORD),('imageSize',W.DWORD),
              ('xppm',W.LONG),('yppm',W.LONG),('used',W.DWORD),('important',W.DWORD)]


def native_api():
    user=C.WinDLL('user32',use_last_error=True)
    signatures={
        'SetProcessDpiAwarenessContext':([C.c_void_p],W.BOOL),
        'GetWindowThreadProcessId':([W.HWND,C.POINTER(W.DWORD)],W.DWORD),
        'IsWindowVisible':([W.HWND],W.BOOL),
        'GetWindowTextW':([W.HWND,W.LPWSTR,C.c_int],C.c_int),
        'GetWindowRect':([W.HWND,C.POINTER(W.RECT)],W.BOOL),
        'MonitorFromWindow':([W.HWND,W.DWORD],W.HANDLE),
        'GetMonitorInfoW':([W.HANDLE,C.POINTER(MonitorInfo)],W.BOOL),
        'GetDpiForWindow':([W.HWND],W.UINT),
        'SetForegroundWindow':([W.HWND],W.BOOL),
        'PostMessageW':([W.HWND,W.UINT,W.WPARAM,W.LPARAM],W.BOOL),
        'GetDC':([W.HWND],W.HDC),
        'ReleaseDC':([W.HWND,W.HDC],C.c_int),
    }
    for name,(args,result) in signatures.items():
        fn=getattr(user,name);fn.argtypes=args;fn.restype=result
    user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    return user


def own_window(user,pid):
    found=[]
    callback_type=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    @callback_type
    def visit(hwnd,_):
        owner=W.DWORD();user.GetWindowThreadProcessId(hwnd,C.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            title=C.create_unicode_buffer(512);user.GetWindowTextW(hwnd,title,512)
            if title.value.startswith('CIMC Studio'):found.append(hwnd)
        return True
    user.EnumWindows.argtypes=[callback_type,W.LPARAM];user.EnumWindows.restype=W.BOOL
    user.EnumWindows(visit,0)
    return found[0] if found else None


def rect_dict(rect):
    return dict(left=rect.left,top=rect.top,right=rect.right,bottom=rect.bottom,
                width=rect.right-rect.left,height=rect.bottom-rect.top)


def measure(user,hwnd):
    rect=W.RECT();info=MonitorInfo();info.size=C.sizeof(info)
    if not user.GetWindowRect(hwnd,C.byref(rect)):raise C.WinError(C.get_last_error())
    if not user.GetMonitorInfoW(user.MonitorFromWindow(hwnd,2),C.byref(info)):raise C.WinError(C.get_last_error())
    work=info.work
    inside=(rect.left>=work.left and rect.top>=work.top and rect.right<=work.right and rect.bottom<=work.bottom)
    return {'window':rect_dict(rect),'workArea':rect_dict(work),'monitor':rect_dict(info.monitor),
            'dpi':user.GetDpiForWindow(hwnd),'fullyInsideWorkArea':inside}


def capture_native_window(user,hwnd,path):
    """Capture visible native bounds, including WPF title bar, with Win32 GDI."""
    user.SetForegroundWindow(hwnd)
    time.sleep(.2)
    r=measure(user,hwnd)['window'];width,height=r['width'],r['height']
    gdi=C.WinDLL('gdi32',use_last_error=True)
    signatures={
        'CreateCompatibleDC':([W.HDC],W.HDC),
        'CreateCompatibleBitmap':([W.HDC,C.c_int,C.c_int],W.HANDLE),
        'SelectObject':([W.HDC,W.HANDLE],W.HANDLE),
        'BitBlt':([W.HDC,C.c_int,C.c_int,C.c_int,C.c_int,W.HDC,C.c_int,C.c_int,W.DWORD],W.BOOL),
        'GetDIBits':([W.HDC,W.HANDLE,W.UINT,W.UINT,C.c_void_p,C.c_void_p,W.UINT],C.c_int),
        'DeleteObject':([W.HANDLE],W.BOOL),'DeleteDC':([W.HDC],W.BOOL),
    }
    for name,(args,result) in signatures.items():
        fn=getattr(gdi,name);fn.argtypes=args;fn.restype=result
    screen=user.GetDC(None);memory=gdi.CreateCompatibleDC(screen)
    bitmap=gdi.CreateCompatibleBitmap(screen,width,height);old=gdi.SelectObject(memory,bitmap)
    try:
        if not gdi.BitBlt(memory,0,0,width,height,screen,r['left'],r['top'],0x00CC0020):raise C.WinError(C.get_last_error())
        header=BitmapHeader(C.sizeof(BitmapHeader),width,-height,1,32,0,0,0,0,0,0)
        pixels=C.create_string_buffer(width*height*4)
        gdi.SelectObject(memory,old)
        if gdi.GetDIBits(memory,bitmap,0,height,pixels,C.byref(header),0)!=height:raise RuntimeError('Native screenshot capture failed')
        bgra=pixels.raw;rgb=bytearray(width*height*3)
        rgb[0::3]=bgra[2::4];rgb[1::3]=bgra[1::4];rgb[2::3]=bgra[0::4]
        scan=b''.join(b'\0'+rgb[y*width*3:(y+1)*width*3] for y in range(height))
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+
                         chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b''))
    finally:
        gdi.SelectObject(memory,old);gdi.DeleteObject(bitmap);gdi.DeleteDC(memory);user.ReleaseDC(None,screen)


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(('127.0.0.1',port))==0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts'/'desktop-v0.2')
    args=parser.parse_args()
    if os.name!='nt':parser.error('This acceptance test requires Windows')
    if not args.exe.is_absolute() or not args.exe.is_file():parser.error('Pass an existing EXE absolute path')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    user=native_api()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));debug_port=sock.getsockname()[1]
    # Per-process overrides; never edit machine/user settings or the user's app profile.
    profile=Path(tempfile.mkdtemp(prefix='cimc-desktop-smoke-'))
    env=os.environ.copy()
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=f'--remote-debugging-port={debug_port}'
    env['WEBVIEW2_USER_DATA_FOLDER']=str(profile)
    report={'exe':str(args.exe.resolve()),'debugPort':debug_port,'profile':str(profile),'passed':False}
    process=subprocess.Popen([str(args.exe)],cwd=args.exe.parent,env=env)
    report['pid']=process.pid
    hwnd=None;backend_port=None;failure=None
    try:
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError(f'WPF exited during startup: {process.returncode}')
            hwnd=own_window(user,process.pid)
            if hwnd and port_open(debug_port):break
            time.sleep(.2)
        else:raise RuntimeError('Own WPF window / WebView2 CDP startup timed out')
        with sync_playwright() as playwright:
            browser=playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}',timeout=30000)
            page=None
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                page=next((p for context in browser.contexts for p in context.pages
                           if urlsplit(p.url).hostname=='127.0.0.1'),None)
                if page:break
                time.sleep(.2)
            if page is None:raise RuntimeError('No local simulator WebView page')
            backend_port=urlsplit(page.url).port;report['backendUrl']=page.url
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            expect(page.locator('#demo-button')).to_be_enabled()
            report['initialBounds']=measure(user,hwnd)
            assert report['initialBounds']['fullyInsideWorkArea'],report['initialBounds']
            page.locator('#demo-button').click()
            page.locator('#run-button').click()
            expect(page.locator('#terminal')).to_contain_text('OLED READY',timeout=30000)
            expect(page.locator('#terminal')).to_contain_text('FLASH JEDEC C84013',timeout=30000)
            page.wait_for_function("() => document.querySelector('#oled-live').classList.contains('on')")
            with urlopen(f'http://127.0.0.1:{backend_port}/api/state',timeout=3) as response:state=json.load(response)
            assert state['status']!='faulted',state['diagnostics']
            assert sum(state['oled']['pixels'])>300
            report['firmware']={'oledPixelsOn':sum(state['oled']['pixels']),'adc':state['adc'],'flash':state['flash'],
                                'jedecReply':next(log['text'] for log in state['serial'] if 'FLASH JEDEC C84013' in log['text'])}
            report['browser']=page.evaluate('({width:innerWidth,height:innerHeight,devicePixelRatio,scrollWidth:document.documentElement.scrollWidth})')
            assert report['browser']['scrollWidth']<=report['browser']['width']+1,report['browser']
            report['finalBounds']=measure(user,hwnd)
            assert report['finalBounds']['fullyInsideWorkArea'],report['finalBounds']
            page.screenshot(path=str(args.output)+'-content.png')
            capture_native_window(user,hwnd,Path(str(args.output)+'.png'))
            expect(page.locator('#wire-layer .fixed-board-wire')).to_have_count(4)
            page.locator('#schematic-button').click()
            expect(page.locator('#schematic-dialog')).to_be_visible()
            page.locator('#schematic-page-select').select_option('2')
            page.wait_for_function("() => document.querySelector('#schematic-image').complete && document.querySelector('#schematic-image').naturalWidth === 3200")
            expect(page.locator('#schematic-image')).to_be_visible()
            page.screenshot(path=str(args.output)+'-schematic.png')
            page.keyboard.press('Escape')
            expect(page.locator('#schematic-dialog')).not_to_be_visible()
            expect(page.locator('#schematic-button')).to_be_focused()
            report['schematicReader']=True
            report['pageErrors']=errors
            assert not errors,errors
            # WM_CLOSE must trigger WPF's own StopEngine cleanup, not browser.close().
            if not user.PostMessageW(hwnd,0x0010,0,0):raise C.WinError(C.get_last_error())
            process.wait(timeout=15)
            report['exitCode']=process.returncode
            assert process.returncode==0,process.returncode
        deadline=time.monotonic()+10
        while port_open(backend_port) and time.monotonic()<deadline:time.sleep(.2)
        report['backendStopped']=not port_open(backend_port)
        assert report['backendStopped'],'Own backend port remained listening after WPF close'
        report['passed']=True
    except BaseException as error:
        failure=error;report['error']=repr(error)
    finally:
        if process.poll() is None:
            hwnd=own_window(user,process.pid)
            if hwnd:user.PostMessageW(hwnd,0x0010,0,0)
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                # Restricted to the process tree created above, never by image name.
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                process.wait(timeout=8)
        report['cleanupExitCode']=process.returncode
        Path(str(args.output)+'.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if failure:raise failure
    print('PASS: WPF fits work area + WebView2 demo/OLED/JEDEC + original schematic reader + own backend stops on close')
    print(json.dumps({'bounds':report['finalBounds'],'browser':report['browser'],'report':str(args.output)+'.json'},ensure_ascii=False))


if __name__=='__main__':main()
