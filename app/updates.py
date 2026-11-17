"""User-confirmed, checksum-verified GitHub Releases update downloads."""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import re
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.version import get_application_version

REPOSITORY = "davidsundayonah/research-analysis-system"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
INSTALLER = "ResearchAnalysis_Setup.exe"


def _read_https(url: str, limit: int = 2_000_000) -> bytes:
    if not url.startswith("https://github.com/") and not url.startswith("https://api.github.com/"):
        raise ValueError("Release metadata contained a non-GitHub URL")
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ResearchAnalysis-Updater"})
    with urlopen(request, timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release metadata exceeds the allowed size")
    return data


def latest_release() -> dict:
    """Return validated latest stable release metadata."""
    release = json.loads(_read_https(API_URL).decode("utf-8"))
    if not isinstance(release, dict):
        raise ValueError("GitHub returned malformed release metadata")
    tag = release.get("tag_name", "")
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag) if isinstance(tag, str) else None
    if release.get("draft") or release.get("prerelease") or not match:
        raise ValueError("Latest GitHub release is not a stable MAJOR.MINOR.PATCH release")
    current = tuple(map(int, get_application_version().split(".")))
    if tuple(map(int, match.groups())) <= current:
        return {"version": tag.removeprefix("v"), "available": False, "notes": release.get("body", "")}
    raw_assets = release.get("assets", [])
    if not isinstance(raw_assets, list):
        raise ValueError("GitHub returned malformed release assets")
    assets = {a.get("name"): a for a in raw_assets if isinstance(a, dict)}
    for name in (INSTALLER, "SHA256SUMS.txt"):
        asset = assets.get(name)
        if not asset or asset.get("state") != "uploaded" or not isinstance(asset.get("browser_download_url"), str):
            raise ValueError(f"Release is missing required asset {name}")
        url = asset["browser_download_url"]
        if not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/{tag}/"):
            raise ValueError(f"Release asset URL is not from the expected tagged release: {name}")
    return {"version": tag.removeprefix("v"), "available": True,
            "notes": release.get("body", ""), "installer_url": assets[INSTALLER]["browser_download_url"],
            "checksums_url": assets["SHA256SUMS.txt"]["browser_download_url"]}


def download_verified_installer(release: dict, destination_dir: Path | None = None) -> Path:
    """Download only the release installer whose published SHA-256 matches."""
    if not release.get("available"):
        raise ValueError("There is no newer stable release to download")
    version = release.get("version", "")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release version is not a stable MAJOR.MINOR.PATCH version")
    if tuple(map(int, version.split("."))) <= tuple(map(int, get_application_version().split("."))):
        raise ValueError("There is no newer stable release to download")
    release_base = f"https://github.com/{REPOSITORY}/releases/download/v{version}/"
    sums_url = release.get("checksums_url", "")
    installer_url = release.get("installer_url", "")
    if not isinstance(sums_url, str) or not sums_url.startswith(release_base + "SHA256SUMS.txt"):
        raise ValueError("Checksum URL is not from the expected tagged GitHub release")
    if not isinstance(installer_url, str) or not installer_url.startswith(release_base + INSTALLER):
        raise ValueError("Installer URL is not from the expected tagged GitHub release")
    sums = _read_https(sums_url, limit=100_000).decode("utf-8")
    expected = None
    for line in sums.splitlines():
        fields = line.strip().split()
        if len(fields) == 2 and fields[1].lstrip("*") == INSTALLER:
            expected = fields[0].lower()
            break
    if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Published SHA256SUMS.txt has no valid installer checksum")

    target_dir = destination_dir or Path(tempfile.gettempdir()) / "ResearchAnalysis-Updates"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ResearchAnalysis_Setup_{version}.exe"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="research-analysis-update-", suffix=".part", dir=target_dir, delete=False) as output:
            temp_path = Path(output.name)
            digest = hashlib.sha256()
            total = 0
            request = Request(installer_url, headers={"User-Agent": "ResearchAnalysis-Updater"})
            with urlopen(request, timeout=60) as response:
                final_url = response.geturl()
                if not final_url.startswith((
                    "https://release-assets.githubusercontent.com/",
                    "https://objects.githubusercontent.com/",
                )):
                    raise ValueError("Installer download redirected outside GitHub's release asset hosts")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 1024 * 1024 * 1024:
                        raise ValueError("Downloaded installer exceeds the allowed size")
                    digest.update(chunk)
                    output.write(chunk)
        if total <= 1024 * 1024:
            raise ValueError("Downloaded installer has an implausible size")
        if digest.hexdigest() != expected:
            raise ValueError("Installer SHA-256 does not match the published checksum")
        with temp_path.open("rb") as installer_file:
            if installer_file.read(2) != b"MZ":
                raise ValueError("Downloaded file is not a recognized Inno Setup installer")
            with mmap.mmap(installer_file.fileno(), 0, access=mmap.ACCESS_READ) as installer_map:
                if installer_map.find(b"Inno Setup Setup Data") < 0:
                    raise ValueError("Downloaded file is not a recognized Inno Setup installer")
            # The Inno bootstrapper may be a 32-bit PE for an x64-only payload.
            installer_file.seek(0x3C)
            pe_offset_bytes = installer_file.read(4)
            pe_offset = int.from_bytes(pe_offset_bytes, "little") if len(pe_offset_bytes) == 4 else 0
            installer_file.seek(pe_offset)
            pe_header = installer_file.read(6)
            machine = pe_header[4:6] if pe_header[:4] == b"PE\0\0" else b""
            if machine not in (b"L\x01", b"d\x86"):
                raise ValueError("Downloaded Inno installer has an unsupported Windows PE machine type")
        os.replace(temp_path, target)
        temp_path = None
        return target
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
