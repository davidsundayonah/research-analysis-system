$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Create .venv and install requirements first." }
& $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt") -r (Join-Path $PSScriptRoot "requirements-dev.txt")
& $python -m PyInstaller --clean --noconfirm (Join-Path $PSScriptRoot "research_analysis.spec")
Write-Host "Desktop build created under $PSScriptRoot\dist\ResearchAnalysis"
