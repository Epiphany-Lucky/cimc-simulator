"""Read-only, bounded update checks against CIMC Studio's public releases."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


RELEASES_API = "https://api.github.com/repos/Epiphany-Lucky/cimc-simulator/releases?per_page=100"
REPOSITORY_PATH = "/Epiphany-Lucky/cimc-simulator/releases/"
REQUEST_TIMEOUT = 5
CACHE_SECONDS = 600
FORCE_INTERVAL_SECONDS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
ASSET_NAMES = {
    "windowsInstaller": "CIMC-Studio-{version}-Setup-x64.exe",
    "linuxDeb": "cimc-studio_{version}_amd64.deb",
    "linuxPortable": "CIMC-Studio-{version}-linux-x64.tar.gz",
    "html": "CIMC-Studio-{version}-html-local.zip",
}
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


def _version(value, *, tag=False):
    """Return a SemVer precedence key and version; build metadata is ignored."""
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError("Invalid semantic version")
    if tag and value.startswith("v"):
        value = value[1:]
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise ValueError("Invalid semantic version")
    major, minor, patch, prerelease, _build = match.groups()
    identifiers = []
    for identifier in prerelease.split(".") if prerelease else ():
        if identifier.isdigit():
            if len(identifier) > 1 and identifier.startswith("0"):
                raise ValueError("Invalid numeric prerelease identifier")
            identifiers.append((0, int(identifier)))
        else:
            identifiers.append((1, identifier))
    return (int(major), int(minor), int(patch), int(prerelease is None), tuple(identifiers)), value


def _official_url(value, expected_path):
    if not isinstance(value, str) or len(value) > 1024:
        return None
    if any(ord(character) <= 32 or ord(character) == 127 for character in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment or unquote(parsed.path) != expected_path):
        return None
    return value


def _published_at(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if timestamp.tzinfo is not None else None


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value[:limit]
                   if character in "\n\t" or ord(character) >= 32 and ord(character) != 127)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        # A repository rename must be reviewed in source, not followed silently.
        return None


class UpdateChecker:
    """Cached metadata only; never downloads or executes an update installer.

    ``opener`` follows urllib's ``open(request, timeout=...)`` interface.
    ``clock`` is a monotonic seconds callable. Both are injectable for offline tests.
    """

    def __init__(self, current_version, *, opener=None, clock=None):
        self._current_key, self.current_version = _version(current_version)
        self._opener = opener if opener is not None else build_opener(_NoRedirect()).open
        self._clock = clock if clock is not None else monotonic
        self._lock = Lock()
        self._cached = None
        self._cached_at = 0.0

    def check(self, force=False):
        with self._lock:
            interval = FORCE_INTERVAL_SECONDS if force else CACHE_SECONDS
            if self._cached is not None and self._clock() - self._cached_at < interval:
                return deepcopy(self._cached)
            result = self._check()
            self._cached = result
            self._cached_at = self._clock()
            return deepcopy(result)

    def _base_result(self):
        return {
            "status": "ok", "message": "尚未发现可下载的公开版本。", "errorCode": None,
            "currentVersion": self.current_version, "latestVersion": None,
            "available": False, "releaseUrl": None, "publishedAt": None,
            "releaseTitle": "", "releaseNotes": "", "prerelease": False,
            "assets": {kind: None for kind in ASSET_NAMES},
            "assetDetails": {}, "checksumsUrl": None,
            "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _check(self):
        result = self._base_result()
        request = Request(RELEASES_API, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "CIMC-Studio/" + self.current_version,
        })
        try:
            with self._opener(request, timeout=REQUEST_TIMEOUT) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError("Release response too large")
            releases = json.loads(payload)
            if not isinstance(releases, list):
                raise ValueError("Invalid release response")
            candidates = []
            for release in releases[:100]:
                candidate = self._candidate(release)
                if candidate is not None:
                    candidates.append(candidate)
            if candidates:
                version_key, metadata = max(candidates, key=lambda item: item[0])
                result.update(metadata)
                result["available"] = version_key > self._current_key
                result["message"] = ("发现新版本，可前往 GitHub 下载。" if result["available"]
                                     else "当前已是最新版本。")
        except HTTPError as error:
            if error.code == 404:
                self._error(result, "not_found", "更新服务暂不可用，公开版本可能尚未发布。")
            elif error.code in (403, 429):
                self._error(result, "rate_limited", "GitHub 暂时限制了更新检查，请稍后重试。")
            else:
                self._error(result, "service_unavailable", "更新服务暂不可用，请稍后重试。")
            error.close()
        except (URLError, OSError, TimeoutError):
            self._error(result, "offline", "无法连接更新服务，请检查网络后重试。")
        except (ValueError, UnicodeError, RecursionError):
            self._error(result, "invalid_response", "更新信息暂时无法读取，请稍后重试。")
        return result

    @staticmethod
    def _error(result, code, message):
        result.update(status="error", errorCode=code, message=message)

    @staticmethod
    def _candidate(release):
        if not isinstance(release, dict) or release.get("draft") is not False:
            return None
        tag = release.get("tag_name")
        try:
            version_key, version = _version(tag, tag=True)
        except ValueError:
            return None
        release_url = _official_url(release.get("html_url"), REPOSITORY_PATH + "tag/" + tag)
        published_at = _published_at(release.get("published_at"))
        raw_assets = release.get("assets")
        if release_url is None or published_at is None or not isinstance(raw_assets, list):
            return None
        assets = {kind: None for kind in ASSET_NAMES}
        details = {}
        checksums_url = None
        expected_names = {pattern.format(version=version): kind for kind, pattern in ASSET_NAMES.items()}
        for asset in raw_assets[:100]:
            if not isinstance(asset, dict) or asset.get("state") != "uploaded":
                continue
            name = asset.get("name")
            if name == f"SHA256SUMS-{version}.txt":
                checksums_url = _official_url(asset.get("browser_download_url"),
                    REPOSITORY_PATH + "download/" + tag + "/" + name)
            if not isinstance(name, str) or name not in expected_names:
                continue
            size = asset.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                continue
            url = _official_url(asset.get("browser_download_url"),
                                REPOSITORY_PATH + "download/" + tag + "/" + name)
            if url is not None:
                kind = expected_names[name]
                assets[kind] = url
                digest = asset.get("digest")
                details[kind] = {"name": name, "url": url, "size": size,
                    "sha256": digest[7:] if isinstance(digest, str) and
                    re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) else None}
        if not any(assets.values()):
            return None
        return version_key, {
            "latestVersion": version, "releaseUrl": release_url, "publishedAt": published_at,
            "releaseTitle": _text(release.get("name"), 160),
            "releaseNotes": _text(release.get("body"), 2000),
            "prerelease": release.get("prerelease") is True or version_key[3] == 0,
            "assets": assets,
            "assetDetails": details, "checksumsUrl": checksums_url,
        }
