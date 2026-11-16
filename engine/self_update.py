"""User-initiated, verified downloads and out-of-process installer handoff."""
from copy import deepcopy
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from threading import Lock, Thread
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from desktop_session import browser_environment

MAX_INSTALLER_BYTES = 512 * 1024 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024
UPDATE_EXIT_MARKER = 'CIMC_UPDATE_EXIT:'


class _AssetRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        parsed = urlsplit(new_url)
        if (parsed.scheme != 'https' or parsed.netloc not in
                {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}):
            raise ValueError('更新下载重定向地址无效。')
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _cache_root():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'CIMCStudio' / 'Updates'
    configured = os.environ.get('XDG_CACHE_HOME', '')
    base = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / '.cache'
    return base / 'cimc-studio' / 'updates'


def _windows_destination(root):
    """Keep a registered installation's actual location, including custom drives."""
    try:
        import winreg
        key_name = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\CIMCStudio.User_is1'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
            installed = Path(winreg.QueryValueEx(key, 'InstallLocation')[0]).resolve()
        if installed == root:
            return installed
    except (ImportError, OSError, ValueError):
        pass
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Programs' / 'CIMC Studio'


def _file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class SelfUpdater:
    def __init__(self, checker, root, *, opener=None, cache_root=None, platform=None, launcher=None):
        self.checker = checker
        self.root = Path(root).resolve()
        self.platform = platform or sys.platform
        self.opener = opener or build_opener(_AssetRedirect()).open
        self.launcher = launcher or subprocess.Popen
        self.cache_root = Path(cache_root) if cache_root is not None else _cache_root()
        self.token = secrets.token_urlsafe(32)
        self.lock = Lock()
        self.thread = None
        self.download = None
        self.digest = None
        self.destination = _windows_destination(self.root) if self.platform == 'win32' else self.root
        if self.platform == 'win32':
            self.mode, self.kind, self.can_install = 'windowsInstaller', 'windowsInstaller', True
            message = f'下载并校验后，安装到 {self.destination} 并重新启动。'
        elif self.root == Path('/opt/cimc-studio').resolve():
            self.mode, self.kind = 'linuxDeb', 'linuxDeb'
            self.can_install = bool(shutil.which('pkexec') and shutil.which('dpkg'))
            message = '下载并校验后，由系统授权安装 DEB 并重新启动。' if self.can_install else '下载校验 DEB 后，请使用系统软件安装器安装。'
        else:
            self.mode, self.kind, self.can_install = 'linuxPortable', 'linuxPortable', False
            message = '下载校验便携包后，打开所在文件夹，解压新版并运行 cimc-studio。'
        self.info = {'token': self.token, 'mode': self.mode, 'canInstall': self.can_install, 'message': message}
        self._state = {'status': 'idle', 'version': None, 'receivedBytes': 0, 'totalBytes': 0,
                       'percent': 0, 'message': message, 'errorCode': None, 'filePath': None,
                       'willExit': False, **self.info}

    def authorized(self, token):
        return isinstance(token, str) and hmac.compare_digest(token, self.token)

    def state(self):
        with self.lock:
            return deepcopy(self._state)

    def start(self, version):
        with self.lock:
            if self._state['status'] in ('downloading', 'installing'):
                return deepcopy(self._state)
            if self._state['status'] == 'ready' and self._state['version'] == version:
                return deepcopy(self._state)
            result = self.checker.check()
            if result['status'] != 'ok' or not result['available'] or result['latestVersion'] != version:
                raise ValueError('此版本尚未发布或更新信息已变化，请重新检查更新。')
            asset = result.get('assetDetails', {}).get(self.kind)
            if not asset or not 0 < asset['size'] <= MAX_INSTALLER_BYTES:
                raise ValueError('没有适用于本系统的有效更新文件。')
            if not asset.get('sha256') and not result.get('checksumsUrl'):
                raise ValueError('发行版缺少 SHA-256 校验信息，请联系维护者。')
            self._state.update(status='downloading', version=version, receivedBytes=0,
                               totalBytes=asset['size'], percent=0, filePath=None,
                               message='正在下载并校验更新…', errorCode=None, willExit=False)
            self.download = None
            self.digest = None
            self.thread = Thread(target=self._download, args=(asset, result.get('checksumsUrl')), daemon=True)
            self.thread.start()
            return deepcopy(self._state)

    def _open(self, url):
        return self.opener(Request(url, headers={'User-Agent': 'CIMC-Studio-Updater',
                                                'Accept': 'application/octet-stream'}), timeout=20)

    def _expected_digest(self, asset, checksums_url):
        if asset.get('sha256'):
            return asset['sha256'].lower()
        with self._open(checksums_url) as response:
            data = response.read(MAX_CHECKSUM_BYTES + 1)
        if len(data) > MAX_CHECKSUM_BYTES:
            raise ValueError('更新校验清单超过大小限制。')
        records = {}
        for line in data.decode('ascii').splitlines():
            match = re.fullmatch(r'([0-9a-fA-F]{64})  ([A-Za-z0-9_.+-]+)', line)
            if match is None or match[2] in records:
                raise ValueError('更新校验清单无效。')
            records[match[2]] = match[1].lower()
        if asset['name'] not in records:
            raise ValueError('更新文件缺少 SHA-256 校验记录。')
        return records[asset['name']]

    def _download(self, asset, checksums_url):
        directory = None
        temporary = None
        try:
            expected = self._expected_digest(asset, checksums_url)
            self.cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory = Path(tempfile.mkdtemp(prefix='download-', dir=self.cache_root))
            final = directory / asset['name']
            temporary = final.with_suffix(final.suffix + '.part')
            digest = hashlib.sha256()
            received = 0
            started = monotonic()
            with self._open(asset['url']) as response, temporary.open('xb') as stream:
                os.chmod(temporary, 0o600)
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > asset['size'] or monotonic() - started > 1800:
                        raise ValueError('更新文件长度或下载时间超出限制。')
                    stream.write(chunk)
                    digest.update(chunk)
                    with self.lock:
                        self._state.update(receivedBytes=received,
                                           percent=min(99, received * 100 // asset['size']))
                stream.flush()
                os.fsync(stream.fileno())
            if received != asset['size'] or not hmac.compare_digest(digest.hexdigest(), expected):
                raise ValueError('更新文件未通过长度或 SHA-256 校验，请重新下载。')
            temporary.replace(final)
            with self.lock:
                self.download, self.digest = final, expected
                self._state.update(status='ready', percent=100, filePath=str(final),
                                   message='下载和 SHA-256 校验完成。请先保存工程，再安装更新。')
        except Exception as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if directory is not None:
                try:
                    directory.rmdir()
                except OSError:
                    pass
            with self.lock:
                self._state.update(status='error', errorCode='download_failed', message=str(error))

    def install(self):
        with self.lock:
            if self._state['status'] == 'installing':
                return deepcopy(self._state)
            if self._state['status'] != 'ready' or not self.download or not self.can_install:
                raise ValueError('请先下载并校验适用于本系统的安装包。')
            try:
                digest = _file_digest(self.download)
            except OSError:
                self._state.update(status='error', errorCode='installer_missing', message='安装包无法读取，请重新下载。')
                raise ValueError(self._state['message']) from None
            if not hmac.compare_digest(digest, self.digest):
                self._state.update(status='error', errorCode='checksum_mismatch', message='安装包校验失败，请重新下载。')
                raise ValueError(self._state['message'])
            command = self._installer_command()
            options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
                       'env': browser_environment(), 'cwd': str(self.download.parent)}
            if self.platform == 'win32':
                options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            else:
                options['start_new_session'] = True
            self.launcher(command, **options)
            self._state.update(status='installing', willExit=True,
                               message='应用正在退出，随后安装更新并重新启动。安装日志保存在下载文件夹。')
            return deepcopy(self._state)

    def open_folder(self):
        with self.lock:
            if self._state['status'] != 'ready' or not self.download:
                raise ValueError('更新文件尚未准备好。')
            folder = str(self.download.parent)
        if self.platform == 'win32':
            os.startfile(folder)
        else:
            from desktop_session import open_browser
            open_browser(Path(folder).as_uri())
        return self.state()

    def _installer_command(self):
        if self.platform == 'win32':
            helper = self.download.parent / 'install-update.ps1'
            helper.write_text(_WINDOWS_HELPER, encoding='utf-8-sig')
            shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            return [str(shell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
                    '-Installer', str(self.download), '-ExpectedDigest', self.digest,
                    '-InstallDirectory', str(self.destination), '-EngineProcessId', str(os.getpid()),
                    '-DesktopProcessId', str(int(os.environ.get('CIMC_DESKTOP_PID', '0')))]
        helper = self.download.parent / 'install-update.sh'
        helper.write_text(_LINUX_HELPER, encoding='utf-8')
        helper.chmod(0o700)
        return ['/bin/sh', str(helper), str(os.getpid()), str(self.download), self.digest,
                shutil.which('pkexec'), shutil.which('dpkg')]


_WINDOWS_HELPER = r'''param(
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

_LINUX_HELPER = r'''#!/bin/sh
set -eu
engine_id=$1
installer=$2
expected=$3
pkexec=$4
dpkg=$5
directory=$(dirname -- "$installer")
exec >> "$directory/update-helper.log" 2>&1
attempts=0
while kill -0 "$engine_id" 2>/dev/null; do
    attempts=$((attempts + 1))
    [ "$attempts" -le 120 ] || { echo 'Application did not exit.'; exit 1; }
    sleep 1
done
printf '%s  %s\n' "$expected" "$installer" | sha256sum --check --status
if "$pkexec" "$dpkg" -i "$installer"; then
    echo 'Installation completed successfully.'
    /usr/bin/cimc-studio >/dev/null 2>&1 &
else
    echo 'System authorization or installation failed. Reopen CIMC Studio and retry.'
    if command -v xdg-open >/dev/null 2>&1; then xdg-open "$directory" >/dev/null 2>&1 & fi
    exit 1
fi
'''
