import http.server
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from updater import (
    UpdateError,
    UpdateHandler,
    build_type,
    canonical_version,
    checksum_for,
    load_release_builds,
    safe_extract,
)


class UpdateHelpersTest(unittest.TestCase):
    def test_normalizes_release_versions(self):
        self.assertEqual(canonical_version("v0.30.1"), "0.30.1")
        self.assertEqual(canonical_version("0.31.0-rc.2"), "0.31.0-rc.2")

    def test_rejects_non_release_versions(self):
        for version in ("latest/../../etc", "main", "0.30", "", None):
            with self.subTest(version=version), self.assertRaises(UpdateError):
                canonical_version(version)

    def test_classifies_release_channels(self):
        self.assertEqual(build_type("0.40.0", False), "stable")
        self.assertEqual(build_type("0.40.0-rc.2", True), "release candidate")
        self.assertEqual(build_type("0.40.0-nightly.20261110.117.1", True), "nightly")
        self.assertEqual(build_type("0.40.0-beta.1", True), "beta")

    def test_loads_all_installable_release_pages(self):
        def release(tag, prerelease=False):
            version = tag.removeprefix("v")
            return {
                "tag_name": tag,
                "name": f"SolidCraft {version}",
                "prerelease": prerelease,
                "draft": False,
                "published_at": "2026-11-11T01:44:57Z",
                "html_url": f"https://github.com/tangency-labs/solidcraft/releases/tag/{tag}",
                "assets": [
                    {"name": f"solidcraft-web-{version}.zip"},
                    {"name": "SHA256SUMS.txt"},
                ],
            }

        unavailable = release("v0.1.0")
        unavailable["assets"] = []
        first_page = [release("v0.30.1"), release("v0.31.0-rc.2", True), unavailable]
        first_page.extend({"tag_name": f"not-a-release-{index}"} for index in range(97))
        pages = [first_page, [release("v0.31.0-nightly.20261110.117.1", True)]]
        with patch("updater.request_json", side_effect=pages) as request:
            builds = load_release_builds()

        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            [build["type"] for build in builds],
            ["stable", "release candidate", "stable", "nightly"],
        )
        self.assertEqual([build["available"] for build in builds], [True, True, False, True])
        self.assertEqual(builds[-1]["version"], "0.31.0-nightly.20261110.117.1")

    def test_selects_checksum_by_exact_filename(self):
        digest = "a" * 64
        checksums = f"{digest}  other.zip\n{digest} *solidcraft-web-0.30.1.zip\n"
        self.assertEqual(checksum_for(checksums, "solidcraft-web-0.30.1.zip"), digest)

    def test_extracts_expected_site_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "site.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name in ("index.html", "sw.js", "build.json"):
                    archive.writestr(f"solidcraft-web-0.30.1/{name}", "ok")
            destination = root / "extracted"
            safe_extract(archive_path, destination, "solidcraft-web-0.30.1")
            self.assertEqual((destination / "index.html").read_text(), "ok")

    def test_rejects_zip_slip_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "site.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("solidcraft-web-0.30.1/../outside", "bad")
            with self.assertRaises(UpdateError):
                safe_extract(archive_path, root / "extracted", "solidcraft-web-0.30.1")


class UpdateHandlerTest(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), UpdateHandler)
        self.server.update_token = "test-token-" + ("x" * 32)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, method="GET", headers=None):
        request = Request(f"{self.base_url}{path}", method=method, headers=headers or {})
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    @patch("updater.release_catalog", return_value={"active_version": "0.30.1", "builds": []})
    def test_release_catalog_is_public(self, _release_catalog):
        status, result = self.request("/_admin/releases")
        self.assertEqual(status, 200)
        self.assertEqual(result["active_version"], "0.30.1")

    @patch("updater.install", return_value={"version": "0.30.1", "updated": True})
    def test_selected_release_can_be_published_without_authentication(self, install):
        status, result = self.request("/_admin/update?version=v0.30.1", method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(result["version"], "0.30.1")
        install.assert_called_once_with("0.30.1")

    def test_status_endpoint_still_requires_authentication(self):
        with self.assertRaises(HTTPError) as response:
            self.request("/_admin/status")
        self.assertEqual(response.exception.code, 401)
        response.exception.close()

        status, result = self.request(
            "/_admin/status",
            headers={"Authorization": f"Bearer {self.server.update_token}"},
        )
        self.assertEqual(status, 200)
        self.assertIn("version", result)


if __name__ == "__main__":
    unittest.main()