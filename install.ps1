<#
.SYNOPSIS
    SilentTrack AI — Automated Windows PowerShell Installer
.DESCRIPTION
    Detects Windows version, verifies Python 3.10–3.12, Node.js, npm, and FFmpeg/FFprobe,
    offers Winget installation if FFmpeg is missing, creates .venv, installs backend and
    frontend dependencies without unnecessary reinstalls, caches the TIGER-DnR AI model,
    and validates the complete installation.
#>
[CmdletBinding()]
param(
    [switch]$AutoInstallFfmpeg,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.FullName
Set-Location $RootDir

# Prepend bundled tools\ffmpeg to PATH if present
$BundledFfmpegDir = Join-Path $RootDir "tools\ffmpeg"
if (Test-Path $BundledFfmpegDir) {
    $env:Path = "$BundledFfmpegDir;$env:Path"
}

function Write-Step($Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor White
}
function Write-Info($Text) {
    Write-Host "[INFO] $Text" -ForegroundColor Cyan
}
function Write-Ok($Text) {
    Write-Host "  [OK] $Text" -ForegroundColor Green
}
function Write-Warn($Text) {
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}
function Exit-WithError($Text) {
    Write-Host ""
    Write-Host "[ERROR] $Text" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SilentTrack AI — Automated Windows Installation" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan

# ----------------------------------------------------------------------------
# [1/5] Checking prerequisites...
# ----------------------------------------------------------------------------
Write-Step "[1/5] Checking prerequisites..."

# 1. Detect Windows version
$OsCaption = [System.Environment]::OSVersion.VersionString
try {
    $CimOs = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue
    if ($CimOs -and $CimOs.Caption) {
        $OsCaption = "$($CimOs.Caption) (Build $($CimOs.BuildNumber))"
    }
} catch {}
Write-Ok "Detected Windows version: $OsCaption"

# Check available disk space (require >= 500 MB)
try {
    $DriveRoot = (Get-Item $RootDir).PSDrive.Name
    $DriveInfo = Get-PSDrive -Name $DriveRoot -ErrorAction SilentlyContinue
    if ($DriveInfo -and $DriveInfo.Free) {
        $FreeMb = [math]::Round($DriveInfo.Free / 1MB, 0)
        if ($FreeMb -lt 500) {
            Exit-WithError "Insufficient disk space ($FreeMb MB free on drive ${DriveRoot}:). At least 500 MB is required."
        }
        Write-Ok "Available disk space: $FreeMb MB"
    }
} catch {}

# 2. Check Python 3.10–3.12
$PythonCmd = $null
$PythonArgs = @()

$Candidates = @(
    @{ Exe = "py"; Args = @("-3.12") },
    @{ Exe = "py"; Args = @("-3.11") },
    @{ Exe = "py"; Args = @("-3.10") },
    @{ Exe = "python"; Args = @() },
    @{ Exe = "python3"; Args = @() }
)

foreach ($cand in $Candidates) {
    $cmdObj = Get-Command $cand.Exe -ErrorAction SilentlyContinue
    if ($cmdObj) {
        try {
            $verOut = & $cand.Exe @($cand.Args) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and ($verOut -in @("3.10", "3.11", "3.12"))) {
                $PythonCmd = $cand.Exe
                $PythonArgs = $cand.Args
                $PythonFullVer = & $cand.Exe @($cand.Args) --version 2>&1
                break
            }
        } catch {}
    }
}

if (-not $PythonCmd) {
    Write-Host ""
    Write-Host "Helpful instructions to install Python 3.12 on Windows:" -ForegroundColor Yellow
    Write-Host "  Option A (Winget):   winget install --id Python.Python.3.12 -e"
    Write-Host "  Option B (Download): https://www.python.org/downloads/"
    Write-Host "  (Important: Check 'Add Python to PATH' during installation)"
    Exit-WithError "Python 3.10, 3.11, or 3.12 was not found."
}
Write-Ok "Found $PythonFullVer"

# 3. Check Node.js and npm
$NodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $NodeCmd) {
    Write-Host ""
    Write-Host "Helpful instructions to install Node.js LTS on Windows:" -ForegroundColor Yellow
    Write-Host "  Option A (Winget):   winget install --id OpenJS.NodeJS.LTS -e"
    Write-Host "  Option B (Download): https://nodejs.org/"
    Exit-WithError "Node.js is not installed or not in PATH."
}
$NodeVer = & node --version 2>&1
Write-Ok "Found Node.js $NodeVer"

$NpmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $NpmCmd) {
    $NpmCmd = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $NpmCmd) {
    Exit-WithError "npm was not found in PATH. Please reinstall Node.js LTS from https://nodejs.org/."
}
$NpmVer = & $NpmCmd.Source --version 2>&1
Write-Ok "Found npm v$NpmVer"

# 4. Check FFmpeg and FFprobe (offer Winget installation if missing)
function Test-FfmpegAvailable {
    $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $fp = Get-Command ffprobe -ErrorAction SilentlyContinue
    return ($null -ne $ff) -and ($null -ne $fp)
}

if (-not (Test-FfmpegAvailable)) {
    Write-Warn "FFmpeg / FFprobe was not found in PATH or tools\ffmpeg."
    $WingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($WingetCmd) {
        $ShouldInstall = $AutoInstallFfmpeg.IsPresent
        if (-not $ShouldInstall -and -not $NonInteractive.IsPresent) {
            $Reply = Read-Host "Would you like to install FFmpeg automatically via Winget now? (Y/n)"
            if ([string]::IsNullOrWhiteSpace($Reply) -or $Reply -match "^[Yy]") {
                $ShouldInstall = $true
            }
        }
        if ($ShouldInstall) {
            Write-Info "Installing FFmpeg via Winget (Gyan.FFmpeg)..."
            & winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
            # Refresh PATH from Windows registry
            $MachinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
            $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
            $env:Path = "$BundledFfmpegDir;$MachinePath;$UserPath"
        }
    }
}

if (-not (Test-FfmpegAvailable)) {
    Write-Host ""
    Write-Host "Helpful instructions to install FFmpeg on Windows:" -ForegroundColor Yellow
    Write-Host "  1. Run in PowerShell:  winget install --id Gyan.FFmpeg -e"
    Write-Host "  2. Close and reopen PowerShell so the updated PATH takes effect."
    Write-Host "  3. Or place ffmpeg.exe and ffprobe.exe inside: $BundledFfmpegDir"
    Exit-WithError "FFmpeg and FFprobe are required before continuing."
}
Write-Ok "Found FFmpeg ($( (Get-Command ffmpeg).Source ))"
Write-Ok "Found FFprobe ($( (Get-Command ffprobe).Source ))"

# ----------------------------------------------------------------------------
# [2/5] Setting up Python environment...
# ----------------------------------------------------------------------------
Write-Step "[2/5] Setting up Python environment..."

$VenvDir = Join-Path $RootDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (Test-Path $VenvPython) {
    Write-Ok "Existing Python virtual environment detected at .venv (reusing)"
} else {
    Write-Info "Creating Python virtual environment at .venv..."
    & $PythonCmd @PythonArgs -m venv $VenvDir
    if (-not (Test-Path $VenvPython)) {
        Exit-WithError "Failed to create Python virtual environment at .venv."
    }
    Write-Ok "Created Python virtual environment at .venv"
}

$EnvFile = Join-Path $RootDir ".env"
$EnvExample = Join-Path $RootDir ".env.example"
if (Test-Path $EnvFile) {
    Write-Ok "Existing .env configuration found (preserved)"
} elseif (Test-Path $EnvExample) {
    Copy-Item $EnvExample $EnvFile
    Write-Ok "Created .env from .env.example (defaulting to localhost)"
}

New-Item -ItemType Directory -Force -Path (Join-Path $RootDir "data\jobs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RootDir "data\models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RootDir ".runtime") | Out-Null

# ----------------------------------------------------------------------------
# [3/5] Installing backend dependencies...
# ----------------------------------------------------------------------------
Write-Step "[3/5] Installing backend dependencies..."

$ReqFile = Join-Path $RootDir "backend\requirements.txt"
$ReqStamp = Join-Path $VenvDir ".requirements.sha256"
$CurrentReqHash = (Get-FileHash -Path $ReqFile -Algorithm SHA256).Hash
$InstalledReqHash = if (Test-Path $ReqStamp) { (Get-Content $ReqStamp -Raw).Trim() } else { "" }

$ImportsOk = $false
try {
    & $VenvPython -c "import fastapi, uvicorn, torch, soundfile, huggingface_hub, safetensors, aiofiles, pytest, httpx" 2>$null
    if ($LASTEXITCODE -eq 0) { $ImportsOk = $true }
} catch {}

if ($ImportsOk -and ($CurrentReqHash -eq $InstalledReqHash)) {
    Write-Ok "Backend Python dependencies are already installed and up to date"
} elseif ($ImportsOk -and [string]::IsNullOrEmpty($InstalledReqHash)) {
    Set-Content -Path $ReqStamp -Value $CurrentReqHash -NoNewline
    Write-Ok "Verified existing backend Python packages in .venv"
} else {
    Write-Info "Installing Python packages from backend\requirements.txt..."
    & $VenvPython -m pip install --upgrade pip | Out-Null
    & $VenvPython -m pip install -r $ReqFile
    if ($LASTEXITCODE -ne 0) {
        Exit-WithError "Failed to install backend Python dependencies."
    }
    Set-Content -Path $ReqStamp -Value $CurrentReqHash -NoNewline
    Write-Ok "Installed backend Python dependencies"
}

Write-Info "Verifying TIGER-DnR AI audio separation model cache..."
$env:PYTHONPATH = Join-Path $RootDir "backend"
& $VenvPython -c "from app.services.separation import separator_service; snap = separator_service.ensure_model_cached(); print(f'  [OK] AI model ready in local cache: {snap}')"
if ($LASTEXITCODE -ne 0) {
    Exit-WithError "AI model verification/download failed. Check your internet connection or disk space."
}

# ----------------------------------------------------------------------------
# [4/5] Installing frontend dependencies...
# ----------------------------------------------------------------------------
Write-Step "[4/5] Installing frontend dependencies..."

$FrontendDir = Join-Path $RootDir "frontend"
$LockFile = Join-Path $FrontendDir "package-lock.json"
if (-not (Test-Path $LockFile)) {
    $LockFile = Join-Path $FrontendDir "package.json"
}
$NpmStamp = Join-Path $FrontendDir "node_modules\.package.sha256"
$ViteBin = Join-Path $FrontendDir "node_modules\.bin\vite.cmd"
$CurrentNpmHash = (Get-FileHash -Path $LockFile -Algorithm SHA256).Hash
$InstalledNpmHash = if (Test-Path $NpmStamp) { (Get-Content $NpmStamp -Raw).Trim() } else { "" }

if ((Test-Path $ViteBin) -and ($CurrentNpmHash -eq $InstalledNpmHash)) {
    Write-Ok "Frontend npm dependencies are already installed and up to date"
} elseif ((Test-Path $ViteBin) -and [string]::IsNullOrEmpty($InstalledNpmHash)) {
    Set-Content -Path $NpmStamp -Value $CurrentNpmHash -NoNewline
    Write-Ok "Verified existing frontend node_modules"
} else {
    Write-Info "Installing frontend npm packages in frontend\..."
    Push-Location $FrontendDir
    try {
        & $NpmCmd.Source install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            Exit-WithError "npm install failed in frontend directory."
        }
    } finally {
        Pop-Location
    }
    Set-Content -Path $NpmStamp -Value $CurrentNpmHash -NoNewline
    Write-Ok "Installed frontend npm dependencies"
}

# ----------------------------------------------------------------------------
# [5/5] Validating installation...
# ----------------------------------------------------------------------------
Write-Step "[5/5] Validating installation..."

$env:PYTHONPATH = Join-Path $RootDir "backend"
& $VenvPython -c "
from app.main import app
from app.services.media_service import check_ffmpeg_installed
from app.services.separation import separator_service
ff_ok, fp_ok = check_ffmpeg_installed()
assert ff_ok and fp_ok, 'FFmpeg or FFprobe validation failed'
assert separator_service.is_model_available(), 'TIGER-DnR model cache validation failed'
print('  [OK] FastAPI application & routes verified')
print('  [OK] FFmpeg & FFprobe integration verified')
print(f'  [OK] TIGER-DnR AI model verified (device: {separator_service.device})')
"
if ($LASTEXITCODE -ne 0) {
    Exit-WithError "Backend validation check failed."
}

if (-not (Test-Path $ViteBin)) {
    Exit-WithError "Frontend Vite binary was not found in frontend\node_modules\.bin."
}
Write-Ok "React + Vite frontend verified"

Write-Host ""
Write-Host "SUCCESS:" -ForegroundColor Green
Write-Host "SilentTrack AI is ready!" -ForegroundColor White
Write-Host ""
Write-Host "Start the application with:"
Write-Host "  .\start.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Open:"
Write-Host "  http://localhost:5173" -ForegroundColor Cyan
Write-Host ""
