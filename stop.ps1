<#
.SYNOPSIS
    SilentTrack AI — Safe Windows PowerShell Shutdown Script
.DESCRIPTION
    Stops ONLY the backend and frontend processes started by SilentTrack AI
    using recorded PID files in .runtime\, without killing unrelated Python or Node processes.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "SilentlyContinue"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.FullName
$RuntimeDir = Join-Path $RootDir ".runtime"

function Stop-SilentTrackProcess {
    param(
        [string]$Label,
        [string]$PidFile,
        [string]$ExpectedKeyword
    )

    if (-not (Test-Path $PidFile)) {
        return $false
    }

    $RawPid = (Get-Content $PidFile -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($RawPid)) {
        Remove-Item $PidFile -Force
        return $false
    }

    $TargetPid = 0
    if (-not [int]::TryParse($RawPid, [ref]$TargetPid)) {
        Remove-Item $PidFile -Force
        return $false
    }

    $Proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $Proc) {
        Remove-Item $PidFile -Force
        return $false
    }

    # Verify process ownership via CommandLine before terminating
    $CimProc = Get-CimInstance Win32_Process -Filter "ProcessId = $TargetPid" -ErrorAction SilentlyContinue
    $CmdLine = if ($CimProc) { $CimProc.CommandLine } else { "" }

    if ($CmdLine -and ($CmdLine -notlike "*$RootDir*") -and ($CmdLine -notlike "*$ExpectedKeyword*")) {
        Write-Host "[WARN] Skipping PID $TargetPid ($Label): does not belong to SilentTrack AI." -ForegroundColor Yellow
        Remove-Item $PidFile -Force
        return $false
    }

    Write-Host "[INFO] Stopping SilentTrack AI $Label (PID $TargetPid)..." -ForegroundColor Cyan

    # Stop any child processes spawned by this PID (e.g., node.exe/esbuild.exe under cmd/vite)
    $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $TargetPid" -ErrorAction SilentlyContinue
    foreach ($child in $Children) {
        $grandChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($child.ProcessId)" -ErrorAction SilentlyContinue
        foreach ($gc in $grandChildren) {
            Stop-Process -Id $gc.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }

    Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -Force
    Write-Host "  [OK] Stopped $Label" -ForegroundColor Green
    return $true
}

$StoppedFrontend = Stop-SilentTrackProcess -Label "Frontend (Vite)" -PidFile (Join-Path $RuntimeDir "frontend.pid") -ExpectedKeyword "vite"
$StoppedBackend  = Stop-SilentTrackProcess -Label "Backend (FastAPI)" -PidFile (Join-Path $RuntimeDir "backend.pid") -ExpectedKeyword "app.main:app"

if (-not $StoppedFrontend -and -not $StoppedBackend) {
    Write-Host "[INFO] No running SilentTrack AI instances found." -ForegroundColor Cyan
} else {
    Write-Host "SilentTrack AI has been stopped safely." -ForegroundColor Green
}
