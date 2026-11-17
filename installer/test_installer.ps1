param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [switch]$CurrentUser,
    [switch]$SimulateMissingLocalAppData,
    [switch]$UseDefaultInstallDirectory,
    [string]$PreviousInstallerPath,
    [switch]$ReinstallAfterUninstall,
    [string]$ReportDirectory
)

$ErrorActionPreference = "Stop"
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$testRoot = Join-Path $env:TEMP ("Research Analysis Installer Smoke " + [guid]::NewGuid().ToString("N"))
$originalLocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA", "Process")
$originalAppData = [Environment]::GetEnvironmentVariable("APPDATA", "Process")
$originalPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
$profileRoot = Join-Path $testRoot "User Profile"
$isolatedAppData = Join-Path $profileRoot "Roaming"
$sentinel = Join-Path $isolatedAppData "ResearchAnalysis\preserve-this-file.txt"
$currentLocalAppData = if ($originalLocalAppData -and (Test-Path -LiteralPath $originalLocalAppData -PathType Container)) {
    [System.IO.Path]::GetFullPath($originalLocalAppData)
} else {
    Join-Path $env:USERPROFILE "AppData\Local"
}
$expectedInstallDir = if ($UseDefaultInstallDirectory -and $CurrentUser) {
    Join-Path $currentLocalAppData "Programs\Research Analysis System"
} elseif ($UseDefaultInstallDirectory) {
    Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)) "Research Analysis System"
} else {
    Join-Path $testRoot "Program Files With Spaces\Research Analysis System"
}
$appExe = Join-Path $expectedInstallDir "ResearchAnalysis.exe"
$uninstaller = Join-Path $expectedInstallDir "unins000.exe"
$testToken = [guid]::NewGuid().ToString("N")
$logs = [System.Collections.Generic.List[string]]::new()
$appProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$smokeInstallStarted = $false

$startMenuRoot = [Environment]::ExpandEnvironmentVariables(
    (Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders").Programs
)
$desktopRoot = [Environment]::ExpandEnvironmentVariables(
    (Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders").Desktop
)
$commonProgramsRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonPrograms)
$commonDesktopRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonDesktopDirectory)
$shortcutPaths = @(
    (Join-Path $startMenuRoot "Research Analysis System\Research Analysis System.lnk"),
    (Join-Path $commonProgramsRoot "Research Analysis System\Research Analysis System.lnk")
)
$desktopShortcutPaths = @(
    (Join-Path $desktopRoot "Research Analysis System.lnk"),
    (Join-Path $commonDesktopRoot "Research Analysis System.lnk")
)

if (-not $CurrentUser) {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Machine-wide installer smoke tests require an elevated PowerShell session. Use -CurrentUser for the non-admin installation test."
    }
}
if (-not $env:USERPROFILE -or -not (Test-Path -LiteralPath $env:USERPROFILE -PathType Container)) {
    throw "USERPROFILE is unavailable or does not identify an existing Windows profile directory."
}
if (($shortcutPaths | Where-Object { Test-Path -LiteralPath $_ }) -or ($desktopShortcutPaths | Where-Object { Test-Path -LiteralPath $_ })) {
    throw "An existing Research Analysis System shortcut was found. Refusing to overwrite a user's shortcut during the installer smoke test."
}
$uninstallRoots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
)
foreach ($root in $uninstallRoots) {
    if (Test-Path -LiteralPath $root) {
        foreach ($entry in Get-ChildItem -LiteralPath $root) {
            $metadata = Get-ItemProperty -LiteralPath $entry.PSPath
            if ($metadata.DisplayName -eq "Research Analysis System") {
                throw "An existing Research Analysis System installation is registered at '$($metadata.InstallLocation)'. Refusing to modify it during the smoke test."
            }
        }
    }
}

New-Item -ItemType Directory -Path (Split-Path -Parent $sentinel) -Force | Out-Null
Set-Content -LiteralPath $sentinel -Value "Installer smoke-test data must survive uninstall and reinstall." -Encoding utf8

function Copy-Diagnostics {
    if (-not $ReportDirectory) { return }
    New-Item -ItemType Directory -Path $ReportDirectory -Force | Out-Null
    foreach ($log in $logs) {
        if (Test-Path -LiteralPath $log) {
            Copy-Item -LiteralPath $log -Destination (Join-Path $ReportDirectory ([System.IO.Path]::GetFileName($log))) -Force
        }
    }
    $runtimeLog = Join-Path $env:TEMP "ResearchAnalysis-installer-smoke-test.log"
    if (Test-Path -LiteralPath $runtimeLog) {
        Copy-Item -LiteralPath $runtimeLog -Destination (Join-Path $ReportDirectory "installed-app-smoke.log") -Force
    }
}

function Invoke-SmokeInstall([string]$SetupPath, [string]$Label) {
    $logPath = Join-Path $testRoot ("installer-{0}.log" -f $Label)
    $logs.Add($logPath)
    $scope = if ($CurrentUser) { "/CURRENTUSER " } else { "" }
    $directory = if ($UseDefaultInstallDirectory) { "" } else { "/DIR=`"$expectedInstallDir`" " }
    $arguments = "$scope/VERYSILENT /SUPPRESSMSGBOXES /NORESTART $directory/TASKS=desktopicon /LOG=`"$logPath`""
    $script:smokeInstallStarted = $true
    $savedLocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA", "Process")
    try {
        if ($SimulateMissingLocalAppData) { $env:LOCALAPPDATA = "" }
        $process = Start-Process -FilePath $SetupPath -ArgumentList $arguments -Wait -PassThru
    } finally {
        $env:LOCALAPPDATA = $savedLocalAppData
    }
    if ($process.ExitCode -ne 0) {
        Copy-Diagnostics
        if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Tail 60 }
        throw "Inno Setup returned exit code $($process.ExitCode) during '$Label'. Setup log: $logPath"
    }
    if ($SimulateMissingLocalAppData -and $CurrentUser) {
        $contents = Get-Content -LiteralPath $logPath -Raw
        if ($contents -notmatch "Resolved per-user Local AppData through the Windows shell folder API|Resolved per-user Local AppData from USERPROFILE") {
            throw "The missing-LOCALAPPDATA regression scenario did not exercise either documented fallback. See $logPath"
        }
    }
    if (-not (Test-Path -LiteralPath $expectedInstallDir -PathType Container)) {
        throw "Setup completed without creating the expected installation directory: $expectedInstallDir"
    }
}

function Invoke-InstalledAppTest([string]$Action) {
    $oldAppData = [Environment]::GetEnvironmentVariable("APPDATA", "Process")
    $oldPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
    $log = Join-Path $testRoot ("app-{0}.log" -f $Action)
    $logs.Add($log)
    try {
        $env:APPDATA = $isolatedAppData
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:RESEARCH_ANALYSIS_SELF_TEST_LOG = $log
        $process = Start-Process -FilePath $appExe `
            -ArgumentList "--installer-smoke-test $Action $testToken" `
            -WorkingDirectory $expectedInstallDir -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 50 }
            throw "Installed app smoke action '$Action' failed with exit code $($process.ExitCode)."
        }
        if (-not (Test-Path -LiteralPath $log)) { throw "Installed app did not produce diagnostics for action '$Action'." }
    } finally {
        $env:APPDATA = $oldAppData
        $env:PATH = $oldPath
        Remove-Item Env:\RESEARCH_ANALYSIS_SELF_TEST_LOG -ErrorAction SilentlyContinue
    }
}

function Start-NormalAppAndWait {
    $oldAppData = [Environment]::GetEnvironmentVariable("APPDATA", "Process")
    $oldPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
    try {
        $env:APPDATA = $isolatedAppData
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $process = Start-Process -FilePath $appExe -WorkingDirectory $expectedInstallDir -WindowStyle Hidden -PassThru
        $appProcesses.Add($process)
        $process.WaitForInputIdle(30000) | Out-Null
        Start-Sleep -Seconds 3
        $process.Refresh()
        if ($process.HasExited) { throw "The installed application exited during launch (code $($process.ExitCode))." }
    } finally {
        $env:APPDATA = $oldAppData
        $env:PATH = $oldPath
    }
}

function Invoke-PackagedSelfTest {
    $oldAppData = [Environment]::GetEnvironmentVariable("APPDATA", "Process")
    $oldPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
    $log = Join-Path $testRoot "packaged-runtime-self-test.log"
    $logs.Add($log)
    try {
        $env:APPDATA = $isolatedAppData
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:RESEARCH_ANALYSIS_SELF_TEST_LOG = $log
        $process = Start-Process -FilePath $appExe -ArgumentList "--packaging-self-test" `
            -WorkingDirectory $expectedInstallDir -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 50 }
            throw "Packaged runtime self-test failed with exit code $($process.ExitCode)."
        }
        $contents = Get-Content -LiteralPath $log -Raw
        foreach ($component in @("NumPy numerical operation", "SciPy calculation", "Qt initialized; platform=windows", "Matplotlib Qt chart rendered", "Isolated database initialization")) {
            if ($contents -notmatch [regex]::Escape("[PASS] $component")) {
                throw "Packaged runtime self-test did not report PASS for '$component'."
            }
        }
    } finally {
        $env:APPDATA = $oldAppData
        $env:PATH = $oldPath
        Remove-Item Env:\RESEARCH_ANALYSIS_SELF_TEST_LOG -ErrorAction SilentlyContinue
    }
}

function Stop-NormalApps {
    foreach ($process in $appProcesses) {
        $process.Refresh()
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
            $process.WaitForExit()
        }
    }
}

function Invoke-SmokeUninstall([string]$Label) {
    $log = Join-Path $testRoot ("uninstaller-{0}.log" -f $Label)
    $logs.Add($log)
    $process = Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$log`"" -Wait -PassThru
    if ($process.ExitCode -ne 0) { Copy-Diagnostics; throw "Inno Setup uninstaller returned exit code $($process.ExitCode). Log: $log" }
    if (Test-Path -LiteralPath $appExe) { throw "Application executable remains after uninstall: $appExe" }
    if (($shortcutPaths | Where-Object { Test-Path -LiteralPath $_ }) -or ($desktopShortcutPaths | Where-Object { Test-Path -LiteralPath $_ })) {
        throw "Application shortcuts remain after uninstall."
    }
    if (-not (Test-Path -LiteralPath $sentinel)) { throw "Application data under APPDATA was removed during uninstall." }
    $database = Join-Path $isolatedAppData "ResearchAnalysis\research_analysis.db"
    if (-not (Test-Path -LiteralPath $database)) { throw "The user database was removed during uninstall: $database" }
}

try {
    if ($PreviousInstallerPath) {
        $previousInstaller = (Resolve-Path -LiteralPath $PreviousInstallerPath).Path
        $previousVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($previousInstaller).ProductVersion
        if (-not $previousVersion.StartsWith("1.0.1")) {
            throw "The representative upgrade fixture must identify itself as 1.0.1; found '$previousVersion'."
        }
        Invoke-SmokeInstall $previousInstaller "previous-fixture"
        if (-not (Test-Path -LiteralPath $appExe)) { throw "The representative 1.0.1 fixture did not install the application." }
        Invoke-InstalledAppTest "write"
    }

    Invoke-SmokeInstall $installer "1.0.2"
    foreach ($requiredPath in @(
        $appExe,
        (Join-Path $expectedInstallDir "_internal\README.md"),
        (Join-Path $expectedInstallDir "_internal\pyproject.toml")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) { throw "Installed application file is missing: $requiredPath" }
    }
    $peStream = [System.IO.File]::OpenRead($appExe)
    try {
        $reader = [System.IO.BinaryReader]::new($peStream)
        $peStream.Position = 0x3c
        $peOffset = $reader.ReadInt32()
        $peStream.Position = $peOffset + 4
        $machine = $reader.ReadUInt16()
    } finally {
        if ($reader) { $reader.Dispose() } else { $peStream.Dispose() }
    }
    if ($machine -ne 0x8664) { throw "Installed app is not Windows x64 (PE machine 0x$($machine.ToString('x4')))." }
    $qtPlugin = Get-ChildItem -LiteralPath (Join-Path $expectedInstallDir "_internal") -Filter "qwindows.dll" -File -Recurse | Select-Object -First 1
    if (-not $qtPlugin) { throw "Installed application is missing qwindows.dll." }
    $actualStartMenuShortcuts = @($shortcutPaths | Where-Object { Test-Path -LiteralPath $_ })
    $actualDesktopShortcuts = @($desktopShortcutPaths | Where-Object { Test-Path -LiteralPath $_ })
    if ($actualStartMenuShortcuts.Count -ne 1) { throw "Expected exactly one Start Menu shortcut; found $($actualStartMenuShortcuts.Count)." }
    if ($actualDesktopShortcuts.Count -ne 1) { throw "Expected exactly one optional desktop shortcut; found $($actualDesktopShortcuts.Count)." }

    if (-not $PreviousInstallerPath) { Invoke-InstalledAppTest "write" }
    Invoke-InstalledAppTest "verify"
    Invoke-PackagedSelfTest
    Start-NormalAppAndWait
    Stop-NormalApps

    if ($ReinstallAfterUninstall) {
        Invoke-SmokeUninstall "after-upgrade"
        Invoke-SmokeInstall $installer "reinstall"
        Invoke-InstalledAppTest "verify"
        Start-NormalAppAndWait
        Stop-NormalApps
    }
    Invoke-InstalledAppTest "cleanup"
    Invoke-SmokeUninstall "final"
    if (Get-Process -Name ResearchAnalysis -ErrorAction SilentlyContinue) {
        throw "ResearchAnalysis processes remain after uninstall."
    }

    if ($ReportDirectory) { Copy-Diagnostics }
    Write-Host "Installer smoke test passed: scope=$([bool]$CurrentUser), installDir=$expectedInstallDir, files, x64 executable, Qt plugin, shortcuts, app launch, database, settings, upgrade/reinstall where configured, uninstall, and data preservation."
    Write-Host "Temporary smoke-test profile and logs remain at: $testRoot"
} catch {
    Stop-NormalApps
    if ($smokeInstallStarted -and (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        $registered = $false
        foreach ($root in $uninstallRoots) {
            if (Test-Path -LiteralPath $root) {
                foreach ($entry in Get-ChildItem -LiteralPath $root) {
                    $metadata = Get-ItemProperty -LiteralPath $entry.PSPath
                    if ($metadata.DisplayName -eq "Research Analysis System" -and
                        [System.IO.Path]::GetFullPath($metadata.InstallLocation).TrimEnd('\') -eq $expectedInstallDir.TrimEnd('\')) {
                        $registered = $true
                    }
                }
            }
        }
        if ($registered) {
            $failureCleanupLog = Join-Path $testRoot "failure-cleanup-uninstaller.log"
            $logs.Add($failureCleanupLog)
            $cleanup = Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$failureCleanupLog`"" -Wait -PassThru
            if ($cleanup.ExitCode -ne 0) { Write-Error "Smoke-test cleanup failed with exit code $($cleanup.ExitCode); see $failureCleanupLog" }
        }
    }
    Copy-Diagnostics
    throw
} finally {
    $env:LOCALAPPDATA = $originalLocalAppData
    $env:APPDATA = $originalAppData
    $env:PATH = $originalPath
    Remove-Item Env:\RESEARCH_ANALYSIS_SELF_TEST_LOG -ErrorAction SilentlyContinue
}
