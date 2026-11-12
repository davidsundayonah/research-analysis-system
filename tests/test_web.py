from fastapi.testclient import TestClient

from app.web import DOWNLOAD_FILENAME, LATEST_RELEASE_DOWNLOAD, create_app


def test_download_page_describes_desktop_app_without_replica_routes(tmp_path):
    executable = tmp_path / DOWNLOAD_FILENAME
    executable.write_bytes(b"MZ test executable")
    client = TestClient(create_app(executable))

    response = client.get("/")

    assert response.status_code == 200
    assert "Research Analysis System" in response.text
    assert "Download for Windows" in response.text
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
    contents = b"MZ\x90\x00 valid downloaded executable fixture"
    executable.write_bytes(contents)
    client = TestClient(create_app(executable))

    response = client.get("/download")

    assert response.status_code == 200
    assert response.content == contents
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{DOWNLOAD_FILENAME}"'
    )
    assert response.headers["content-type"] == (
        "application/vnd.microsoft.portable-executable"
    )
    assert response.headers["x-content-type-options"] == "nosniff"


def test_download_uses_latest_release_when_local_build_is_not_deployed(tmp_path):
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
