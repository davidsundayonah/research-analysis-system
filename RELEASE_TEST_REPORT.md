# Release test report

Local checks were run on Windows 10 x64 (build 19045) with Python 3.13.7 available on the machine. The packaged self-test was run with Python directories removed from `PATH`; that is useful packaging evidence, but it does not prove Python independence on a clean VM.

The staged release-candidate installer is [ResearchAnalysis_Setup.exe](<C:/Users/Smarprex Telecom/OneDrive/Desktop/research_analysis/dist/release-candidate/v1.0.2/ResearchAnalysis_Setup.exe>); its SHA-256 is recorded in the adjacent `SHA256SUMS.txt`.

| Check | Status | Evidence / limit |
| --- | --- | --- |
| Full Python unit and integration suite | PASS | 234 passed; 563 existing scientific and deprecation warnings |
| Update and download website tests | PASS | 16 passed |
| Python source compilation | PASS | `compileall app tests` completed |
| GitHub Actions workflow syntax | PASS | Both workflow YAML files parsed successfully |
| Windows x64 PyInstaller onedir build | PASS | Staged under `dist` after verification; existing distribution files preserved |
| Qt Windows platform plugin and SciPy DLL presence | PASS | `qwindows.dll` and SciPy DLLs found in staged bundle |
| Packaged NumPy and SciPy operations | PASS | In-bundle self-test |
| Packaged PySide6 Windows initialization | PASS | In-bundle self-test selected `windows` platform |
| Packaged Matplotlib Qt rendering | PASS | In-bundle canvas render |
| Packaged icon and isolated SQLite initialization | PASS | In-bundle self-test |
| Inno Setup x64 installer compilation and format-marker validation | PASS | `ResearchAnalysis_Setup.exe` generated from the staged onedir bundle with Inno Setup 6.7.3 |
| Installer SHA-256 manifest | PASS | Candidate checksum re-computed and matched |
| Original current-user smoke attempt | FAIL, FIXED | Local attempt failed with Windows shell-folder error `0x80070002`; the corrected harness explicitly resolves a supported profile path. The corrected missing-`LOCALAPPDATA` installation passed in the GitHub-hosted Windows run recorded below. |
| First launch, uninstall, and user-data sentinel | PASS in corrected hosted smoke | The original local attempt did not reach install; the later hosted corrected smoke verified launch, data, uninstall and cleanup. |
| Program Files machine-wide installation | PASS on GitHub-hosted Windows | Elevated machine-wide install smoke passed; installed files, shortcuts, launch, database/settings, uninstall, and user-data preservation were checked. The local shell itself is not elevated. |
| Upgrade and reinstall | PASS with representative fixture | No historical installer was available; the hosted test used an explicitly identified representative 1.0.1 fixture built from the 1.0.2 payload. |
| Windows launch after OS restart | NOT TESTED | No restart was performed |
| Clean Windows 10/11 VMs without Python | NOT TESTED | No clean VMs available in this environment |
| Production dependency vulnerability audit | NOT TESTED locally | Added as a blocking step to GitHub CI and release workflows |
| Render deployment, live HTTPS download, and public release asset | NOT TESTED | Requires a connected Render service and a published GitHub release |
| Authenticode signature | NOT TESTED | No signing certificate is configured; this installer is unsigned |

## Security remediation verification (2026-11-16)

The pre-remediation pip-audit JSON is preserved at `security-audit/production-audit-v1.0.2-pre-remediation.json`. It contained 189 raw vulnerability records. Deduplicating by normalized package name and advisory ID yields **132 unique package/advisory pairs**: cryptography 7, pypdf 64, Pillow 61. Every affected package was a direct production dependency in `requirements.txt`; no affected transitive package was reported. The full OSV enrichment and advisory detail is preserved in `security-audit/production-audit-v1.0.2-pre-remediation-enriched.json` (132/132 advisory records retrieved; 0 fetch errors). Structured affected ranges are recorded directly; for the 41 entries without structured ranges, version intervals were extracted from vendor advisory prose and marked as text-derived. All 132 entries have a machine-readable range representation; the 41 text-derived entries retain their source details. Vendor fixed-version values are recorded per advisory in `vendor_confirmed_fixed_versions` and pip-audit fix fields.

The reported vulnerable direct pins were cryptography 46.0.3, pypdf 6.1.3, and Pillow 12.0.0. Targeted compatibility remediation selected the latest versions reported as fixing all findings for each package: cryptography 50.0.0 (reported fixed versions included 46.0.5, 46.0.6, 46.0.7, 48.0.1, 49.0.0, and 50.0.0); pypdf 6.21.4 (reported fixes range from 6.4.0 through 6.21.4); Pillow 13.0.0 (reported fixes include 12.1.1, 12.2.0, 12.3.0, and 13.0.0). Only these three direct pins were upgraded. They passed the complete test suite in both the repository environment and an isolated environment assembled from production requirements plus declared build/test requirements.

Severity classification uses the OSV-published CVSS v4 score where present and otherwise the CVSS v3 base score calculated from the published vector. The report includes **7 Critical, 61 High, 60 Medium, and 4 Low** unique advisories. 90 advisories have CVSS v4 scores and 42 use CVSS v3-only scores. For six advisory pages unavailable to the lookup tool, the same score was used only where the CVSS v4 vector exactly matched another OSV-scored record; these substitutions are explicitly labeled in the enrichment JSON. All 132 advisories were direct dependency findings; no transitive findings were present. Tool versions were pip-audit 2.10.1, cyclonedx-bom 8.0.1, and Python 3.13.7. The final production pip-audit command was `.venv\Scripts\python.exe -m pip_audit --cache-dir .test-temp\pip-audit-cache --timeout 60 --format json --output security-audit\production-audit-v1.0.2-post-remediation.json -r requirements.txt`; it completed with **No known vulnerabilities found** across 36 reported production dependencies. No advisory was suppressed. The post-remediation JSON is preserved.

CycloneDX 8.0.1 generated `security-audit/production-sbom-v1.0.2-post-remediation.cyclonedx.json` with `cyclonedx-py environment .test-temp/production-only-sbom-venv/Scripts/python.exe --pyproject pyproject.toml --output-format JSON --output-file security-audit/production-sbom-v1.0.2-post-remediation.cyclonedx.json` from a fresh pip-free virtual environment installed only from `requirements.txt`. It validates as CycloneDX 1.6 and contains 37 components. It includes cryptography 50.0.0, pypdf 6.21.4, and Pillow 13.0.0; it excludes pip, FastAPI, Uvicorn, pytest, and PyInstaller. The SBOM tool warned that its environment BOM root has no dependency graph edges; component inventory and versions are present, but the generated dependency graph is incomplete.

| Security/package check | Result | Evidence / limits |
| --- | --- | --- |
| Repository and isolated full test suite after targeted upgrades | PASS | Windows 10 x64 build 19045, Python 3.13.7. The 255-test isolated run passed in 196.74 seconds; the suite after the website display fix passed 256 in 200.10 seconds; the final suite with the runner-Python regression test passed **257 in 273.96 seconds** (563 warnings). Earlier repository-environment run also passed 255 tests; the prior baseline of 234 passing tests is retained. |
| Rebuilt Windows x64 onedir bundle | PASS | Rebuilt in `.test-temp/release-final` after all three upgrades; explicit `app.updates` and `app.version` imports are included. |
| Packaged application self-test | PASS | NumPy, SciPy, Windows Qt, Matplotlib render, icon resource, and isolated DB initialization passed. |
| Inno Setup compile and installer validation | PASS | Inno Setup 6.7.3 compiled the rebuilt bundle; `tools/validate_installer.py` passed. Installer is unsigned. |
| Final installer checksum | PASS | `3d362b6ea851555850117eaaf42e660248bddc8d0c2ce2c539ec8dea1c12d933`; manifest was recomputed and compared with the final installer. |
| Final production audit | PASS | No known vulnerabilities in `requirements.txt`; audit JSON preserved. |
| Production SBOM | PASS WITH LIMITATION | CycloneDX 1.6, 37 production components; dependency graph root edges incomplete as noted above. |
| Current-user clean installation and upgrade smoke | PASS | Corrected smoke test passed with `LOCALAPPDATA` removed. The `1.0.1` upgrade installer was a representative fixture built from the current payload, not a historical installer. It confirmed install paths, app files, shortcuts, normal launch, database initialization, settings persistence across upgrade and reinstall, user-data preservation after uninstall, and cleanup. Logs are under `.test-temp/release-final/smoke-currentuser`. |
| Download website local preview and route checks | PASS | Local preview at `http://127.0.0.1:8000/` shows the checkout version 1.0.2 and uses the rebuilt installer. Homepage, `/healthz`, and GET `/download` returned 200; download headers identify `ResearchAnalysis_Setup.exe`. The preview uses a task-local artifact and does not establish public availability. |
| Download website tests after local-version display fix | PASS | `python -m pytest -q tests/test_web.py`: 14 passed, 1 dependency deprecation warning. Added regression for an older remote release and current local installer. |
| Failure-path cleanup and user-data protection | PASS | The earlier import failure (`app.updates` omission) triggered harness cleanup. It removed only its uniquely registered temporary test install. The harness refuses to modify an existing registered installation and preserved isolated settings/database data during the successful uninstall/reinstall check. |
| Windows 11 clean VM and actual reboot | NOT TESTED | A clean Windows 11 VM and real OS restart are unavailable. Process-level reinstall was tested and is not represented as a reboot. |
| Initial GitHub tag verification run | FAIL, FIXED | Historical run `44062987304` failed because the expected missing-release check leaked a nonzero exit code. The check was corrected. Current verification run `44066885184` from main passed against the existing immutable `v1.0.2` tag; its Windows job passed and publication was skipped. |
| GitHub CI run on main | FAIL, CORRECTION PREPARED | Run `44063324584` passed dependency install, production audit, metadata preflight, and the full suite, then failed bundle build because `build_windows.ps1` assumed `.venv\Scripts\python.exe`; GitHub Actions provides Python on `PATH` without that repository venv. The script now discovers the active `python.exe` and has a regression test; the correction has not yet run on GitHub. |
| GitHub verification-only release run | PASS; publication skipped | Run `44066885184` checked out the immutable tag source, audited production dependencies (no known vulnerabilities), passed 256 tests, packaged self-test and installer build, clean per-user install with `LOCALAPPDATA` absent, representative 1.0.1 upgrade fixture, and elevated machine-wide install. It generated SHA256SUMS and a CycloneDX SBOM, validated artifacts, and retained artifact `windows-release-v1.0.2` (ID `14320952819`). Signing status: unsigned. The workflow was dispatched with `publish_release=false`; no public GitHub release exists. |
| Render production site | NOT VERIFIED | The candidate hostname `research-analysis-downloads.onrender.com` returned Cloudflare HTTP 404 after the `main` push; no live download page or health check could be verified. |

### Release disposition

**NOT READY FOR PUBLIC RELEASE.** The targeted security findings are resolved. Local and GitHub-hosted build, audit, artifact verification, user-level install, upgrade-fixture, and elevated machine-wide install checks pass. Main CI and the verification-only run for the existing immutable `v1.0.2` tag both succeeded. The installer is unsigned. A clean Windows 11 VM, actual OS restart test, and public production download verification remain outstanding. The configured Render candidate hostname still returns HTTP 404 at `/healthz`, so v1.0.2 remains unpublished to avoid directing users to a broken production download site.

## Final GitHub verification (2026-11-17)

- Main CI run `44066846342` for tested code commit `68ad223df4e0b30ee4961e45a2919f8c56010cc1` completed successfully. The report-only verification update was subsequently pushed to both `main` and `release-readiness/v1.0.2`; it did not change tested application code.
- The immutable `v1.0.2` tag still points to the previously recorded release source commit `154f20a0a80b1439356de502288a74e936e7d34d`. It was not moved or recreated. The verification-only workflow run `44066885184` completed successfully from main while validating the existing tag and source.
- GitHub-hosted Windows Python 3.13 ran 256 tests (563 warnings); production pip-audit reported no known vulnerabilities; PyInstaller build and packaged NumPy/SciPy/Matplotlib self-test passed.
- Both current-user installation with `LOCALAPPDATA` absent and elevated machine-wide installation passed. The workflow verified application files, shortcuts, normal launch, database/settings initialization, representative upgrade fixture, uninstall, and data preservation. The 1.0.1 fixture was constructed from the current payload, not a historical release installer.
- Release artifact verification generated SHA256SUMS and CycloneDX SBOM and retained workflow artifact `windows-release-v1.0.2` (artifact ID `14320952819`, uploaded archive SHA-256 `ceb02868e9b6d9fe3662bb468e176e9736c15e5dccf42cdcc4b29b8b37f0d123`). Installer signing step explicitly reported **UNSIGNED**. Release publication job was skipped (`publish_release=false`).
- `https://research-analysis-downloads.onrender.com/healthz` returned HTTP 404 on 2026-11-17. Thus production homepage, release notes, and installer download are not verified and the public release remains blocked. The local preview (when its development server is running) is at `http://127.0.0.1:8000/` and is not a substitute for production verification.
- A clean Windows 11 VM and actual OS restart remain untested. Process-level persistence/reinstall checks passed; no reboot is claimed.
