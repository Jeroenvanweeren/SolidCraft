#!/usr/bin/env python3
"""Install verified SolidCraft web release bundles and expose a small update API."""

import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
import zipfile


REPOSITORY_API = "https://api.github.com/repos/tangency-labs/solidcraft"
VERSION_PATTERN = re.compile(r"^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 10000
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
RELEASES_DIR = DATA_DIR / "releases"
UPDATE_LOCK = threading.Lock()


class UpdateError(Exception):
    """An expected error while looking up, verifying, or activating a release."""


def canonical_version(value):
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        raise UpdateError("version must look like 0.30.1 or 0.31.0-rc.1")
    return match.group(1)


def request_json(url):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "solidcraft-web-container",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise UpdateError(f"GitHub release lookup failed: {error}") from error


def download(url, destination, maximum=MAX_DOWNLOAD_BYTES):
    request = Request(url, headers={"User-Agent": "solidcraft-web-container"})
    digest = hashlib.sha256()
    size = 0
    try:
        with urlopen(request, timeout=120) as response, destination.open("wb") as output:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > maximum:
                raise UpdateError("release asset exceeds the download size limit")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise UpdateError("release asset exceeds the download size limit")
                digest.update(chunk)
                output.write(chunk)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        destination.unlink(missing_ok=True)
        if isinstance(error, UpdateError):
            raise
        raise UpdateError(f"release asset download failed: {error}") from error
    return digest.hexdigest()


def checksum_for(checksums, filename):
    matches = []
    for line in checksums.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line.strip())
        if match and match.group(2) == filename:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise UpdateError(f"SHA256SUMS.txt must contain one checksum for {filename}")
    return matches[0]


def safe_extract(archive_path, destination, expected_root):
    destination.mkdir(parents=True, exist_ok=False)
    total_size = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise UpdateError("release archive contains too many files")
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                if "\\" in name or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
                    raise UpdateError("release archive contains an unsafe path")
                if not path.parts or path.parts[0] != expected_root:
                    raise UpdateError("release archive has an unexpected directory layout")

                mode = entry.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise UpdateError("release archive contains a non-regular file")
                if entry.is_dir():
                    continue

                relative_parts = path.parts[1:]
                if not relative_parts:
                    raise UpdateError("release archive contains an invalid root file")
                total_size += entry.file_size
                if total_size > MAX_EXTRACTED_BYTES:
                    raise UpdateError("release archive expands beyond the size limit")
                target = destination.joinpath(*relative_parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        if isinstance(error, UpdateError):
            raise
        raise UpdateError(f"release archive could not be extracted: {error}") from error

    for required in ("index.html", "sw.js", "build.json"):
        if not (destination / required).is_file():
            raise UpdateError(f"release archive is missing {required}")


def active_version():
    try:
        link = os.readlink(DATA_DIR / "current")
    except OSError:
        return None
    match = re.fullmatch(r"releases/(.+)", link)
    if not match:
        return None
    try:
        return canonical_version(match.group(1))
    except UpdateError:
        return None


def release_for(version):
    if version == "latest":
        release = request_json(f"{REPOSITORY_API}/releases/latest")
    else:
        version = canonical_version(version)
        release = request_json(f"{REPOSITORY_API}/releases/tags/v{version}")

    tag = release.get("tag_name", "")
    resolved_version = canonical_version(tag)
    if version != "latest" and resolved_version != version:
        raise UpdateError("GitHub returned a different release version than requested")
    if release.get("draft"):
        raise UpdateError("draft releases cannot be installed")

    asset_name = f"solidcraft-web-{resolved_version}.zip"
    assets = {asset.get("name"): asset for asset in release.get("assets", [])}
    if asset_name not in assets or "SHA256SUMS.txt" not in assets:
        raise UpdateError(f"release {tag} has no web bundle and checksum file")
    return resolved_version, assets[asset_name], assets["SHA256SUMS.txt"]


def install(version):
    with UPDATE_LOCK:
        resolved_version, web_asset, checksum_asset = release_for(version)
        if active_version() == resolved_version:
            return {"version": resolved_version, "updated": False}

        RELEASES_DIR.mkdir(parents=True, exist_ok=True)
        final_dir = RELEASES_DIR / resolved_version
        if not final_dir.exists():
            with tempfile.TemporaryDirectory(prefix=".install-", dir=RELEASES_DIR) as temporary:
                work = Path(temporary)
                archive_path = work / web_asset["name"]
                checksum_path = work / "SHA256SUMS.txt"
                archive_digest = download(web_asset["browser_download_url"], archive_path)
                download(checksum_asset["browser_download_url"], checksum_path, 1024 * 1024)
                expected_digest = checksum_for(checksum_path.read_text(encoding="utf-8"), web_asset["name"])
                if not hmac.compare_digest(archive_digest, expected_digest):
                    raise UpdateError("web bundle SHA-256 does not match SHA256SUMS.txt")

                extracted = work / "site"
                safe_extract(archive_path, extracted, web_asset["name"].removesuffix(".zip"))
                os.replace(extracted, final_dir)
        elif not all((final_dir / name).is_file() for name in ("index.html", "sw.js", "build.json")):
            raise UpdateError("an incomplete installation already exists for this version")

        temporary_link = DATA_DIR / f".current-{os.getpid()}-{threading.get_ident()}"
        try:
            os.symlink(f"releases/{resolved_version}", temporary_link)
            os.replace(temporary_link, DATA_DIR / "current")
        finally:
            temporary_link.unlink(missing_ok=True)
        return {"version": resolved_version, "updated": True}


class UpdateHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SolidCraftUpdater"
    sys_version = ""

    def log_message(self, format_string, *args):
        print(f"update-api: {format_string % args}", flush=True)

    def authorized(self):
        expected = f"Bearer {self.server.update_token}"
        supplied = self.headers.get("Authorization", "")
        if hmac.compare_digest(supplied, expected):
            return True
        self.send_json(401, {"error": "unauthorized"}, extra_headers={"WWW-Authenticate": "Bearer"})
        return False

    def send_json(self, status, value, extra_headers=None):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.authorized():
            return
        if urlsplit(self.path).path != "/_admin/status":
            self.send_json(404, {"error": "not found"})
            return
        self.send_json(200, {"version": active_version()})

    def do_POST(self):
        if not self.authorized():
            return
        parsed = urlsplit(self.path)
        if parsed.path != "/_admin/update":
            self.send_json(404, {"error": "not found"})
            return
        parameters = parse_qs(parsed.query, keep_blank_values=True)
        versions = parameters.get("version", ["latest"])
        if len(versions) != 1:
            self.send_json(400, {"error": "provide exactly one version parameter"})
            return
        version = versions[0]
        if version != "latest":
            try:
                version = canonical_version(version)
            except UpdateError as error:
                self.send_json(400, {"error": str(error)})
                return
        try:
            result = install(version)
        except UpdateError as error:
            self.send_json(502, {"error": str(error)})
            return
        self.send_json(200, result)


def main():
    token = os.environ.get("UPDATE_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("UPDATE_TOKEN must contain at least 32 characters")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    if active_version() is None:
        print("No installed release found; installing the latest SolidCraft web release.", flush=True)
        install("latest")

    api = http.server.ThreadingHTTPServer(("127.0.0.1", 8081), UpdateHandler)
    api.update_token = token
    api_thread = threading.Thread(target=api.serve_forever, daemon=True)
    api_thread.start()

    nginx = subprocess.Popen(["nginx", "-g", "daemon off;"])

    def stop(signum, frame):
        nginx.terminate()
        threading.Thread(target=api.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    result = nginx.wait()
    api.shutdown()
    api.server_close()
    raise SystemExit(result)


if __name__ == "__main__":
    main()