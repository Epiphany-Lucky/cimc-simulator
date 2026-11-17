"""Real onefile parent -> legacy updater -> isolated installer -> restarted WPF.

Run with a complete frozen Windows package and its version. A unique TestId keeps
the installation separate. The old onefile probe occupies the exact engine path
that the installer replaces, and its temporary extraction directory must disappear
before the restarted application's own health endpoint can pass acceptance.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
import uuid

from playwright.sync_api import expect, sync_playwright

from desktop_smoke import capture_native_window, measure, native_api, own_window, port_open
from windows_installer_smoke import registry_entry, run

ROOT = Path(__file__).resolve().parents[1]

# Exact 0.5.1 helper, SHA-256 6487a83b795941c112217d349d6062f29f43ad6b9af8d83e2a27ccb474785987.
# Keep the legacy environment inheritance here to exercise old clients upgrading.
LEGACY_HELPER = r'''param(
    [string]$Installer, [string]$ExpectedDigest, [string]$InstallDirectory,
    [int]$EngineProcessId, [int]$DesktopProcessId
)
$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'update-helper.log'
try {
    foreach ($processId in @($EngineProcessId, $DesktopProcessId)) {
        if ($processId -le 0) { continue }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process -and -not $process.WaitForExit(120000)) { throw 'Application did not exit. Retry after saving and closing it.' }
    }
    $stream = [System.IO.File]::OpenRead($Installer)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try { $actualDigest = [System.BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $sha256.Dispose() }
    if ($actualDigest -ne $ExpectedDigest) { throw 'Installer SHA-256 changed.' }
    $setupLog = Join-Path $PSScriptRoot 'installer.log'
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', ('/DIR="' + $InstallDirectory + '"'), ('/LOG="' + $setupLog + '"'))
    $installed = Start-Process -FilePath $Installer -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($installed.ExitCode -ne 0) { throw ('Installer exit code ' + $installed.ExitCode) }
    Add-Content -LiteralPath $log -Value 'Installation completed successfully.'
    Start-Process -FilePath (Join-Path $InstallDirectory 'CIMC-Studio.exe') -WorkingDirectory $InstallDirectory -WindowStyle Hidden
} catch {
    $_ | Out-String | Set-Content -LiteralPath $log -Encoding UTF8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(('CIMC Studio update failed. See ' + $log), 'CIMC Studio') | Out-Null
    exit 1
}
'''

PROBE_SOURCE = r'''import json, os, subprocess, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
assert getattr(sys, 'frozen', False)
assert 'PYINSTALLER_RESET_ENVIRONMENT' not in os.environ
assert Path(os.environ['_PYI_ARCHIVE_FILE']).resolve() == Path(sys.executable).resolve()
environment = dict(os.environ)
original = environment.pop('LD_LIBRARY_PATH_ORIG', None)
if original is None:
    environment.pop('LD_LIBRARY_PATH', None)
else:
    environment['LD_LIBRARY_PATH'] = original
arguments = [request['powershell'], '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', request['helper'], '-Installer', request['installer'],
             '-ExpectedDigest', request['installerSha256'], '-InstallDirectory', request['installDirectory'],
             '-EngineProcessId', str(os.getpid()), '-DesktopProcessId', '0']
helper = subprocess.Popen(arguments, env=environment, cwd=str(Path(request['helper']).parent),
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NO_WINDOW)
witness = {'frozen': True, 'enginePid': os.getpid(), 'helperPid': helper.pid,
           'executable': sys.executable, 'extractionDirectory': sys._MEIPASS,
           'environment': {name: os.environ.get(name) for name in
                           ('_PYI_ARCHIVE_FILE', '_PYI_APPLICATION_HOME_DIR', '_PYI_PARENT_PROCESS_LEVEL',
                            'PYINSTALLER_RESET_ENVIRONMENT')}}
Path(request['witness']).write_text(json.dumps(witness, indent=2), encoding='utf-8')
'''


def own_desktops(executable, shell):
    environment = dict(os.environ, CIMC_TEST_RESTART_EXE=str(executable))
    script = ("[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
              "$owned = @(Get-CimInstance Win32_Process -Filter \"Name='CIMC-Studio.exe'\" | "
              "Where-Object { $_.ExecutablePath -eq $env:CIMC_TEST_RESTART_EXE } | "
              "Select-Object ProcessId, ParentProcessId, ExecutablePath); "
              "ConvertTo-Json -InputObject $owned -Compress")
    completed = subprocess.run([shell, '-NoProfile', '-Command', script], env=environment,
                               capture_output=True, encoding='utf-8', check=True, timeout=15,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(completed.stdout)


def window_text(user, hwnd):
    captions = []

    def record(handle):
        value = ctypes.create_unicode_buffer(8192)
        user.GetWindowTextW(handle, value, len(value))
        if value.value:
            captions.append(value.value)

    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def visit(handle, unused):
        record(handle)
        return 1

    record(hwnd)
    user.EnumChildWindows.argtypes = [ctypes.c_void_p, callback_type, ctypes.c_void_p]
    user.EnumChildWindows.restype = ctypes.c_int
    user.EnumChildWindows(hwnd, visit, None)
    return '\n'.join(captions)


def close_desktops(executable, shell, user):
    for process in own_desktops(executable, shell):
        hwnd = own_window(user, process['ProcessId'])
        if hwnd:
            user.PostMessageW(hwnd, 0x0010, 0, 0)
    deadline = time.monotonic() + 8
    while own_desktops(executable, shell) and time.monotonic() < deadline:
        time.sleep(.2)
    for process in own_desktops(executable, shell):
        # The queried executable must still be this test's exact installation path.
        subprocess.run(['taskkill', '/PID', str(process['ProcessId']), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def close_helper(witness, helper, shell):
    if not witness.is_file():
        return
    process_id = json.loads(witness.read_text(encoding='utf-8'))['helperPid']
    environment = dict(os.environ, CIMC_TEST_HELPER_PID=str(int(process_id)), CIMC_TEST_HELPER_PATH=str(helper))
    script = ("$candidate = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:CIMC_TEST_HELPER_PID); "
              "if ($candidate.Name -eq 'powershell.exe' -and $candidate.CommandLine -and "
              "$candidate.CommandLine.Contains($env:CIMC_TEST_HELPER_PATH)) { "
              "& taskkill.exe /PID $candidate.ProcessId /T /F | Out-Null }")
    subprocess.run([shell, '-NoProfile', '-Command', script], env=environment,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--version', required=True)
    arguments = parser.parse_args()
    if os.name != 'nt':
        parser.error('This acceptance requires Windows and an interactive WebView2 desktop')
    package = arguments.package.resolve(strict=True)
    for name in ('CIMC-Studio.exe', 'CIMC-Engine.exe', 'web/index.html'):
        if not (package / name).is_file():
            parser.error('Pass a complete frozen Windows release directory')
    # Keep WPF's first-free-port selection away from8765 on a clean test host.
    # If an existing service owns it, leave that service untouched.
    production_reservation = socket.socket()
    try:
        production_reservation.bind(('127.0.0.1', 8765))
    except OSError:
        production_reservation.close()
        production_reservation = None
    shell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    build_shell = shutil.which('pwsh') or shell
    identity = uuid.uuid4().hex[:12]
    test_root = (ROOT / 'artifacts' / f'update-restart-smoke-{identity}').resolve()
    assert test_root.is_relative_to((ROOT / 'artifacts').resolve())
    test_root.mkdir()
    installed = test_root / 'application'
    installed.mkdir()
    executable = installed / 'CIMC-Studio.exe'
    engine = installed / 'CIMC-Engine.exe'
    registry_key = rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\CIMCStudio.InstallerTest.{identity}_is1'
    production_key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\CIMCStudio.User_is1'
    assert registry_entry(registry_key) is None
    production_before = registry_entry(production_key)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        debug_port = listener.getsockname()[1]
    report_path = test_root / 'result.json'
    helper = test_root / 'install-update.ps1'
    witness = test_root / 'old-frozen-environment.json'
    report = {'passed': False, 'testId': identity, 'package': str(package), 'version': arguments.version,
              'installDirectory': str(installed), 'startedAtUtc': datetime.now(timezone.utc).isoformat(),
              'method': 'Real onefile probe at the replaced engine path and unchanged 0.5.1 installer helper',
              'legacyHelperSha256': hashlib.sha256(LEGACY_HELPER.encode()).hexdigest(),
              'packageSha256': {name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                                for name in ('CIMC-Studio.exe', 'CIMC-Engine.exe')}}
    assert report['legacyHelperSha256'] == '6487a83b795941c112217d349d6062f29f43ad6b9af8d83e2a27ccb474785987'
    user = native_api()
    parent = None
    try:
        probe = test_root / 'frozen_restart_parent.py'
        probe.write_text(PROBE_SOURCE, encoding='utf-8')
        output = run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                      '--name', 'CIMC-Engine', '--distpath', test_root / 'probe-dist',
                      '--workpath', test_root / 'probe-build', '--specpath', test_root / 'probe-spec', probe], timeout=180)
        (test_root / 'probe-build.log').write_text(output, encoding='utf-8')
        shutil.copyfile(test_root / 'probe-dist/CIMC-Engine.exe', engine)
        report['oldProbeSha256'] = hashlib.sha256(engine.read_bytes()).hexdigest()
        output = run([build_shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                      ROOT / 'scripts/build-windows-installer.ps1', '-Version', arguments.version,
                      '-PackageDirectory', package, '-OutputDirectory', test_root, '-TestId', identity], timeout=600)
        (test_root / 'installer-build.log').write_text(output, encoding='utf-8')
        setup = test_root / f'CIMC-Studio-{arguments.version}-Test-{identity}-Setup-x64.exe'
        helper.write_text(LEGACY_HELPER, encoding='utf-8-sig')
        request = {'powershell': shell, 'helper': str(helper), 'installer': str(setup),
                   'installerSha256': hashlib.sha256(setup.read_bytes()).hexdigest(),
                   'installDirectory': str(installed), 'witness': str(witness)}
        request_path = test_root / 'request.json'
        request_path.write_text(json.dumps(request), encoding='utf-8')
        sentinel = installed / 'my-exported-wiring.json'
        sentinel.write_text('{"keep":"exported user project"}', encoding='utf-8')
        environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1',
                           WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={debug_port}',
                           WEBVIEW2_USER_DATA_FOLDER=str(test_root / 'webview-profile'),
                           CIMC_CONFIG_DIRECTORY=str(test_root / 'preferences'))
        environment.pop('PSModulePath', None)  # Let Windows PowerShell initialize its own module search path.
        parent = subprocess.Popen([str(engine), str(request_path)], cwd=installed, env=environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        stdout, stderr = parent.communicate(timeout=45)
        report.update(oldProbeExitCode=parent.returncode, oldProbeStdout=stdout.decode('utf-8', errors='replace'),
                      oldProbeStderr=stderr.decode('utf-8', errors='replace'))
        assert parent.returncode == 0, report['oldProbeStderr']
        report['oldFrozen'] = json.loads(witness.read_text(encoding='utf-8'))
        old_directory = Path(report['oldFrozen']['extractionDirectory'])
        assert not old_directory.exists(), 'Old onefile extraction directory survived parent exit'
        report['oldExtractionRemoved'] = True
        assert Path(report['oldFrozen']['executable']).resolve() == engine
        assert report['oldFrozen']['environment']['PYINSTALLER_RESET_ENVIRONMENT'] is None
        deadline = time.monotonic() + 180
        processes = []
        while time.monotonic() < deadline:
            processes = own_desktops(executable, build_shell)
            if processes:
                break
            time.sleep(.2)
        assert len(processes) == 1, 'Legacy helper did not restart the isolated WPF application'
        report['newDesktop'] = processes[0]
        deadline = time.monotonic() + 45
        while not port_open(debug_port) and time.monotonic() < deadline:
            hwnd = own_window(user, processes[0]['ProcessId'])
            if hwnd and '启动失败' in window_text(user, hwnd):
                break
            time.sleep(.2)
        hwnd = own_window(user, processes[0]['ProcessId'])
        if hwnd:
            report['restartWindowText'] = window_text(user, hwnd)
            capture_native_window(user, hwnd, test_root / 'restarted-desktop.png')
        assert port_open(debug_port), 'Restarted WPF did not initialize WebView2 after the old extraction directory was deleted'
        assert hwnd is not None, 'Restarted WPF has no visible native window'
        user.IsIconic.argtypes = [wintypes.HWND]
        user.IsIconic.restype = wintypes.BOOL
        user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetClientRect.restype = wintypes.BOOL
        client = wintypes.RECT()
        assert user.GetClientRect(hwnd, ctypes.byref(client))
        report['nativeWindow'] = {'visible': bool(user.IsWindowVisible(hwnd)),
                                  'minimized': bool(user.IsIconic(hwnd)),
                                  'clientWidth': client.right - client.left,
                                  'clientHeight': client.bottom - client.top,
                                  'bounds': measure(user, hwnd)}
        assert report['nativeWindow']['visible'] and not report['nativeWindow']['minimized']
        assert report['nativeWindow']['clientWidth'] > 100 and report['nativeWindow']['clientHeight'] > 100
        assert report['nativeWindow']['bounds']['fullyInsideWorkArea']
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}')
            deadline = time.monotonic() + 30
            page = None
            while time.monotonic() < deadline:
                page = next((page for context in browser.contexts for page in context.pages
                             if urlsplit(page.url).hostname == '127.0.0.1'), None)
                if page is not None:
                    break
                time.sleep(.2)
            assert page is not None, 'Restarted WPF did not navigate to its own local workbench'
            url = page.url.rstrip('/')
            assert urlsplit(url).port != 8765
            with urlopen(url + '/api/health', timeout=10) as response:
                report['newHealth'] = json.load(response)
            assert report['newHealth']['version'] == arguments.version
            report['newBackendUrl'] = url
            expect(page.locator('#demo-button')).to_be_enabled()
            page.screenshot(path=str(test_root / 'restarted-content.png'))
            capture_native_window(user, hwnd, test_root / 'restarted-desktop.png')
        report['registration'] = registry_entry(registry_key)
        assert report['registration']['DisplayVersion'] == arguments.version
        assert Path(report['registration']['InstallLocation']).resolve() == installed
        for name, digest in report['packageSha256'].items():
            assert hashlib.sha256((installed / name).read_bytes()).hexdigest() == digest
        assert sentinel.read_text(encoding='utf-8') == '{"keep":"exported user project"}'
        report['sameEnginePathReplaced'] = True
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if parent is not None and parent.poll() is None:
            subprocess.run(['taskkill', '/PID', str(parent.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            parent.wait(timeout=10)
        try:
            close_desktops(executable, build_shell, user)
            close_helper(witness, helper, build_shell)
            uninstaller = installed / 'unins000.exe'
            if uninstaller.is_file():
                assert uninstaller.resolve().is_relative_to(test_root)
                run([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                     f'/LOG={test_root / "uninstall.log"}'])
            report['testRegistrationRemoved'] = registry_entry(registry_key) is None
            report['productionRegistrationUnchanged'] = registry_entry(production_key) == production_before
            assert report['testRegistrationRemoved'] and report['productionRegistrationUnchanged']
        except Exception as error:
            report['cleanupError'] = repr(error)
            report['passed'] = False
        report['completedAtUtc'] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if production_reservation is not None:
            production_reservation.close()
        print(json.dumps({'passed': report['passed'], 'report': str(report_path)}), flush=True)
    assert report['passed'], report.get('cleanupError')


if __name__ == '__main__':
    main()
