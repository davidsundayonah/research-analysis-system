# Release engineering and dependency audit

## Current release baseline

The single version source is `[project].version` in `pyproject.toml`; the desktop UI, website, preflight script, Inno Setup command line, and tagged build read or validate that value. Use stable immutable tags in `vMAJOR.MINOR.PATCH` form. The workflow refuses a tag that differs from the package version and refuses to create a release whose tag already has a published release. Never move a published tag or replace release assets.

## Dependency and packaging audit

| Component | Production use | Packaging treatment |
| --- | --- | --- |
| PySide6 | Desktop UI, Qt platform plugin | PyInstaller Qt hooks; installer preflight checks `qwindows.dll`; packaged self-test creates QApplication |
| NumPy, pandas | Numerical arrays and dataset processing | Runtime requirements; NumPy core hidden imports retained, tests excluded |
| SciPy, statsmodels, arch | Inferential and time-series analysis | Runtime requirements; SciPy lazy imports and compiled libraries collected; test modules filtered |
| Matplotlib, seaborn | Charts and diagnostics | Runtime requirements; QtAgg backend and resources collected by hooks; packaged chart render is tested |
| openpyxl, xlrd, pyreadstat | XLSX/XLS and statistical-file imports/exports | Runtime requirements |
| python-docx, pypdf, Pillow, pytesseract | Report/document/image workflows | Runtime requirements; OCR additionally requires an independently installed Tesseract executable and is not bundled |
| cryptography | Password/security support | Runtime requirement |
| SQLite | Project store | Python standard library; created under `%APPDATA%\\ResearchAnalysis` |
| FastAPI, Uvicorn | Separate public download website | Website requirements only; excluded from desktop bundle |
| PyInstaller | Build only | `requirements-build.txt`; not a runtime library |
| pytest, httpx | Test only | `requirements-dev.txt`; excluded from installer |

The pinned direct production set is in `requirements.txt`. Its transitive dependencies are resolved by pip from those pinned direct requirements. The onedir build explicitly carries SciPy dynamic libraries and keeps the application icon, project metadata, and readme. PyInstaller's PySide6/NumPy hooks provide Qt, NumPy and Matplotlib package resources; installer checks fail if the Windows Qt platform plugin is missing. `runtime_hooks/windows_runtime.py` prevents external Python/Qt paths from overriding the bundle and relocates Matplotlib's writable cache to the user profile.

For v1.0.2, pip-audit found 132 unique advisories across the direct `cryptography`, `pypdf`, and `Pillow` requirements. The pins were updated to 50.0.0, 6.21.4, and 13.0.0 respectively; the final audit reported no known vulnerabilities. The preserved before/after reports and CycloneDX SBOM are listed in `RELEASE_TEST_REPORT.md`. The SBOM contains the production environment's component inventory but the generator reports an incomplete dependency graph.

Known external runtime requirement: OCR operations need Tesseract OCR installed separately. Windows' Visual C++ runtime may also be needed on unusually clean systems; the setup wizard checks for it and offers Microsoft's official download page. This release pipeline does not bundle or silently fetch third-party system runtimes.

### Local AppData install-root failure

The earlier non-admin smoke test ran Setup with Inno Setup's `/CURRENTUSER` override. In that mode, `{autopf}` resolves through `{userpf}` to `{localappdata}\Programs`. Inno attempted to create the Local AppData shell folder through `SHGetKnownFolderPath`/`SHGetFolderPath` (`CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE`) and returned `0x80070002`, even though the process had a valid `LOCALAPPDATA` value and the directory existed. The test profile had the modern `Explorer\User Shell Folders` key but no legacy `Explorer\Shell Folders` cache. Direct calls with shell-folder creation requested reproduced the failure; the existing environment path and the ordinary non-create known-folder lookup worked. This was a shell-folder creation/profile-initialization mismatch, not a missing application dependency or an unavailable APPDATA database path.

The installer now uses a scripted default-directory resolver instead of expanding `{autopf}` in current-user mode. It accepts only an absolute, existing `LOCALAPPDATA` directory; otherwise it checks the non-creating Local AppData shell lookup. When `LOCALAPPDATA` is absent, it can derive the standard Local AppData location from an existing `USERPROFILE` and create that directory. If `LOCALAPPDATA` was explicitly set but invalid and the shell lookup also fails, Setup stops with a clear error instead of silently choosing another profile path. The machine-wide default remains 64-bit Program Files. The regression smoke mode removes `LOCALAPPDATA` from the Setup process and checks the fallback, application database, settings persistence, upgrade fixture, reinstall, and data preservation.

## Test evidence and limits

The Windows CI workflow runs pytest, builds the onedir bundle on a Windows x64 runner, verifies key distribution resources, then the tagged release workflow runs the packaged self-test and Inno Setup install/launch/uninstall smoke test with isolated `%APPDATA%`. The smoke test confirms sentinel user data remains after uninstall. It does not claim to be a clean virtual machine test. See [RELEASE_TEST_REPORT.md](RELEASE_TEST_REPORT.md) for the statuses and evidence from this workspace.

Never mark an unexecuted check as passed. The Windows runner smoke test does not prove behavior on every Windows 10/11 image.

## Distribution security

Release automation publishes `ResearchAnalysis_Setup.exe`, `SHA256SUMS.txt`, and a CycloneDX environment SBOM. SHA-256 detects file corruption and mismatched downloads, but the checksum is hosted alongside the installer; it is not an independent publisher signature. Releases are currently unsigned because no Authenticode certificate is configured. Windows SmartScreen may show an unknown-publisher warning, especially for early downloads. Obtain and protect an Authenticode code-signing certificate, keep its private key in protected CI secrets or a managed signing service, and sign and timestamp the installer before claiming a signed release.

The update check uses only stable GitHub Releases from the configured repository and exact named assets, validates HTTPS URLs, compares semantic versions, verifies SHA-256, checks the Inno Setup signature marker and Windows PE container, saves the installer, and asks before opening it. Inno Setup's bootstrapper can be a 32-bit PE even when its payload is x64; the release build validates a 64-bit Windows runner, compiles an x64-only setup, and smoke-tests the installed executable. Users can inspect the published release and checksum manually. Network failures leave the installed application and its data untouched.

## Repeatable release procedure

1. Merge reviewed changes to `main` and update `pyproject.toml` using semantic versioning.
2. Add user-facing changes to `CHANGELOG.md` and ensure CI passes.
3. Create and push a new immutable tag matching the version, for example `git tag v1.0.3; git push origin v1.0.3`. This starts verification only; it does not publish a public release.
4. Review the Windows verification job, retained artifact, install logs, checksum, SBOM, test report, and release notes.
5. When all release gates pass, dispatch **Verify and release Windows installer** on that exact tag with `publish_release=true`; satisfy any protection on the `production-release` Environment. The publishing job verifies the tag and checksum again before attaching release artifacts.
6. After publication, verify the public release assets and the Render website's `/`, `/download`, and `/healthz` endpoints.
7. Website deployment uses the independent Render service described in `DEPLOYMENT.md`. The `main` branch is configured for automatic deployment, so pushing to `main` can deploy the website; desktop packaging does not deploy it.

## Hosting

The website uses the existing FastAPI ASGI application and is configured for Render (`render.yaml`), where it runs independently of Windows release builds. The process binds Render's `$PORT`, trusts proxy headers, disables API docs, provides `/healthz`, applies security headers, and obtains the latest public version from GitHub. Render provisions HTTPS for its hostname; custom domains and DNS/TLS are configured in the Render dashboard. Vercel's Python function runtime would require changing the current server deployment model, so it is not used.
