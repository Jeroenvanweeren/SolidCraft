import tempfile
import unittest
import zipfile
from pathlib import Path

from updater import UpdateError, canonical_version, checksum_for, safe_extract


class UpdateHelpersTest(unittest.TestCase):
    def test_normalizes_release_versions(self):
        self.assertEqual(canonical_version("v0.30.1"), "0.30.1")
        self.assertEqual(canonical_version("0.31.0-rc.2"), "0.31.0-rc.2")

    def test_rejects_non_release_versions(self):
        for version in ("latest/../../etc", "main", "0.30", ""):
            with self.subTest(version=version), self.assertRaises(UpdateError):
                canonical_version(version)

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


if __name__ == "__main__":
    unittest.main()