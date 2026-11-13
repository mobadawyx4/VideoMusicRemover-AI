<#
.SYNOPSIS
    VideoMusicRemover AI — Safe Windows PowerShell Update Script
.DESCRIPTION
    Safely stops running VideoMusicRemover AI processes, preserves user .env configuration
    and cached data/models, pulls Git updates if a remote is configured, and updates dependencies.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.FullName
Set-Location $RootDir

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VideoMusicRemover AI — Safe Local Update" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Stop running VideoMusicRemover AI processes safely
$StopScript = Join-Path $RootDir "stop.ps1"
if (Test-Path $StopScript) {
    & $StopScript
}

# 2. Backup .env configuration
$EnvFile = Join-Path $RootDir ".env"
$EnvBackup = Join-Path $RootDir ".runtime\.env.backup"
if (Test-Path $EnvFile) {
    New-Item -ItemType Directory -Force -Path (Join-Path $RootDir ".runtime") | Out-Null
    Copy-Item $EnvFile $EnvBackup -Force
    Write-Host "  [OK] Backed up custom .env configuration" -ForegroundColor Green
}

# 3. Pull latest Git changes if inside a repository with a remote
$GitDir = Join-Path $RootDir ".git"
$GitCmd = Get-Command git -ErrorAction SilentlyContinue
if ((Test-Path $GitDir) -and $GitCmd) {
    try {
        $RemoteUrl = & git remote get-url origin 2>$null
        if ($LASTEXITCODE -eq 0 -and $RemoteUrl) {
            Write-Host "[INFO] Pulling latest updates from Git remote..." -ForegroundColor Cyan
            & git pull --ff-only
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] Repository updated from origin" -ForegroundColor Green
            } else {
                Write-Host "[WARN] Could not fast-forward from Git remote; keeping local working tree." -ForegroundColor Yellow
            }
        } else {
            Write-Host "[INFO] No Git remote configured; skipping git pull and refreshing dependencies." -ForegroundColor Cyan
        }
    } catch {
        Write-Host "[WARN] Git update skipped: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 4. Restore .env if needed
if ((Test-Path $EnvBackup) -and -not (Test-Path $EnvFile)) {
    Copy-Item $EnvBackup $EnvFile -Force
}

# 5. Re-run installer to sync changed dependencies and validate setup
& (Join-Path $RootDir "install.ps1") -NonInteractive

Write-Host "Update complete! Your configuration (.env) and cached models (data\) were preserved." -ForegroundColor Green
