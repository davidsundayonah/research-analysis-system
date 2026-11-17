from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_installer_uses_profile_safe_scripted_install_directory():
    script = (ROOT / "installer" / "ResearchAnalysis.iss").read_text(encoding="utf-8")

    assert "DefaultDirName={code:GetDefaultInstallDir}" in script
    assert "GetEnv('LOCALAPPDATA')" in script
    assert "GetShellFolderByCSIDL($001C, False)" in script
    assert "GetEnv('USERPROFILE')" in script
    assert "Setup stopped because no usable per-user Local AppData directory could be resolved." in script
    assert "DefaultDirName={autopf}\\Research Analysis System" not in script


def test_windows_installer_smoke_has_missing_localappdata_regression_mode():
    script = (ROOT / "installer" / "test_installer.ps1").read_text(encoding="utf-8")

    assert "[switch]$SimulateMissingLocalAppData" in script
    assert "[switch]$ReinstallAfterUninstall" in script
    assert '("installer-{0}.log" -f $Label)' in script
    assert '"packaged-runtime-self-test.log"' in script


def test_packaged_installer_smoke_mode_covers_database_and_real_qsettings():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert "--installer-smoke-test" in source
    assert 'QSettings("ResearchAnalysis", "ResearchAnalysis")' in source
    assert "Application settings did not survive the upgrade" in source
    assert "Database path is outside the expected user data directory" in source


def test_pyinstaller_explicitly_bundles_namespace_package_update_modules():
    spec = (ROOT / "research_analysis.spec").read_text(encoding="utf-8")

    assert '"app.updates"' in spec
    assert '"app.version"' in spec


def test_windows_build_script_uses_active_python_when_repository_venv_is_absent():
    script = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")

    assert '[string]$PythonExe = ""' in script
    assert "Get-Command python.exe -ErrorAction SilentlyContinue" in script
    assert "the repository .venv is missing" in script
