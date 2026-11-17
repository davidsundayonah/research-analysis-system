import hashlib
import json
from urllib.error import URLError

import pytest

from app import updates


def release_payload(version="2.0.0", *, prerelease=False, installer_url=None, sums_url=None):
    base = f"https://github.com/{updates.REPOSITORY}/releases/download/v{version}/"
    return {
        "tag_name": f"v{version}",
        "prerelease": prerelease,
        "draft": False,
        "body": "Release notes",
        "assets": [
            {"name": updates.INSTALLER, "state": "uploaded", "browser_download_url": installer_url or base + updates.INSTALLER},
            {"name": "SHA256SUMS.txt", "state": "uploaded", "browser_download_url": sums_url or base + "SHA256SUMS.txt"},
        ],
    }


def make_fake_installer():
    data = bytearray(1024 * 1024 + 32)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x86] = b"PE\0\0\x4c\x01"
    data[512:536] = b"Inno Setup Setup Data"
    return bytes(data)


class FakeResponse:
    def __init__(self, content, url):
        self.content = content
        self.url = url
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if size < 0:
            size = len(self.content) - self.offset
        chunk = self.content[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


def test_latest_release_accepts_new_stable_release_with_only_expected_assets(monkeypatch):
    installer = f"https://github.com/{updates.REPOSITORY}/releases/download/v2.0.0/{updates.INSTALLER}"
    sums = f"https://github.com/{updates.REPOSITORY}/releases/download/v2.0.0/SHA256SUMS.txt"
    monkeypatch.setattr(updates, "_read_https", lambda *_args, **_kwargs: json.dumps(release_payload()).encode())
    release = updates.latest_release()
    assert release["available"] is True
    assert release["version"] == "2.0.0"
    assert release["installer_url"] == installer
    assert release["checksums_url"] == sums
    assert release["notes"] == "Release notes"


def test_latest_release_rejects_prerelease_and_draft(monkeypatch):
    for overrides in ({"version": "2.0.0-rc1", "prerelease": True}, {"draft": True}):
        payload = release_payload(overrides.get("version", "2.0.0"), prerelease=overrides.get("prerelease", False))
        payload["draft"] = overrides.get("draft", False)
        monkeypatch.setattr(updates, "_read_https", lambda *_args, payload=payload, **_kwargs: json.dumps(payload).encode())
        with pytest.raises(ValueError, match="stable"):
            updates.latest_release()


def test_latest_release_reports_no_update_when_latest_is_already_installed(monkeypatch):
    current = updates.get_application_version()
    monkeypatch.setattr(updates, "_read_https", lambda *_args, **_kwargs: json.dumps(release_payload(current)).encode())
    assert updates.latest_release()["available"] is False


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"tag_name":"v2.0.0","assets":{}}'])
def test_latest_release_rejects_malformed_responses(monkeypatch, body):
    monkeypatch.setattr(updates, "_read_https", lambda *_args, **_kwargs: body)
    with pytest.raises((ValueError, json.JSONDecodeError, AttributeError)):
        updates.latest_release()


def test_latest_release_propagates_api_and_timeout_errors(monkeypatch):
    monkeypatch.setattr(updates, "_read_https", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")))
    with pytest.raises(URLError):
        updates.latest_release()


def test_latest_release_rejects_untrusted_asset_urls(monkeypatch):
    payload = release_payload(installer_url="https://example.com/setup.exe")
    monkeypatch.setattr(updates, "_read_https", lambda *_args, **_kwargs: json.dumps(payload).encode())
    with pytest.raises(ValueError, match="expected tagged release"):
        updates.latest_release()


def download_fixture(monkeypatch, tmp_path, *, content=None, checksum=None, final_url="https://release-assets.githubusercontent.com/file"):
    content = content if content is not None else make_fake_installer()
    checksum = checksum if checksum is not None else hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(updates, "_read_https", lambda *_args, **_kwargs: f"{checksum}  {updates.INSTALLER}\n".encode())
    monkeypatch.setattr(updates, "urlopen", lambda *_args, **_kwargs: FakeResponse(content, final_url))
    release = {"available": True, "version": "2.0.0",
               "installer_url": f"https://github.com/{updates.REPOSITORY}/releases/download/v2.0.0/{updates.INSTALLER}",
               "checksums_url": f"https://github.com/{updates.REPOSITORY}/releases/download/v2.0.0/SHA256SUMS.txt"}
    return release


def test_download_verifies_checksum_format_and_publishes_atomically(monkeypatch, tmp_path):
    content = make_fake_installer()
    release = download_fixture(monkeypatch, tmp_path, content=content)
    target = updates.download_verified_installer(release, tmp_path)
    assert target.read_bytes() == content
    assert target.name == "ResearchAnalysis_Setup_2.0.0.exe"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("checksum", ["", "invalid", "0" * 64])
def test_download_rejects_missing_malformed_or_mismatched_checksum(monkeypatch, tmp_path, checksum):
    content = make_fake_installer()
    if checksum == "":
        sums = ""
    elif checksum == "invalid":
        sums = f"{checksum}  {updates.INSTALLER}\n"
    else:
        sums = f"{checksum}  {updates.INSTALLER}\n"
    monkeypatch.setattr(updates, "_read_https", lambda *_args, **_kwargs: sums.encode())
    monkeypatch.setattr(updates, "urlopen", lambda *_args, **_kwargs: FakeResponse(content, "https://release-assets.githubusercontent.com/file"))
    release = {"available": True, "version": "2.0.0",
               "installer_url": f"https://github.com/{updates.REPOSITORY}/releases/download/v2.0.0/{updates.INSTALLER}",
               "checksums_url": f"https://github.com/{updates.REPOSITORY}/releases/download/v2.0.0/SHA256SUMS.txt"}
    with pytest.raises(ValueError, match="checksum"):
        updates.download_verified_installer(release, tmp_path)
    assert not list(tmp_path.glob("*.exe"))
    assert not list(tmp_path.glob("*.part"))


def invalid_pe_installer():
    data = bytearray(make_fake_installer())
    data[0x84:0x86] = b"\0\0"
    return bytes(data)


@pytest.mark.parametrize("content", [b"MZ" + b"x" * (1024 * 1024), invalid_pe_installer()], ids=["missing-inno-marker", "invalid-pe-machine"])
def test_download_rejects_corrupt_or_unrecognized_installer(monkeypatch, tmp_path, content):
    release = download_fixture(monkeypatch, tmp_path, content=content)
    with pytest.raises(ValueError, match="recognized Inno|PE machine"):
        updates.download_verified_installer(release, tmp_path)
    assert not list(tmp_path.glob("*.exe"))
    assert not list(tmp_path.glob("*.part"))


def test_download_rejects_redirect_outside_github_release_hosts(monkeypatch, tmp_path):
    release = download_fixture(monkeypatch, tmp_path, final_url="https://example.com/payload")
    with pytest.raises(ValueError, match="redirected outside"):
        updates.download_verified_installer(release, tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_download_rejects_unavailable_or_path_traversal_release(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="newer stable"):
        updates.download_verified_installer({"available": False}, tmp_path)
    unsafe = {"available": True, "version": "../../bad", "installer_url": "", "checksums_url": ""}
    with pytest.raises(ValueError, match="version"):
        updates.download_verified_installer(unsafe, tmp_path)
