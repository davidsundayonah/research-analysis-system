import tomllib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from urllib.error import URLError

from app.web import DOWNLOAD_FILENAME, LATEST_RELEASE_DOWNLOAD, app as vercel_app, create_app


def test_vercel_entrypoint_is_the_fastapi_download_application():
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as project_file:
        project_config = tomllib.load(project_file)

    assert project_config["tool"]["vercel"]["entrypoint"] == "app.web:app"
    assert "fastapi==0.115.12" in project_config["project"]["dependencies"]
    assert isinstance(vercel_app, FastAPI)
    assert TestClient(vercel_app).get("/healthz").json() == {"status": "ok"}


def _write_installer(path, marker=b"Inno Setup Setup Data"):
    path.write_bytes(b"MZ" + marker + b"\0" * (1024 * 1024))


def test_download_page_describes_desktop_app_without_replica_routes(tmp_path, monkeypatch):
    monkeypatch.setattr("app.web._latest_release_version", lambda: "1.0.2")
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.2", True))
    executable = tmp_path / DOWNLOAD_FILENAME
    _write_installer(executable)
    client = TestClient(create_app(executable))

    response = client.get("/")

    assert response.status_code == 200
    assert "Research Analysis System" in response.text
    assert "Download for Windows" in response.text
    assert "Windows installer" in response.text
    assert "ResearchAnalysis_Setup.exe" in response.text
    assert 'href="/download"' in response.text
    assert f"Version <strong>{client.app.version}</strong>" in response.text
    assert "Windows 10 or later (64-bit)" in response.text
    assert "does not provide browser-based research tools" in response.text

    for path in (
        "/login",
        "/signup",
        "/help",
        "/docs",
        "/openapi.json",
        "/api/projects",
        "/web/projects/1",
    ):
        assert client.get(path).status_code == 404


def test_download_route_serves_real_executable_as_attachment(tmp_path):
    executable = tmp_path / DOWNLOAD_FILENAME
    _write_installer(executable)
    client = TestClient(create_app(executable))

    response = client.get("/download")

    assert response.status_code == 200
    assert response.content.startswith(b"MZInno Setup Setup Data")
    assert len(response.content) > 1024 * 1024
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{DOWNLOAD_FILENAME}"'
    )
    assert response.headers["content-type"] == (
        "application/vnd.microsoft.portable-executable"
    )
    assert response.headers["x-content-type-options"] == "nosniff"


def test_local_installer_displays_checkout_version_not_older_remote_release(tmp_path, monkeypatch):
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.1", True))
    executable = tmp_path / DOWNLOAD_FILENAME
    _write_installer(executable)
    client = TestClient(create_app(executable))

    response = client.get("/")

    assert response.status_code == 200
    assert f"Version <strong>{client.app.version}</strong>" in response.text
    assert "Version <strong>1.0.1</strong>" not in response.text


def test_download_uses_latest_release_when_local_build_is_not_deployed(tmp_path, monkeypatch):
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.2", True))
    client = TestClient(create_app(tmp_path / DOWNLOAD_FILENAME), follow_redirects=False)

    response = client.get("/download")

    assert response.status_code == 302
    assert response.headers["location"] == LATEST_RELEASE_DOWNLOAD


def test_fastapi_docs_and_schema_are_disabled(tmp_path):
    client = TestClient(create_app(tmp_path / DOWNLOAD_FILENAME))

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/healthz").json() == {"status": "ok"}


def test_download_responses_include_security_headers_and_redirect_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.2", True))
    client = TestClient(create_app(tmp_path / DOWNLOAD_FILENAME), follow_redirects=False)

    response = client.get("/download")

    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "server" not in response.headers


def test_configured_download_path_serves_only_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.2", True))
    directory = tmp_path / "not-an-installer"
    directory.mkdir()
    client = TestClient(create_app(directory), follow_redirects=False)

    response = client.get("/download")

    assert response.status_code == 302
    assert response.headers["location"] == LATEST_RELEASE_DOWNLOAD


def test_download_reports_missing_release_asset_instead_of_redirecting(tmp_path, monkeypatch):
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.2", False))
    client = TestClient(create_app(tmp_path / DOWNLOAD_FILENAME), follow_redirects=False)

    response = client.get("/download")

    assert response.status_code == 503
    assert "does not yet include the Windows installer" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_landing_page_does_not_advertise_missing_release_asset(tmp_path, monkeypatch):
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.1", False))
    client = TestClient(create_app(tmp_path / DOWNLOAD_FILENAME))

    response = client.get("/")

    assert "temporarily unavailable" in response.text
    assert 'href="/download"' not in response.text
    assert "Version <strong>1.0.1</strong>" in response.text


class _FakeResponse:
    def __init__(self, body=b"", headers=None, status=200):
        self.body = body
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def _release_payload(assets):
    import json

    return json.dumps({"tag_name": "v1.0.1", "assets": assets}).encode()


def _release_asset(name=DOWNLOAD_FILENAME):
    return {
        "name": name,
        "state": "uploaded",
        "size": 2 * 1024 * 1024,
        "browser_download_url": f"https://github.com/davidsundayonah/research-analysis-system/releases/download/v1.0.1/{name}",
    }


def test_existing_v101_release_executable_is_not_treated_as_installer(monkeypatch):
    import app.web as web

    web._version_cache = None
    monkeypatch.setattr(
        "app.web.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            _release_payload([_release_asset("ResearchAnalysis.exe")])
        ),
    )
    assert web._latest_release_info() == ("1.0.1", False)


def test_github_release_without_assets_is_unavailable(monkeypatch):
    import app.web as web

    web._version_cache = None
    monkeypatch.setattr("app.web.urlopen", lambda *_args, **_kwargs: _FakeResponse(_release_payload([])))
    assert web._latest_release_info() == ("1.0.1", False)


def test_exact_uploaded_asset_must_be_publicly_reachable(monkeypatch):
    import app.web as web

    web._version_cache = None
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _FakeResponse(_release_payload([_release_asset()]))
        return _FakeResponse(headers={"Content-Disposition": f'attachment; filename="{DOWNLOAD_FILENAME}"'})

    monkeypatch.setattr(web, "urlopen", fake_urlopen)
    assert web._latest_release_info() == ("1.0.1", True)
    assert calls == 2


def test_github_api_failure_fails_closed(monkeypatch):
    import app.web as web

    web._version_cache = None
    monkeypatch.setattr(web, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")))
    assert web._latest_release_info() == (None, False)


def test_portable_executable_at_configured_path_is_never_served(tmp_path, monkeypatch):
    executable = tmp_path / DOWNLOAD_FILENAME
    _write_installer(executable, marker=b"PyInstaller portable application")
    monkeypatch.setattr("app.web._latest_release_info", lambda: ("1.0.1", False))
    client = TestClient(create_app(executable), follow_redirects=False)

    response = client.get("/download")

    assert response.status_code == 503
    assert "does not yet include the Windows installer" in response.text
