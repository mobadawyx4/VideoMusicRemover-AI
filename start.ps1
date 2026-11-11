<#
.SYNOPSIS
    SilentTrack AI — One-Command Windows PowerShell Startup Script
.DESCRIPTION
    Verifies installation, starts the FastAPI backend on http://127.0.0.1:8000
    and the React/Vite frontend on http://localhost:5173, checks health,
    opens the default browser, and runs until stopped.
#>
[CmdletBinding()]
param(
    [switch]$Lan,
    [switch]$NoBrowser,
    [switch]$Detach
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.FullName
Set-Location $RootDir

$BundledFfmpegDir = Join-Path $RootDir "tools\ffmpeg"
if (Test-Path $BundledFfmpegDir) {
    $env:Path = "$BundledFfmpegDir;$env:Path"
}

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
$ViteCmd    = Join-Path $RootDir "frontend\node_modules\.bin\vite.cmd"
$RuntimeDir = Join-Path $RootDir ".runtime"

# 1. Verify installation
if (-not (Test-Path $VenvPython) -or -not (Test-Path $ViteCmd)) {
    Write-Host "[INFO] First-time setup required. Running .\install.ps1..." -ForegroundColor Yellow
    & (Join-Path $RootDir "install.ps1")
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

# Load .env settings if present
$EnvFile = Join-Path $RootDir ".env"
$EnableLanFromEnv = $false
$BackendPort = 8000
$FrontendPort = 5173

if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $parts = $trimmed -split "=", 2
        if ($parts.Length -eq 2) {
            $k = $parts[0].Trim()
            $v = $parts[1].Trim().Trim('"').Trim("'")
            if ($k -eq "ENABLE_LAN_ACCESS" -and ($v -eq "true" -or $v -eq "1")) {
                $EnableLanFromEnv = $true
            }
            if ($k -eq "PORT" -and ($v -as [int])) {
                $BackendPort = [int]$v
            }
            if ($k -eq "FRONTEND_PORT" -and ($v -as [int])) {
                $FrontendPort = [int]$v
            }
        }
    }
}

$LanMode = $Lan.IsPresent -or $EnableLanFromEnv
$BackendHost = "127.0.0.1"
$FrontendHost = if ($LanMode) { "0.0.0.0" } else { "127.0.0.1" }

# Clean up any stale PIDs before starting
if ((Test-Path (Join-Path $RuntimeDir "backend.pid")) -or (Test-Path (Join-Path $RuntimeDir "frontend.pid"))) {
    & (Join-Path $RootDir "stop.ps1") | Out-Null
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting SilentTrack AI" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan

# 2. Start FastAPI Backend
Write-Host "[1/4] Starting FastAPI backend on http://${BackendHost}:${BackendPort}..." -ForegroundColor Cyan
$env:PYTHONPATH = Join-Path $RootDir "backend"
$BackendLogOut = Join-Path $RuntimeDir "backend.out.log"
$BackendLogErr = Join-Path $RuntimeDir "backend.err.log"

$BackendProc = Start-Process -FilePath $VenvPython `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $BackendHost, "--port", "$BackendPort") `
    -WorkingDirectory (Join-Path $RootDir "backend") `
    -RedirectStandardOutput $BackendLogOut `
    -RedirectStandardError $BackendLogErr `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path (Join-Path $RuntimeDir "backend.pid") -Value $BackendProc.Id -NoNewline

# 3. Start React/Vite Frontend
Write-Host "[2/4] Starting React/Vite frontend on http://localhost:${FrontendPort}..." -ForegroundColor Cyan
$FrontendLogOut = Join-Path $RuntimeDir "frontend.out.log"
$FrontendLogErr = Join-Path $RuntimeDir "frontend.err.log"
$env:VITE_DEV_HOST = $FrontendHost
$env:VITE_DEV_PORT = "$FrontendPort"
$env:VITE_BACKEND_ORIGIN = "http://127.0.0.1:${BackendPort}"

$FrontendProc = Start-Process -FilePath $ViteCmd `
    -ArgumentList @("--host", $FrontendHost, "--port", "$FrontendPort") `
    -WorkingDirectory (Join-Path $RootDir "frontend") `
    -RedirectStandardOutput $FrontendLogOut `
    -RedirectStandardError $FrontendLogErr `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path (Join-Path $RuntimeDir "frontend.pid") -Value $FrontendProc.Id -NoNewline

# 4. Check Backend Health
Write-Host "[3/4] Verifying backend API health (http://127.0.0.1:${BackendPort}/api/health)..." -ForegroundColor Cyan
$BackendReady = $false
for ($i = 0; $i -lt 40; $i++) {
    if ($BackendProc.HasExited) {
        Write-Host "[ERROR] Backend process exited unexpectedly." -ForegroundColor Red
        if (Test-Path $BackendLogErr) { Get-Content $BackendLogErr -Tail 20 | Write-Host }
        & (Join-Path $RootDir "stop.ps1") | Out-Null
        exit 1
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:${BackendPort}/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $BackendReady = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if (-not $BackendReady) {
    Write-Host "[ERROR] Backend did not pass health check in time." -ForegroundColor Red
    & (Join-Path $RootDir "stop.ps1") | Out-Null
    exit 1
}
Write-Host "  [OK] Backend API is healthy" -ForegroundColor Green

# 5. Check Frontend Availability
Write-Host "[4/4] Verifying frontend availability (http://localhost:${FrontendPort})..." -ForegroundColor Cyan
$FrontendReady = $false
for ($i = 0; $i -lt 40; $i++) {
    if ($FrontendProc.HasExited) {
        Write-Host "[ERROR] Frontend process exited unexpectedly." -ForegroundColor Red
        if (Test-Path $FrontendLogErr) { Get-Content $FrontendLogErr -Tail 20 | Write-Host }
        & (Join-Path $RootDir "stop.ps1") | Out-Null
        exit 1
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:${FrontendPort}" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $FrontendReady = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if (-not $FrontendReady) {
    Write-Host "[ERROR] Frontend did not become ready in time." -ForegroundColor Red
    & (Join-Path $RootDir "stop.ps1") | Out-Null
    exit 1
}
Write-Host "  [OK] Frontend server is online" -ForegroundColor Green

Write-Host ""
Write-Host "SUCCESS:" -ForegroundColor Green
Write-Host "SilentTrack AI is ready!" -ForegroundColor White
Write-Host ""
Write-Host "Open:"
Write-Host "  http://localhost:${FrontendPort}" -ForegroundColor Cyan
Write-Host ""
Write-Host "Backend API:    http://127.0.0.1:${BackendPort}"
Write-Host "Health Check:   http://127.0.0.1:${BackendPort}/api/health"

if ($LanMode) {
    try {
        $LanIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1).IPAddress
        if ($LanIp) {
            Write-Host "LAN Access URL: http://${LanIp}:${FrontendPort}" -ForegroundColor Cyan
        }
    } catch {}
}
Write-Host ""

# Open default browser automatically
if (-not $NoBrowser.IsPresent -and -not $Detach.IsPresent) {
    try {
        Start-Process "http://localhost:${FrontendPort}" | Out-Null
    } catch {}
}

if ($Detach.IsPresent) {
    Write-Host "Services are running in the background. Stop them anytime with: .\stop.ps1" -ForegroundColor Cyan
    exit 0
}

Write-Host "Press Ctrl+C to stop SilentTrack AI (or run .\stop.ps1 in another PowerShell window)." -ForegroundColor Yellow

try {
    while (-not $BackendProc.HasExited -and -not $FrontendProc.HasExited) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host ""
    & (Join-Path $RootDir "stop.ps1")
}
