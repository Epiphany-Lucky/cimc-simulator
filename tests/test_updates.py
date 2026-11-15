"""Offline update selection, trust boundary, failure handling and cache tests."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from updates import ASSET_NAMES, MAX_RESPONSE_BYTES, RELEASES_API, UpdateChecker


def release(version="0.4.0", **changes):
    tag = "v" + version
    prefix = "https://github.com/Epiphany-Lucky/cimc-simulator/releases/"
    value = {
        "tag_name": tag, "draft": False, "prerelease": "-" in version,
        "published_at": "2026-11-15T00:00:00Z", "html_url": prefix + "tag/" + tag,
        "name": "CIMC Studio " + version, "body": "更新说明\n纯仿真。", "assets": [],
    }
    for pattern in ASSET_NAMES.values():
        name = pattern.format(version=version)
        value["assets"].append({"name": name, "state": "uploaded", "size": 123,
                                "browser_download_url": prefix + "download/" + tag + "/" + name})
    value.update(changes)
    return value


class FakeOpener:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.value, Exception):
            raise self.value
        data = self.value if isinstance(self.value, bytes) else json.dumps(self.value).encode("utf-8")
        return io.BytesIO(data)


class UpdateSelectionTests(unittest.TestCase):
    def check(self, releases, current="0.3.0"):
        return UpdateChecker(current, opener=FakeOpener(releases)).check()

    def test_release_request_and_download_contract(self):
        opener = FakeOpener([release()])
        result = UpdateChecker("0.3.0", opener=opener).check()
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, RELEASES_API)
        self.assertEqual(timeout, 5)
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["currentVersion"], "0.3.0")
        self.assertEqual(result["latestVersion"], "0.4.0")
        self.assertTrue(result["available"])
        self.assertEqual(set(result["assets"]), set(ASSET_NAMES))
        self.assertTrue(all(result["assets"].values()))

    def test_numeric_precedence_is_not_lexical_or_release_list_order(self):
        result = self.check([release("0.9.0"), release("0.2.0"), release("0.10.0")])
        self.assertEqual(result["latestVersion"], "0.10.0")

    def test_prerelease_numeric_identifiers_and_stable_precedence(self):
        versions = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
                    "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        for earlier, later in zip(versions, versions[1:]):
            with self.subTest(earlier=earlier, later=later):
                result = self.check([release(earlier), release(later)], earlier)
                self.assertEqual(result["latestVersion"], later)
                self.assertTrue(result["available"])
        result = self.check([release("0.4.0-preview.10"), release("0.4.0-preview.2")])
        self.assertEqual(result["latestVersion"], "0.4.0-preview.10")
        self.assertTrue(result["prerelease"])

    def test_same_older_and_build_metadata_do_not_prompt_upgrade(self):
        for version in ("0.3.0", "0.2.9", "0.3.0+build.003", "0.3.0-rc.1"):
            with self.subTest(version=version):
                self.assertFalse(self.check([release(version)])["available"])

    def test_rejects_invalid_versions_and_non_downloadable_releases(self):
        bad_versions = ["01.0.0", "1.0", "1.0.0.1", "1.0.0-01", "1.0.0-a..b",
                        "1.0.0+", "1.0.0\n", "1.0.0_foo", "1.0.0-β", "9" * 129]
        candidates = [release(version) for version in bad_versions]
        candidates += [release("99.0.0", draft=True), release("99.1.0", published_at=None),
                       release("99.2.0", assets=[]), release("99.3.0", assets="bad"),
                       release("99.4.0", published_at="tomorrow"), None, []]
        candidates.append(release("0.4.0"))
        self.assertEqual(self.check(candidates)["latestVersion"], "0.4.0")
        for version in bad_versions + ["v0.3.0", None, 3]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                UpdateChecker(version, opener=FakeOpener([]))

    def test_non_v_tag_and_bounded_release_text(self):
        value = release()
        value["tag_name"] = "0.4.0"
        value["html_url"] = value["html_url"].replace("v0.4.0", "0.4.0")
        for asset in value["assets"]:
            asset["browser_download_url"] = asset["browser_download_url"].replace("v0.4.0", "0.4.0")
        value.update(name="a" * 1000, body="b" * 9000)
        result = self.check([value])
        self.assertEqual(result["latestVersion"], "0.4.0")
        self.assertEqual(len(result["releaseTitle"]), 160)
        self.assertEqual(len(result["releaseNotes"]), 2000)

    def test_unpublished_or_empty_list_has_friendly_non_update_state(self):
        result = self.check([])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["available"])
        self.assertIsNone(result["latestVersion"])
        self.assertTrue(result["message"])


class UpdateTrustBoundaryTests(unittest.TestCase):
    def test_rejects_untrusted_release_and_download_urls(self):
        original = release()
        page = original["html_url"]
        invalid_pages = [page.replace("https:", "http:"), page.replace("github.com", "github.com.evil.test"),
                         page.replace("github.com", "github.com@evil.test"),
                         page.replace("github.com", "evil@github.com"),
                         page.replace("github.com", "github.com:443"),
                         page.replace("Epiphany-Lucky", "other"), page + "?redirect=evil", page + "#fragment",
                         page.replace("tag/v0.4.0", "download/v0.4.0"),
                         page.replace("tag/v0.4.0", "tag/../v0.4.0"), "\n" + page,
                         "javascript:alert(1)", "https://[broken", 42]
        for url in invalid_pages:
            with self.subTest(url=url):
                value = deepcopy(original)
                value["html_url"] = url
                result = UpdateChecker("0.3.0", opener=FakeOpener([value])).check()
                self.assertIsNone(result["releaseUrl"])
                self.assertFalse(result["available"])
        asset = original["assets"][0]
        download = asset["browser_download_url"]
        for url in [download.replace("github.com", "evil.test"), download.replace("v0.4.0/", "v0.5.0/"),
                    download + "?token=secret", download.replace("/releases/", "/other/"),
                    download.replace("CIMC-Studio", "%252e%252e/CIMC-Studio")]:
            with self.subTest(url=url):
                value = deepcopy(original)
                value["assets"][0]["browser_download_url"] = url
                result = UpdateChecker("0.3.0", opener=FakeOpener([value])).check()
                self.assertIsNone(result["assets"]["windowsInstaller"])
                self.assertTrue(result["assets"]["linuxDeb"])

    def test_only_uploaded_positive_size_exact_version_assets_are_returned(self):
        for changes in ({"state": "new"}, {"size": 0}, {"size": True}, {"size": "123"},
                        {"name": "CIMC-Studio-99.0.0-Setup-x64.exe"}):
            with self.subTest(changes=changes):
                value = release()
                value["assets"] = [dict(value["assets"][0], **changes)]
                result = UpdateChecker("0.3.0", opener=FakeOpener([value])).check()
                self.assertFalse(result["available"])

    def test_encoded_build_metadata_urls_remain_official(self):
        value = release("0.4.0+build.1")
        value["html_url"] = value["html_url"].replace("+", "%2B")
        for asset in value["assets"]:
            asset["browser_download_url"] = asset["browser_download_url"].replace("+", "%2B")
        result = UpdateChecker("0.3.0", opener=FakeOpener([value])).check()
        self.assertTrue(result["available"])
        self.assertTrue(all(result["assets"].values()))


class UpdateFailureAndCacheTests(unittest.TestCase):
    def test_network_http_and_invalid_response_errors_are_structured(self):
        cases = [(URLError("private network details"), "offline"), (TimeoutError(), "offline"),
                 (HTTPError(RELEASES_API, 404, "Not Found", {}, None), "not_found"),
                 (HTTPError(RELEASES_API, 403, "Forbidden", {}, None), "rate_limited"),
                 (HTTPError(RELEASES_API, 429, "Limit", {}, None), "rate_limited"),
                 (HTTPError(RELEASES_API, 500, "Internal", {}, None), "service_unavailable"),
                 (b"not JSON", "invalid_response"), (b"\xff", "invalid_response"),
                 ({"unexpected": "object"}, "invalid_response"),
                 (b" " * (MAX_RESPONSE_BYTES + 1), "invalid_response")]
        for value, code in cases:
            with self.subTest(code=code):
                result = UpdateChecker("0.3.0", opener=FakeOpener(value)).check()
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["errorCode"], code)
                self.assertFalse(result["available"])
                self.assertIsNone(result["releaseUrl"])
                self.assertNotIn("private network details", result["message"])

    def test_ten_minute_cache_force_throttle_and_defensive_copies(self):
        now = [100.0]
        opener = FakeOpener([release()])
        checker = UpdateChecker("0.3.0", opener=opener, clock=lambda: now[0])
        first = checker.check()
        first["assets"]["windowsInstaller"] = "corrupted"
        self.assertNotEqual(checker.check()["assets"]["windowsInstaller"], "corrupted")
        now[0] += 9.9
        checker.check(force=True)
        self.assertEqual(len(opener.calls), 1)
        now[0] += 0.1
        checker.check(force=True)
        self.assertEqual(len(opener.calls), 2)
        now[0] += 599
        checker.check()
        self.assertEqual(len(opener.calls), 2)
        now[0] += 1
        checker.check()
        self.assertEqual(len(opener.calls), 3)

    def test_failed_checks_are_cached_and_concurrent_requests_share_one_fetch(self):
        opener = FakeOpener(URLError("offline"))
        checker = UpdateChecker("0.3.0", opener=opener)
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: checker.check(force=True), range(16)))
        self.assertEqual(len(opener.calls), 1)
        self.assertTrue(all(result["status"] == "error" for result in results))


if __name__ == "__main__":
    unittest.main()
