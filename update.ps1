<#
.SYNOPSIS
    VideoMusicRemover AI — Safe Windows PowerShell Update Script
.DESCRIPTION
    Safely stops running VideoMusicRemover AI processes, backs up .env, preserves
    the cached AI model and user data, pulls Git updates only when the working tree
    is clean, and reruns the Windows installer without downloading the AI model or
    reinstalling unchanged dependencies.
.PARAMETER NoPull
    Skip git pull and only refresh dependencies from the current local files.
.PARAMETER NoLaunch
    Do not launch the application after the update completes.
.PARAMETER TorchMode
    Forwarded to install.ps1. Auto preserves a compatible CPU or CUDA installation.
#>
[CmdletBinding()]
param(
    [switch]$NoPull,
    [switch]$NoLaunch,
    [ValidateSet("Auto", "CPU", "CUDA")]
    [string]$TorchMode = "Auto"
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.FullName
Set-Location $RootDir

function Write-Info($Text) {
    Write-Host "[INFO] $Text" -ForegroundColor Cyan
}
function Write-Ok($Text) {
    Write-Host "  [OK] $Text" -ForegroundColor Green
}
function Write-Warn($Text) {
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}
function Fail($Text) {
    Write-Host ""
    Write-Host "[ERROR] $Text" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VideoMusicRemover AI — Safe Local Update" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Stop running VideoMusicRemover AI processes safely
$StopScript = Join-Path $RootDir "stop.ps1"
if (Test-Path $StopScript) {
    & $StopScript
}

# 2. Back up .env without overwriting older backups
$EnvFile = Join-Path $RootDir ".env"
$EnvBackup = $null
if (Test-Path $EnvFile) {
    $BackupDir = Join-Path $RootDir ".runtime\backups"
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $BackupName = ".env." + (Get-Date -Format "yyyyMMdd-HHmmss") + ".bak"
    $EnvBackup = Join-Path $BackupDir $BackupName
    Copy-Item $EnvFile $EnvBackup -Force
    Write-Ok "Backed up .env to $EnvBackup"
} else {
    Write-Info "No .env file exists yet; the installer will create one from .env.example."
}

# 3. Record the existing model cache so the update can report that it is preserved
$ModelsDir = Join-Path $RootDir "data\models"
$ModelCacheExisted = Test-Path $ModelsDir

# 4. Pull latest Git changes only when safe
$GitDir = Join-Path $RootDir ".git"
$GitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($NoPull.IsPresent) {
    Write-Info "Git pull skipped because -NoPull was specified."
} elseif ((Test-Path $GitDir) -and $GitCmd) {
    try {
        $RemoteUrl = & git remote get-url origin 2>$null
        if ($LASTEXITCODE -eq 0 -and $RemoteUrl) {
            $LocalChanges = & git status --porcelain 2>$null
            if ($LASTEXITCODE -eq 0 -and $LocalChanges) {
                Write-Warn "Local changes detected. Skipping git pull so your work is not overwritten."
                Write-Host "       Commit or stash your changes, then run: .\update.ps1" -ForegroundColor Gray
            } else {
                Write-Info "Pulling latest updates from the Git remote..."
                & git pull --ff-only
                if ($LASTEXITCODE -eq 0) {
                    Write-Ok "Repository updated from origin"
                } else {
                    Write-Warn "Could not fast-forward from the Git remote; keeping the current local files."
                    Write-Host "       Resolve the Git error above, then rerun .\update.ps1." -ForegroundColor Gray
                }
            }
        } else {
            Write-Info "No Git remote configured; skipping git pull and refreshing dependencies."
        }
    } catch {
        Write-Warn "Git update skipped: $($_.Exception.Message)"
    }
} else {
    Write-Info "Git is unavailable or this is not a Git checkout; updating from local files."
}

# 5. Restore .env if an update removed it unexpectedly
if ($EnvBackup -and (Test-Path $EnvBackup) -and -not (Test-Path $EnvFile)) {
    Copy-Item $EnvBackup $EnvFile -Force
    Write-Ok "Restored .env from backup"
}

# 6. Re-run the installer. It reuses .venv, verifies pinned versions, preserves
#    data\models, and never downloads the AI model during installation.
$InstallScript = Join-Path $RootDir "install.ps1"
if (-not (Test-Path $InstallScript)) {
    Fail "install.ps1 is missing from $RootDir."
}

$InstallArgs = @("-NonInteractive", "-TorchMode", $TorchMode)
if ($NoLaunch.IsPresent) {
    $InstallArgs += "-NoLaunch"
}

Write-Info "Refreshing dependencies and validating the installation..."
& $InstallScript @InstallArgs
if (-not $?) {
    Fail "The update installer reported an error. Review the messages above, then rerun .\update.ps1."
}

Write-Host ""
if ($ModelCacheExisted) {
    Write-Ok "Existing AI model cache in data\models was preserved."
} else {
    Write-Info "No model cache exists yet; the AI model will download on first video-processing use."
}
Write-Ok "Your .env configuration and data\ contents were preserved."
Write-Host ""
Write-Host "Update complete!" -ForegroundColor Green
if ($NoLaunch.IsPresent) {
    Write-Host "Start the application with: .\start.ps1" -ForegroundColor Cyan
}
Write-Host ""
