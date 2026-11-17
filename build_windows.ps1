param(
    [switch]$SkipInstaller,
    [switch]$NoInstallDependencies,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
if (-not $PythonExe) {
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $PythonExe = $venvPython
    }
    else {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw "Python was not found on PATH and the repository .venv is missing. Install 64-bit Python 3.11-3.13 or pass -PythonExe."
        }
        $PythonExe = $pythonCommand.Source
    }
}
$PythonExe = [System.IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python executable not found: $PythonExe. Create .venv with 64-bit Python 3.11-3.13, or pass -PythonExe."
}

if (-not $NoInstallDependencies) {
    & $PythonExe -m pip install -r (Join-Path $root "requirements.txt") -r (Join-Path $root "requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "Installing runtime/build requirements failed (exit $LASTEXITCODE)." }
}

$version = & $PythonExe (Join-Path $root "tools\windows_build_check.py")
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Build environment validation failed. Install 64-bit Windows Python and the requirements listed above." }
& $PythonExe (Join-Path $root "tools\verify_scientific_stack.py")
if ($LASTEXITCODE -ne 0) { throw "NumPy/SciPy/Matplotlib packaging preflight failed." }

$spec = Join-Path $root "research_analysis.spec"
$buildDir = Join-Path $root "build\research_analysis"
$bundleDir = Join-Path $root "dist\ResearchAnalysis"
$installerDir = Join-Path $root "dist\installer"
$zipPath = Join-Path $root "dist\ResearchAnalysis-Windows-x64.zip"
Remove-Item -LiteralPath $buildDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $bundleDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $installerDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue

& $PythonExe -m PyInstaller --clean --noconfirm $spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE). See the preceding hook/import error." }

$exe = Join-Path $bundleDir "ResearchAnalysis.exe"
$requiredFiles = @(
    $exe,
    (Join-Path $bundleDir "_internal\README.md"),
    (Join-Path $bundleDir "_internal\pyproject.toml"),
    (Join-Path $bundleDir "_internal\research_analysis.ico")
)
foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required packaged file is missing: $path" }
}
$qtPlugin = Get-ChildItem -LiteralPath (Join-Path $bundleDir "_internal") -Filter qwindows.dll -File -Recurse | Select-Object -First 1
if (-not $qtPlugin) { throw "PySide6 Windows platform plugin qwindows.dll is missing from the onedir bundle." }
$scipyDlls = Get-ChildItem -LiteralPath (Join-Path $bundleDir "_internal") -Filter "*.dll" -File -Recurse | Where-Object { $_.FullName -match "scipy" }
if (-not $scipyDlls) { throw "No SciPy DLLs were collected. Check the SciPy PyInstaller hooks and environment." }

Write-Host "Verified onedir files, qwindows.dll, and SciPy DLLs. Bundle: $bundleDir"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $bundleDir,
    $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)
if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf) -or (Get-Item -LiteralPath $zipPath).Length -le 0) {
    throw "Compressed onedir archive was not created: $zipPath"
}
Write-Host "Compressed onedir archive created: $zipPath"
if ($SkipInstaller) { return }

& (Join-Path $root "installer\build_installer.ps1") -Version $version -PythonExe $PythonExe
if ($LASTEXITCODE -ne 0) { throw "Inno Setup installer build failed (exit $LASTEXITCODE)." }

$installer = Join-Path $root "dist\installer\ResearchAnalysis-Setup.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw "Installer was not generated: $installer" }
Write-Host "Installer created: $installer"
