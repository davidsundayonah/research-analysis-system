# Download site and Windows release deployment

## Public download website

The FastAPI download site is hosted separately from the Windows desktop build. Render reads `render.yaml`, installs only `requirements-web.txt`, starts `app.web:app`, and checks `/healthz`. Render supplies HTTPS for the generated `onrender.com` hostname. The intended default hostname for this service is:

`https://research-analysis-downloads.onrender.com`

Render assigns the public service URL after deployment. No production URL has been verified yet; do not advertise a guessed hostname. This repository change alone does not deploy it.

To deploy:

1. In Render, create a Blueprint instance connected to this GitHub repository and the `main` branch.
2. Confirm the `research-analysis-downloads` web service from `render.yaml` and deploy it.
3. Copy the HTTPS URL shown in the Render service dashboard. Verify `<service-url>/healthz` returns `{"status":"ok"}`, then check `/` and `/download` at that same service URL.

Render environment settings are declared in `render.yaml`:

- `PYTHON_VERSION=3.13.7`
- `RESEARCH_ANALYSIS_ENABLE_HSTS=true`

No secret or persistent disk is required. The site gets the latest version and installer availability from the public GitHub Releases API. If the API is down or the release lacks a reachable, correctly named setup asset, the page shows an unavailable state and `/download` returns HTTP 503. `RESEARCH_ANALYSIS_DOWNLOAD_PATH` can point to a locally mounted, validated Inno Setup installer if one is deliberately hosted with the web service. `RESEARCH_ANALYSIS_RELEASE_DOWNLOAD_URL` is optional and is accepted only for HTTPS GitHub links.

## Build the Windows installer

On 64-bit Windows with Python 3.11 through 3.13 and Inno Setup 6 installed:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.\build_windows.ps1
```

The script validates the scientific stack, cleans old build artifacts, builds and checks the PyInstaller onedir bundle, creates `dist\ResearchAnalysis-Windows-x64.zip`, compiles the Inno Setup package, validates its Inno Setup signature, and leaves both installer names in `dist\installer`:

- `ResearchAnalysis_Setup.exe` for GitHub Releases and the website.
- `ResearchAnalysis-Setup.exe` as a local alias.

Pass `-SkipInstaller` to create only the onedir ZIP, or `-NoInstallDependencies` when the build environment already has the pinned requirements.

## Publish a release

The GitHub Actions workflows run CI for pull requests and pushes to `main`. Pushing a version tag such as `v1.0.2` to `.github/workflows/release.yml` runs all release verification and uploads a workflow artifact; it does not publish a public release. It audits production dependencies, verifies the immutable tag and exact source commit, runs the project tests, builds the onedir output, installs Inno Setup on the Windows runner, validates and exercises current-user and elevated machine-wide installation, creates a representative upgrade fixture, generates a SHA-256 manifest and production-environment CycloneDX SBOM, and retains logs and reports. A separate `workflow_dispatch` run on that tag with `publish_release=true` is required to publish, and the `production-release` GitHub Environment can require reviewer approval. Existing releases are rejected rather than overwritten.

```powershell
git tag v1.0.2
git push origin v1.0.2
```

After verification succeeds, open **Actions → Verify and release Windows installer**, select the exact immutable tag, and explicitly set **Publish the verified release publicly** to true. Review the retained verification artifact first. The publishing job rechecks the tag commit and installer checksum before creating the release. Do not move or recreate an existing tag.

Review [RELEASE_ENGINEERING.md](RELEASE_ENGINEERING.md) for the dependency audit, local build notes, testing limits, signing status, and full release checklist.

Do not manually rename `ResearchAnalysis.exe` to the setup filename. The release site accepts only an uploaded, anonymously reachable `ResearchAnalysis_Setup.exe` asset, and the build workflow rejects executables without the Inno Setup signature.
