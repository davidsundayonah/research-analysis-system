$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$hostName = if ($env:WEB_HOST) { $env:WEB_HOST } else { "127.0.0.1" }
$port = if ($env:WEB_PORT) { [int]$env:WEB_PORT } else { 8000 }
& $python -m uvicorn app.web:app --host $hostName --port $port
