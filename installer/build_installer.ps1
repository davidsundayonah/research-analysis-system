param(
    [string]$Version = "1.0.2",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $compiler) {
    $compilerPaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ChocolateyInstall "bin\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if ($compilerPaths) {
        $compilerPath = $compilerPaths
    }
    else {
        throw "Inno Setup 6 compiler ISCC.exe was not found. Install Inno Setup 6 and rerun this script."
    }
}
else {
    $compilerPath = $compiler.Source
}

$bundleExe = Join-Path $repoRoot "dist\ResearchAnalysis\ResearchAnalysis.exe"
if (-not (Test-Path -LiteralPath $bundleExe)) {
    throw "PyInstaller onedir output is missing: $bundleExe"
}

$scriptPath = Join-Path $PSScriptRoot "ResearchAnalysis.iss"
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "assets\research_analysis.ico"))) {
    throw "Application icon is missing: $(Join-Path $repoRoot 'assets\research_analysis.ico')"
}
& $compilerPath "/DAppVersion=$Version" $scriptPath
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
}

$installerPath = Join-Path $repoRoot "dist\installer\ResearchAnalysis_Setup.exe"
if (-not (Test-Path -LiteralPath $installerPath)) {
    throw "Installer output was not created: $installerPath"
}
if ((Get-Item -LiteralPath $installerPath).Length -le 0) {
    throw "Installer output is empty: $installerPath"
}

if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) { $PythonExe = $venvPython }
    else {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $pythonCommand) { throw "Python was not found to validate the generated installer executable." }
        $PythonExe = $pythonCommand.Source
    }
}
& $PythonExe (Join-Path $repoRoot "tools\validate_installer.py") $installerPath
if ($LASTEXITCODE -ne 0) { throw "Generated executable did not pass Inno Setup installer validation. Refusing to distribute it." }

# Keep the hyphenated local deliverable requested for manual distribution as
# an identical copy; GitHub Releases uses the stable underscore filename.
$localInstallerAlias = Join-Path $repoRoot "dist\installer\ResearchAnalysis-Setup.exe"
Copy-Item -LiteralPath $installerPath -Destination $localInstallerAlias -Force

Write-Host "Installer created: $installerPath"
Write-Host "Local alias created: $localInstallerAlias"
