"""Linux desktop ownership and browser launch, independent of the MCU model.

The lock file remains in place: unlinking a flock'ed file permits split ownership.
Only the owning process may remove its instance record. Nothing kills arbitrary PIDs.
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

APP_ID = 'cimc-studio'


def browser_environment(environ=None):
    env = dict(os.environ if environ is None else environ)
    original = env.pop('LD_LIBRARY_PATH_ORIG', None)
    if original is None:
        env.pop('LD_LIBRARY_PATH', None)
    else:
        env['LD_LIBRARY_PATH'] = original
    return env


def open_browser(url):
    """Use the user's system opener without inheriting frozen library overrides."""
    opener = shutil.which('xdg-open')
    command = [opener, url] if opener else None
    if command is None:
        opener = shutil.which('gio')
        if opener:
            command = [opener, 'open', url]
    if command is None:
        raise RuntimeError('No desktop URL opener. Install xdg-utils and a graphical web browser.')
    process = subprocess.Popen(command, env=browser_environment(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        code = process.wait(timeout=3)
        if code:
            raise RuntimeError(f'Default browser could not open the workbench (exit {code}).')
    except subprocess.TimeoutExpired:
        # Some desktop openers stay attached to the browser. Do not terminate it.
        pass


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError(f'Unsafe desktop session directory (requires owner-only 0700): {path}')
    return path


def runtime_directory():
    runtime = os.environ.get('XDG_RUNTIME_DIR', '')
    if runtime and Path(runtime).is_absolute() and Path(runtime).is_dir():
        # Validate the containing runtime directory too; never accept a public path.
        _private_directory(Path(runtime))
        return _private_directory(Path(runtime) / APP_ID)
    cache = os.environ.get('XDG_CACHE_HOME', '')
    base = Path(cache) if cache and Path(cache).is_absolute() else Path.home() / '.cache'
    return _private_directory(base / APP_ID / 'runtime')


class DesktopSession:
    def __init__(self, directory=None, idle_seconds=180):
        if not 1 <= idle_seconds <= 86400:
            raise ValueError('Desktop idle timeout must be between 1 and 86400 seconds')
        self.directory = _private_directory(Path(directory)) if directory is not None else runtime_directory()
        self.record_path = self.directory / 'session.json'
        self.instance_id = secrets.token_urlsafe(32)
        self.idle_seconds = idle_seconds
        self.last_activity = time.monotonic()
        self.activity_lock = threading.Lock()
        self.lock_fd = None
        self.owner = False

    def acquire(self):
        import fcntl
        fd = os.open(self.directory / 'session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            os.close(fd)
            raise RuntimeError('Unsafe desktop lock file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self.lock_fd = fd
        self.owner = True
        return True

    def _read_record(self):
        try:
            fd = os.open(self.record_path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                info = os.fstat(stream.fileno())
                if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                    return None
                record = json.loads(stream.read(4096))
            url = urlsplit(record['url'])
            if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.path not in ('', '/'):
                return None
            if not isinstance(record['instanceId'], str) or len(record['instanceId']) < 32:
                return None
            return record
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def existing_url(self, timeout=8):
        end = time.monotonic() + timeout
        opener = build_opener(ProxyHandler({}))
        while time.monotonic() < end:
            record = self._read_record()
            if record:
                try:
                    with opener.open(record['url'].rstrip('/') + '/api/health', timeout=1) as response:
                        health = json.load(response)
                    if health.get('app') == APP_ID and health.get('desktopSession') is True and health.get('instanceId') == record['instanceId']:
                        return record['url']
                except (OSError, ValueError):
                    pass
            time.sleep(.1)
        raise RuntimeError('Another desktop instance owns the lock but is not responding. Retry after it exits.')

    def publish(self, url):
        if not self.owner:
            raise RuntimeError('Only the desktop session owner can publish a session')
        temporary = self.directory / ('session-' + secrets.token_hex(8) + '.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'url': url, 'instanceId': self.instance_id, 'pid': os.getpid()}, stream)
            os.replace(temporary, self.record_path)
        finally:
            temporary.unlink(missing_ok=True)
        self.touch()

    def touch(self):
        with self.activity_lock:
            self.last_activity = time.monotonic()

    def expired(self):
        with self.activity_lock:
            return time.monotonic() - self.last_activity >= self.idle_seconds

    def authorized(self, supplied):
        return isinstance(supplied, str) and hmac.compare_digest(self.instance_id, supplied)

    def log(self, message):
        # Runtime logs contain lifecycle events only, never firmware or user payloads.
        try:
            fd = os.open(self.directory / 'desktop.log', os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as stream:
                stream.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')
        except OSError:
            pass

    def close(self):
        if self.owner:
            record = self._read_record()
            if record and record.get('instanceId') == self.instance_id:
                self.record_path.unlink(missing_ok=True)
            self.owner = False
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
