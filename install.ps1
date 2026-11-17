<#
.SYNOPSIS
    VideoMusicRemover AI — Automated Windows PowerShell Installer
.DESCRIPTION
    Supports Windows 10 and Windows 11 (64-bit x64). Detects and verifies
    Python 3.10–3.12 (64-bit), Node.js/npm, FFmpeg/FFprobe, and NVIDIA driver
    compatibility. Missing prerequisites can be installed through the official
    Winget source when the user allows it. Creates or reuses .venv, installs the
    compatible PyTorch 2.5.1 CPU or CUDA 12.1 build, verifies pinned Python and
    npm dependencies, checks the lazy TIGER-DnR model cache without downloading
    it, and validates the complete installation.
.PARAMETER AutoInstallFfmpeg
    Allow Winget to install FFmpeg/FFprobe without prompting.
.PARAMETER AutoInstallPrerequisites
    Allow Winget to install any missing supported prerequisites without
    prompting. Winget may show a Windows UAC permission prompt.
.PARAMETER NonInteractive
    Never prompt. Missing prerequisites are installed only when
    -AutoInstallPrerequisites (or -AutoInstallFfmpeg for FFmpeg) is also set.
.PARAMETER NoLaunch
    Finish installation without starting the application.
.PARAMETER TorchMode
    Auto (default) selects CUDA 12.1 when a compatible NVIDIA driver is found,
    otherwise CPU. CPU forces the CPU build. CUDA requires a compatible NVIDIA
    driver and fails clearly instead of silently falling back.
.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -AutoInstallPrerequisites -NonInteractive -NoLaunch
.EXAMPLE
    .\install.ps1 -TorchMode CPU
#>
[CmdletBinding()]
param(
    [switch]$AutoInstallFfmpeg,
    [switch]$AutoInstallPrerequisites,
    [switch]$NonInteractive,
    [switch]$NoLaunch,
    [ValidateSet("Auto", "CPU", "CUDA")]
    [string]$TorchMode = "Auto"
)

$ErrorActionPreference = "Stop"
$script:RootDir = Split-Path -Parent $MyInvocation.MyCommand.FullName
Set-Location $script:RootDir

$script:BundledFfmpegDir = Join-Path $script:RootDir "tools\ffmpeg"
$script:PythonIssues = New-Object System.Collections.ArrayList
$script:NodeIssue = ""
$script:Nvidia = $null
$venvDir = Join-Path $script:RootDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

trap {
    Write-Host ""
    Write-Host "[ERROR] Installation stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Review the message above, correct the issue, and rerun .\install.ps1." -ForegroundColor Yellow
    Write-Host "If the problem persists, see the Windows troubleshooting section in README.md." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

function Update-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($script:BundledFfmpegDir, $env:Path, $machinePath, $userPath) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $unique = foreach ($part in $parts) {
        if ($seen.Add($part)) { $part }
    }
    $env:Path = ($unique -join ";")
}

Update-ProcessPath

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
function Write-Detail($Text) {
    Write-Host "       $Text" -ForegroundColor DarkGray
}

function Fail {
    param(
        [string]$Message,
        [string[]]$Hints = @()
    )
    Write-Host ""
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    if ($Hints.Count -gt 0) {
        Write-Host ""
        Write-Host "What to do next:" -ForegroundColor Yellow
        foreach ($hint in $Hints) {
            Write-Host "  - $hint" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    exit 1
}

function Confirm-Yes {
    param(
        [string]$Prompt,
        [bool]$DefaultYes = $true
    )
    if ($NonInteractive.IsPresent) {
        return $false
    }
    $suffix = if ($DefaultYes) { "(Y/n)" } else { "(y/N)" }
    try {
        $reply = Read-Host "$Prompt $suffix"
    } catch {
        return $false
    }
    if ([string]::IsNullOrWhiteSpace($reply)) {
        return $DefaultYes
    }
    return ($reply.Trim() -match "^y(es)?$")
}

function Confirm-AutomaticInstall {
    param(
        [string]$Label,
        [switch]$FfmpegSpecific
    )
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        # Manual instructions are printed by the caller; do not offer an
        # automatic install that cannot run.
        return $false
    }
    if ($AutoInstallPrerequisites.IsPresent) {
        return $true
    }
    if ($FfmpegSpecific.IsPresent -and $AutoInstallFfmpeg.IsPresent) {
        return $true
    }
    if ($NonInteractive.IsPresent) {
        return $false
    }
    return (Confirm-Yes "Install $Label automatically using Winget now?")
}

function Install-WingetPackage {
    param(
        [string]$Id,
        [string]$Label
    )
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Warn "Winget is not available on this computer."
        return $false
    }

    $wingetExe = if ($winget.Source) { $winget.Source } else { $winget.Name }
    Write-Info "Installing $Label from the official Winget source (package: $Id)..."
    Write-Detail "Winget may show a Windows permission prompt (UAC). This comes from the package installer, not from VideoMusicRemover AI."

    $arguments = @(
        "install",
        "--id", $Id,
        "-e",
        "--source", "winget",
        "--accept-source-agreements",
        "--accept-package-agreements"
    )
    if ($NonInteractive.IsPresent) {
        $arguments += "--silent"
    }

    & $wingetExe @arguments
    $exitCode = $LASTEXITCODE
    Update-ProcessPath

    if ($exitCode -ne 0) {
        Write-Warn "Winget could not install $Label (exit code $exitCode)."
        return $false
    }
    Write-Ok "$Label installed"
    return $true
}

function Get-PythonInfo {
    param(
        [string]$Executable,
        [string[]]$Arguments = @()
    )
    if ([string]::IsNullOrWhiteSpace($Executable)) {
        return $null
    }
    $code = "import json,struct,sys; print(json.dumps({'major':sys.version_info.major,'minor':sys.version_info.minor,'bits':struct.calcsize('P')*8,'executable':sys.executable}))"
    try {
        $output = & $Executable @Arguments -c $code 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) {
            return $null
        }
        $line = [string]($output | Select-Object -Last 1)
        if ([string]::IsNullOrWhiteSpace($line)) {
            return $null
        }
        return ($line | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Find-Python {
    $candidates = New-Object System.Collections.ArrayList
    [void]$candidates.Add(@{ Exe = "py"; Arguments = @("-3.12") })
    [void]$candidates.Add(@{ Exe = "py"; Arguments = @("-3.11") })
    [void]$candidates.Add(@{ Exe = "py"; Arguments = @("-3.10") })
    [void]$candidates.Add(@{ Exe = "python"; Arguments = @() })
    [void]$candidates.Add(@{ Exe = "python3"; Arguments = @() })

    $knownPaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python310\python.exe")
    )
    foreach ($knownPath in $knownPaths) {
        if ($knownPath -and (Test-Path $knownPath -PathType Leaf)) {
            [void]$candidates.Add(@{ Exe = $knownPath; Arguments = @() })
        }
    }

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) {
            continue
        }
        $info = Get-PythonInfo -Executable $candidate.Exe -Arguments $candidate.Arguments
        if (-not $info) {
            continue
        }
        $version = "$($info.major).$($info.minor)"
        $supported = @("3.10", "3.11", "3.12")
        if (($version -in $supported) -and ($info.bits -eq 64)) {
            return @{
                Exe = $candidate.Exe
                Arguments = $candidate.Arguments
                Version = $version
                Bits = $info.bits
                Executable = $info.executable
            }
        }
        $issue = "$version ($($info.bits)-bit)"
        if ($script:PythonIssues -notcontains $issue) {
            [void]$script:PythonIssues.Add($issue)
        }
    }
    return $null
}

function Test-NodeVersion {
    param([int]$Major)
    return (($Major -eq 18) -or ($Major -eq 20) -or ($Major -ge 22))
}

function Find-Node {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        $script:NodeIssue = "Node.js was not found in PATH."
        return $null
    }

    $nodeExe = if ($node.Source) { $node.Source } else { $node.Name }
    $versionText = [string](& $nodeExe --version 2>$null | Select-Object -First 1)
    $versionText = $versionText.Trim()
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch "^v?(\d+)\.(\d+)\.(\d+)") {
        $script:NodeIssue = "Node.js was found but its version could not be read."
        return $null
    }
    $major = [int]$Matches[1]
    if (-not (Test-NodeVersion -Major $major)) {
        $script:NodeIssue = "Node.js $versionText is not supported by Vite 6. Use an LTS release (18, 20, or 22+)."
        return $null
    }

    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
    }
    if (-not $npm) {
        $script:NodeIssue = "npm was not found. Reinstall Node.js LTS to restore npm."
        return $null
    }

    return @{
        Node = $nodeExe
        Npm = if ($npm.Source) { $npm.Source } else { $npm.Name }
        Version = $versionText
    }
}

function Test-Executable {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path -PathType Leaf)) {
        return $false
    }
    try {
        & $Path -version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Test-NpmDependencies {
    param(
        [string]$NpmPath,
        [string]$FrontendDirectory
    )
    if ([string]::IsNullOrWhiteSpace($NpmPath) -or -not (Test-Path $FrontendDirectory)) {
        return $false
    }
    Push-Location $FrontendDirectory
    try {
        # npm ls validates that the installed tree matches package.json and the
        # lockfile; the presence of vite.cmd alone is not proof of a valid tree.
        & $NpmPath ls --depth=0 --silent *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        Pop-Location
    }
}

function Resolve-Ffmpeg {
    $systemFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $systemFfprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($systemFfmpeg -and $systemFfprobe) {
        $ffmpegPath = $systemFfmpeg.Source
        $ffprobePath = $systemFfprobe.Source
        if ((Test-Executable $ffmpegPath) -and (Test-Executable $ffprobePath)) {
            return @{ Ffmpeg = $ffmpegPath; Ffprobe = $ffprobePath; Source = "system PATH" }
        }
    }

    $bundledFfmpeg = Join-Path $script:BundledFfmpegDir "ffmpeg.exe"
    $bundledFfprobe = Join-Path $script:BundledFfmpegDir "ffprobe.exe"
    if ((Test-Executable $bundledFfmpeg) -and (Test-Executable $bundledFfprobe)) {
        return @{ Ffmpeg = $bundledFfmpeg; Ffprobe = $bundledFfprobe; Source = "bundled tools\ffmpeg" }
    }

    return $null
}

function Get-NvidiaStatus {
    $gpu = @()
    try {
        $gpu = @(Get-CimInstance -ClassName Win32_VideoController -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "NVIDIA" })
    } catch {
        $gpu = @()
    }

    $gpuName = if ($gpu.Count -gt 0) { [string]$gpu[0].Name } else { "" }
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) {
        return @{
            Present = ($gpu.Count -gt 0)
            Usable = $false
            Name = $gpuName
            Driver = ""
            Reason = if ($gpu.Count -gt 0) {
                "An NVIDIA GPU was detected, but nvidia-smi is unavailable. Install or update the NVIDIA driver to use GPU acceleration."
            } else {
                "No NVIDIA GPU was detected."
            }
        }
    }

    $smiExe = if ($smi.Source) { $smi.Source } else { $smi.Name }
    try {
        $name = [string](& $smiExe --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
        $driverText = [string](& $smiExe --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($driverText)) {
            throw "nvidia-smi did not return a usable GPU and driver version."
        }
        $driverVersion = [version]$driverText.Trim()
        $minimumDriver = [version]"527.41"
        if ($driverVersion -lt $minimumDriver) {
            return @{
                Present = $true
                Usable = $false
                Name = $name.Trim()
                Driver = $driverVersion.ToString()
                Reason = "NVIDIA driver $driverVersion is older than the CUDA 12.1 minimum (527.41). Update the NVIDIA driver to enable GPU acceleration."
            }
        }
        return @{
            Present = $true
            Usable = $true
            Name = $name.Trim()
            Driver = $driverVersion.ToString()
            Reason = ""
        }
    } catch {
        return @{
            Present = ($gpu.Count -gt 0)
            Usable = $false
            Name = $gpuName
            Driver = ""
            Reason = "The NVIDIA driver is present but CUDA support could not be verified. Update the NVIDIA driver or use CPU mode."
        }
    }
}

function Get-TorchInfo {
    param([string]$PythonPath)
    $code = @'
import json
import torch

info = {
    "version": torch.__version__,
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_version": torch.version.cuda or "",
    "capability": "",
}
if info["cuda_available"]:
    try:
        major, minor = torch.cuda.get_device_capability(0)
        info["capability"] = "%d.%d" % (major, minor)
    except Exception:
        info["capability"] = ""
print(json.dumps(info))
'@
    try {
        $output = & $PythonPath -c $code 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) {
            return $null
        }
        $line = [string]($output | Select-Object -Last 1)
        if ([string]::IsNullOrWhiteSpace($line)) {
            return $null
        }
        return ($line | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Test-TorchBaseVersion {
    param([string]$Version)
    return ($Version -match "^2\.5\.1(\+.*)?$")
}

function Test-CudaCapability {
    param([string]$Capability)
    if ([string]::IsNullOrWhiteSpace($Capability)) {
        # cuda.is_available() already succeeded; do not reject an unknown
        # capability value that the driver reported inconsistently.
        return $true
    }
    $parts = $Capability.Split(".")
    $major = 0
    if (-not [int]::TryParse($parts[0], [ref]$major)) {
        return $true
    }
    # CUDA 12.1 requires Maxwell (compute capability 5.0) or newer.
    return ($major -ge 5)
}

function Install-PyTorch {
    param(
        [string]$PythonPath,
        [bool]$Cuda
    )
    $indexUrl = if ($Cuda) {
        "https://download.pytorch.org/whl/cu121"
    } else {
        "https://download.pytorch.org/whl/cpu"
    }
    $label = if ($Cuda) { "CUDA 12.1" } else { "CPU" }
    # Pin the local build label so pip replaces a different variant (for example
    # switching from a CUDA build to the CPU build) instead of treating
    # "torch==2.5.1" as already satisfied.
    $package = if ($Cuda) { "torch==2.5.1+cu121" } else { "torch==2.5.1+cpu" }

    Write-Info "Installing official PyTorch 2.5.1 ($label build)..."
    Write-Detail "Source: $indexUrl"
    Write-Detail "This download can take several minutes on a slow connection."

    & $PythonPath -m pip install $package --index-url $indexUrl
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    return $true
}

function Test-BackendRequirements {
    param(
        [string]$PythonPath,
        [string]$RequirementsFile,
        [switch]$ShowDetails
    )
    $checker = Join-Path $script:RootDir "scripts\check_requirements.py"
    if (-not (Test-Path $checker -PathType Leaf)) {
        Fail "The dependency verifier is missing: $checker" @(
            "Restore scripts\check_requirements.py from the project repository.",
            "Then rerun .\install.ps1."
        )
    }

    if ($ShowDetails.IsPresent) {
        & $PythonPath $checker $RequirementsFile
    } else {
        & $PythonPath $checker $RequirementsFile *> $null
    }
    return ($LASTEXITCODE -eq 0)
}

$existingVenvInfo = $null
$venvUsable = $false
if (Test-Path $venvPython -PathType Leaf) {
    $existingVenvInfo = Get-PythonInfo -Executable $venvPython
    if ($existingVenvInfo) {
        $existingVenvVersion = "$($existingVenvInfo.major).$($existingVenvInfo.minor)"
        $venvUsable = (($existingVenvVersion -in @("3.10", "3.11", "3.12")) -and ($existingVenvInfo.bits -eq 64))
    }
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VideoMusicRemover AI — Automated Windows Installation" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Local AI video music removal with speech and ambience preservation." -ForegroundColor Gray
Write-Host ""

if ($PSVersionTable.PSVersion.Major -lt 5) {
    Fail "Windows PowerShell 5.1 or newer is required." @(
        "Open Windows PowerShell 5.1 or PowerShell 7 and run .\install.ps1 again."
    )
}

# ----------------------------------------------------------------------------
# [1/5] Checking prerequisites...
# ----------------------------------------------------------------------------
Write-Step "[1/5] Checking prerequisites..."

$osVersion = [Environment]::OSVersion.Version
$osCaption = [Environment]::OSVersion.VersionString
try {
    $cimOs = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue
    if ($cimOs -and $cimOs.Caption) {
        $osCaption = "$($cimOs.Caption) (Build $($cimOs.BuildNumber))"
    }
} catch {}

if ($osVersion.Major -lt 10) {
    Fail "VideoMusicRemover AI supports Windows 10 and Windows 11 (64-bit x64)." @(
        "This computer reports: $osCaption",
        "Upgrade to a supported 64-bit Windows version before installing."
    )
}
if (-not [Environment]::Is64BitOperatingSystem) {
    Fail "A 64-bit version of Windows is required." @(
        "This computer is running a 32-bit edition of Windows.",
        "VideoMusicRemover AI and PyTorch require 64-bit Windows."
    )
}
$processArchitecture = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) {
    $processArchitecture = $env:PROCESSOR_ARCHITEW6432
}
if ($processArchitecture -ne "AMD64") {
    Fail "Windows on ARM ($processArchitecture) is not supported by the required PyTorch 2.5.1 wheels." @(
        "Use a 64-bit x64 Windows 10 or Windows 11 computer.",
        "If this is an x64 computer, run the installer from a native x64 PowerShell window."
    )
}
Write-Ok "Windows: $osCaption (x64)"

$driveRoot = (Get-Item $script:RootDir).PSDrive.Name
$freeMb = $null
try {
    $driveInfo = Get-PSDrive -Name $driveRoot -ErrorAction SilentlyContinue
    if ($driveInfo -and $driveInfo.Free) {
        $freeMb = [math]::Round($driveInfo.Free / 1MB, 0)
    }
} catch {}
if ($null -ne $freeMb) {
    if ($freeMb -lt 2000) {
        Fail "Insufficient disk space ($freeMb MB free on drive ${driveRoot}:)." @(
            "Free at least 2 GB for the Python environment and frontend dependencies.",
            "The AI model also needs additional free space when it downloads on first use."
        )
    }
    Write-Ok "Free disk space: $freeMb MB"
    if ($freeMb -lt 6000) {
        Write-Warn "CUDA installations and the AI model cache may need more free space. 6 GB or more is recommended."
    }
}

# Python 3.10-3.12, 64-bit. A valid existing .venv can be reused without a system Python.
$pythonInfo = Find-Python
if (-not $pythonInfo -and -not $venvUsable) {
    if ($script:PythonIssues.Count -gt 0) {
        Write-Warn "A Python installation was found, but it is not supported: $($script:PythonIssues -join ', ')."
    }
    Write-Host ""
    Write-Host "Python 3.10, 3.11, or 3.12 (64-bit) is required." -ForegroundColor Yellow
    Write-Host "  Official downloads: https://www.python.org/downloads/windows/" -ForegroundColor Gray
    Write-Host "  Winget package:     Python.Python.3.12" -ForegroundColor Gray

    $canInstall = Confirm-AutomaticInstall -Label "Python 3.12 (64-bit)"
    if ($canInstall) {
        [void](Install-WingetPackage -Id "Python.Python.3.12" -Label "Python 3.12")
        Start-Sleep -Seconds 1
        $pythonInfo = Find-Python
    }

    if (-not $pythonInfo -and -not $venvUsable) {
        Fail "No supported 64-bit Python 3.10, 3.11, or 3.12 installation was found." @(
            "Install the 64-bit Python 3.12 installer from https://www.python.org/downloads/windows/ and enable 'Add Python to PATH'.",
            "Or run: winget install --id Python.Python.3.12 -e",
            "Close and reopen PowerShell, then run .\install.ps1 again."
        )
    }
}
if ($pythonInfo) {
    Write-Ok "Python $($pythonInfo.Version) (64-bit): $($pythonInfo.Executable)"
} elseif ($venvUsable) {
    Write-Ok "Existing .venv with Python $($existingVenvInfo.major).$($existingVenvInfo.minor) (64-bit) will be reused"
    Write-Detail "A system Python installation is not required when the existing environment is valid."
}

# Node.js and npm
$nodeInfo = Find-Node
if (-not $nodeInfo) {
    Write-Warn $script:NodeIssue
    Write-Host ""
    Write-Host "Node.js LTS and npm are required for the React/Vite frontend." -ForegroundColor Yellow
    Write-Host "  Official downloads: https://nodejs.org/en/download" -ForegroundColor Gray
    Write-Host "  Winget package:     OpenJS.NodeJS.LTS" -ForegroundColor Gray

    $canInstall = Confirm-AutomaticInstall -Label "Node.js LTS"
    if ($canInstall) {
        [void](Install-WingetPackage -Id "OpenJS.NodeJS.LTS" -Label "Node.js LTS")
        Start-Sleep -Seconds 1
        $nodeInfo = Find-Node
    }

    if (-not $nodeInfo) {
        Fail "Node.js LTS (18, 20, or 22+) and npm are required." @(
            "Install Node.js LTS from https://nodejs.org/en/download/.",
            "Or run: winget install --id OpenJS.NodeJS.LTS -e",
            "Close and reopen PowerShell, then run .\install.ps1 again."
        )
    }
}
Write-Ok "Node.js $($nodeInfo.Version): $($nodeInfo.Node)"

# FFmpeg and FFprobe
$ffmpegInfo = Resolve-Ffmpeg
if (-not $ffmpegInfo) {
    Write-Warn "FFmpeg / FFprobe were not found in PATH or tools\ffmpeg as working Windows executables."
    Write-Host ""
    Write-Host "FFmpeg and FFprobe are required for video/audio processing." -ForegroundColor Yellow
    Write-Host "  Official project and download links: https://ffmpeg.org/download.html" -ForegroundColor Gray
    Write-Host "  Winget package:                     Gyan.FFmpeg" -ForegroundColor Gray
    Write-Host "  Bundled fallback:                   $script:BundledFfmpegDir\ffmpeg.exe and ffprobe.exe" -ForegroundColor Gray

    $canInstall = Confirm-AutomaticInstall -Label "FFmpeg and FFprobe" -FfmpegSpecific
    if ($canInstall) {
        [void](Install-WingetPackage -Id "Gyan.FFmpeg" -Label "FFmpeg and FFprobe")
        Start-Sleep -Seconds 1
        $ffmpegInfo = Resolve-Ffmpeg
    }

    if (-not $ffmpegInfo) {
        Fail "FFmpeg and FFprobe are required before continuing." @(
            "Install FFmpeg and FFprobe, then reopen PowerShell and rerun .\install.ps1.",
            "Or place ffmpeg.exe and ffprobe.exe in $script:BundledFfmpegDir.",
            "Do not place the Linux ffmpeg/ffprobe binaries in tools\ffmpeg on Windows."
        )
    }
}
Write-Ok "FFmpeg: $($ffmpegInfo.Ffmpeg) [$($ffmpegInfo.Source)]"
Write-Ok "FFprobe: $($ffmpegInfo.Ffprobe)"

# NVIDIA detection. A GPU alone does not guarantee CUDA compatibility.
$script:Nvidia = Get-NvidiaStatus
if ($script:Nvidia.Usable) {
    Write-Ok "NVIDIA GPU: $($script:Nvidia.Name) (driver $($script:Nvidia.Driver))"
} elseif ($script:Nvidia.Present) {
    Write-Warn "NVIDIA GPU detected, but CUDA 12.1 is not currently usable."
    Write-Detail $script:Nvidia.Reason
} else {
    Write-Info "No NVIDIA GPU detected. CPU acceleration will be used."
}

# ----------------------------------------------------------------------------
# [2/5] Setting up Python environment...
# ----------------------------------------------------------------------------
Write-Step "[2/5] Setting up Python environment..."

if (Test-Path $venvPython -PathType Leaf) {
    $venvInfo = Get-PythonInfo -Executable $venvPython
    if (-not $venvInfo) {
        Fail "The existing .venv folder cannot be used because its Python executable is invalid." @(
            "Rename or move the .venv folder to keep it as a backup.",
            "Then rerun .\install.ps1 to create a clean environment.",
            "No files were deleted by this installer."
        )
    }
    $venvVersion = "$($venvInfo.major).$($venvInfo.minor)"
    if (($venvVersion -notin @("3.10", "3.11", "3.12")) -or ($venvInfo.bits -ne 64)) {
        Fail "The existing .venv uses Python $venvVersion ($($venvInfo.bits)-bit), which is not supported." @(
            "Rename or move the .venv folder to keep it as a backup.",
            "Then rerun .\install.ps1 to create a new 64-bit Python 3.10–3.12 environment.",
            "No files were deleted by this installer."
        )
    }
    Write-Ok "Reusing existing .venv with Python $venvVersion (64-bit)"
} else {
    Write-Info "Creating .venv with Python $($pythonInfo.Version) (64-bit)..."
    & $pythonInfo.Exe @($pythonInfo.Arguments) -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython -PathType Leaf)) {
        Fail "Could not create the Python virtual environment at .venv." @(
            "Confirm that Python $($pythonInfo.Version) is installed correctly and has the venv module.",
            "Check that the project folder is writable.",
            "Then run .\install.ps1 again."
        )
    }
    Write-Ok "Created .venv with Python $($pythonInfo.Version) (64-bit)"
}

& $venvPython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Info "Repairing pip inside .venv..."
    & $venvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        Fail "pip is unavailable inside .venv." @(
            "Rename or move the .venv folder, then rerun .\install.ps1.",
            "No files were deleted by this installer."
        )
    }
}
Write-Ok "pip is available inside .venv"

$envFile = Join-Path $script:RootDir ".env"
$envExample = Join-Path $script:RootDir ".env.example"
if (Test-Path $envFile) {
    Write-Ok "Existing .env configuration found (preserved)"
} elseif (Test-Path $envExample) {
    Copy-Item $envExample $envFile
    Write-Ok "Created .env from .env.example (defaulting to localhost)"
}

New-Item -ItemType Directory -Force -Path (Join-Path $script:RootDir "data\jobs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $script:RootDir "data\models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $script:RootDir ".runtime") | Out-Null

# ----------------------------------------------------------------------------
# [3/5] Installing backend dependencies...
# ----------------------------------------------------------------------------
Write-Step "[3/5] Installing backend dependencies..."

$useCuda = $false
$requestedDescription = ""
switch ($TorchMode) {
    "CPU" {
        $useCuda = $false
        $requestedDescription = "CPU was requested explicitly."
    }
    "CUDA" {
        if (-not $script:Nvidia.Usable) {
            Fail "CUDA mode was requested, but a compatible NVIDIA GPU and driver were not detected." @(
                $script:Nvidia.Reason,
                "Update the NVIDIA driver to version 527.41 or newer for CUDA 12.1.",
                "Then rerun: .\install.ps1 -TorchMode CUDA",
                "Or rerun without -TorchMode to use automatic CPU fallback."
            )
        }
        $useCuda = $true
        $requestedDescription = "CUDA mode was requested explicitly."
    }
    default {
        if ($script:Nvidia.Usable) {
            $useCuda = $true
            $requestedDescription = "Automatic mode selected CUDA 12.1."
        } else {
            $useCuda = $false
            $requestedDescription = "Automatic mode selected CPU."
        }
    }
}

if ($useCuda) {
    Write-Info "PyTorch mode: NVIDIA CUDA 12.1 (PyTorch 2.5.1)"
    Write-Detail $requestedDescription
} else {
    Write-Info "PyTorch mode: CPU (PyTorch 2.5.1)"
    Write-Detail $requestedDescription
}

$torchInfo = Get-TorchInfo -PythonPath $venvPython
$torchBaseOk = ($torchInfo -and (Test-TorchBaseVersion -Version $torchInfo.version))
$torchCompatible = $false
if ($torchBaseOk) {
    if ($useCuda) {
        $torchCompatible = ($torchInfo.cuda_available) -and
            ($torchInfo.cuda_version -like "12.1*") -and
            (Test-CudaCapability -Capability $torchInfo.capability)
    } else {
        # An empty cuda_version identifies the CPU build; a CUDA build that
        # simply cannot see a GPU should still be replaced with the CPU build.
        $torchCompatible = (-not $torchInfo.cuda_available) -and
            [string]::IsNullOrEmpty([string]$torchInfo.cuda_version)
    }
}

if ($torchCompatible) {
    if ($torchInfo.cuda_available) {
        Write-Ok "Compatible PyTorch $($torchInfo.version) with CUDA $($torchInfo.cuda_version) already present"
    } else {
        Write-Ok "Compatible PyTorch $($torchInfo.version) CPU build already present"
    }
} else {
    if ($torchInfo) {
        Write-Info "Existing PyTorch $($torchInfo.version) does not match the selected mode; installing PyTorch 2.5.1."
    } else {
        Write-Info "PyTorch is not installed in .venv yet."
    }
    $torchInstalled = Install-PyTorch -PythonPath $venvPython -Cuda $useCuda
    if (-not $torchInstalled) {
        if ($useCuda -and $TorchMode -ne "CUDA") {
            Write-Warn "The CUDA PyTorch installation failed. Falling back to the official CPU build."
            $useCuda = $false
            $torchInstalled = Install-PyTorch -PythonPath $venvPython -Cuda $false
        }
    }
    if (-not $torchInstalled) {
        Fail "PyTorch 2.5.1 installation failed." @(
            "Check your internet connection and free disk space.",
            "Confirm that pip can access https://download.pytorch.org/.",
            "Then rerun .\install.ps1.",
            "If corporate security software blocks the download, allow download.pytorch.org temporarily."
        )
    }

    $torchInfo = Get-TorchInfo -PythonPath $venvPython
    if (-not $torchInfo -or -not (Test-TorchBaseVersion -Version $torchInfo.version)) {
        Fail "PyTorch 2.5.1 could not be verified after installation." @(
            "Run: .venv\Scripts\python.exe -m pip show torch",
            "Then rerun .\install.ps1 or open an issue with the output."
        )
    }

    $cudaRuntimeOk = ($torchInfo.cuda_available) -and
        ($torchInfo.cuda_version -like "12.1*") -and
        (Test-CudaCapability -Capability $torchInfo.capability)
    if ($useCuda -and -not $cudaRuntimeOk) {
        if ($TorchMode -eq "CUDA") {
            Fail "PyTorch was installed, but CUDA is not usable at runtime." @(
                "Update the NVIDIA driver to version 527.41 or newer.",
                "This GPU must support compute capability 5.0 (Maxwell) or newer for CUDA 12.1.",
                "Close other GPU-heavy applications and rerun: .\install.ps1 -TorchMode CUDA",
                "Or use CPU fallback by running .\install.ps1 without -TorchMode."
            )
        }
        Write-Warn "CUDA was selected but PyTorch cannot access the GPU. Installing the CPU build as a safe fallback."
        $useCuda = $false
        $torchInstalled = Install-PyTorch -PythonPath $venvPython -Cuda $false
        if (-not $torchInstalled) {
            Fail "The CPU fallback PyTorch installation failed." @(
                "Check your internet connection and rerun .\install.ps1.",
                "You can also run: .venv\Scripts\python.exe -m pip install torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu"
            )
        }
        $torchInfo = Get-TorchInfo -PythonPath $venvPython
        if (-not $torchInfo -or -not (Test-TorchBaseVersion -Version $torchInfo.version)) {
            Fail "The CPU fallback could not be verified." @(
                "Run: .venv\Scripts\python.exe -m pip show torch",
                "Then rerun .\install.ps1."
            )
        }
        if ($torchInfo.cuda_available -or -not [string]::IsNullOrEmpty([string]$torchInfo.cuda_version)) {
            Fail "The CPU fallback did not produce a CPU-only PyTorch build." @(
                "Run: .venv\Scripts\python.exe -m pip install torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu",
                "Then rerun .\install.ps1 and confirm that torch.cuda.is_available() is False and torch.version.cuda is None."
            )
        }
        Write-Ok "CPU-only PyTorch build verified after fallback (CUDA disabled)"
    }
}

if ($useCuda -and ((-not $torchInfo.cuda_available) -or ($torchInfo.cuda_version -notlike "12.1*"))) {
    Fail "The selected CUDA mode does not match the installed PyTorch build." @(
        "Run: .venv\Scripts\python.exe -c ""import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)""",
        "Then rerun .\install.ps1 -TorchMode CUDA or allow automatic CPU fallback."
    )
}
if (-not $useCuda -and ($torchInfo.cuda_available -or -not [string]::IsNullOrEmpty([string]$torchInfo.cuda_version))) {
    Fail "The selected CPU mode does not match the installed PyTorch build." @(
        "An existing CUDA-enabled PyTorch installation is still active.",
        "Run: .venv\Scripts\python.exe -m pip install torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu",
        "Then rerun .\install.ps1."
    )
}
if ($torchInfo.cuda_available) {
    Write-Ok "Acceleration selected: NVIDIA CUDA (PyTorch $($torchInfo.version), CUDA $($torchInfo.cuda_version))"
} else {
    Write-Ok "Acceleration selected: CPU (PyTorch $($torchInfo.version))"
}

$requirementsFile = Join-Path $script:RootDir "backend\requirements.txt"
$requirementsStamp = Join-Path $venvDir ".requirements.sha256"
$currentRequirementsHash = (Get-FileHash -Path $requirementsFile -Algorithm SHA256).Hash
$installedRequirementsHash = if (Test-Path $requirementsStamp) {
    (Get-Content $requirementsStamp -Raw).Trim()
} else {
    ""
}

$requirementsSatisfied = Test-BackendRequirements -PythonPath $venvPython -RequirementsFile $requirementsFile
if ($requirementsSatisfied) {
    if ($currentRequirementsHash -ne $installedRequirementsHash) {
        Set-Content -Path $requirementsStamp -Value $currentRequirementsHash -NoNewline
    }
    Write-Ok "Backend Python packages verified against backend\requirements.txt"
} else {
    Write-Info "Installing or updating backend Python packages from backend\requirements.txt..."
    & $venvPython -m pip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
        Fail "Backend Python dependency installation failed." @(
            "Check your internet connection and free disk space.",
            "Run this command for details: .venv\Scripts\python.exe -m pip install -r backend\requirements.txt",
            "Then rerun .\install.ps1."
        )
    }
    $requirementsSatisfied = Test-BackendRequirements -PythonPath $venvPython -RequirementsFile $requirementsFile -ShowDetails
    if (-not $requirementsSatisfied) {
        Fail "Backend Python packages are still incomplete after installation." @(
            "Review the missing package names printed above.",
            "Run: .venv\Scripts\python.exe -m pip install -r backend\requirements.txt",
            "Then rerun .\install.ps1."
        )
    }
    Set-Content -Path $requirementsStamp -Value $currentRequirementsHash -NoNewline
    Write-Ok "Backend Python dependencies installed and verified"
}

Write-Info "Checking TIGER-DnR AI audio separation model cache..."
$env:PYTHONPATH = Join-Path $script:RootDir "backend"
$modelStatus = [string](& $venvPython -c "from app.services.separation import separator_service; print('cached' if separator_service.is_model_available() else 'pending')" 2>$null | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0) {
    Fail "The AI model status check failed because the backend could not be imported." @(
        "Run: .venv\Scripts\python.exe -c ""import sys; sys.path.insert(0, 'backend'); import app.main""",
        "Review any Python error above, then rerun .\install.ps1."
    )
}
if ($modelStatus.Trim() -eq "cached") {
    Write-Ok "TIGER-DnR AI model weights already cached locally (preserved)"
} else {
    Write-Ok "No model download during installation"
    Write-Host "       The TIGER-DnR AI model downloads automatically on your first video-processing run." -ForegroundColor Cyan
    Write-Host "       It is cached in data\models and reused offline on later runs." -ForegroundColor Gray
}

# ----------------------------------------------------------------------------
# [4/5] Installing frontend dependencies...
# ----------------------------------------------------------------------------
Write-Step "[4/5] Installing frontend dependencies..."

$frontendDir = Join-Path $script:RootDir "frontend"
$lockFile = Join-Path $frontendDir "package-lock.json"
if (-not (Test-Path $lockFile)) {
    $lockFile = Join-Path $frontendDir "package.json"
}
$npmStamp = Join-Path $frontendDir "node_modules\.package.sha256"
$viteBin = Join-Path $frontendDir "node_modules\.bin\vite.cmd"
$currentNpmHash = (Get-FileHash -Path $lockFile -Algorithm SHA256).Hash
$installedNpmHash = if (Test-Path $npmStamp) {
    (Get-Content $npmStamp -Raw).Trim()
} else {
    ""
}

$npmTreeValid = (Test-Path $viteBin) -and
    (Test-NpmDependencies -NpmPath $nodeInfo.Npm -FrontendDirectory $frontendDir)

if ($npmTreeValid -and ($currentNpmHash -eq $installedNpmHash)) {
    Write-Ok "Frontend npm dependencies are installed, verified, and match package-lock.json"
} elseif ($npmTreeValid -and [string]::IsNullOrEmpty($installedNpmHash)) {
    Set-Content -Path $npmStamp -Value $currentNpmHash -NoNewline
    Write-Ok "Verified existing frontend node_modules with npm ls"
} else {
    if (Test-Path $viteBin) {
        Write-Info "Existing frontend node_modules failed verification; repairing with npm..."
    } else {
        Write-Info "Installing frontend npm packages in frontend\..."
    }

    $hasLockFile = (Test-Path $lockFile) -and
        ((Split-Path -Leaf $lockFile) -eq "package-lock.json")
    $installArgs = if ($hasLockFile -and -not (Test-Path (Join-Path $frontendDir "node_modules"))) {
        # A clean, reproducible install when node_modules is absent. npm ci is
        # only used here so an existing user node_modules tree is never deleted.
        @("ci", "--no-audit", "--no-fund", "--prefer-offline")
    } else {
        @("install", "--no-audit", "--no-fund", "--prefer-offline")
    }

    Push-Location $frontendDir
    try {
        & $nodeInfo.Npm @installArgs
        if ($LASTEXITCODE -ne 0) {
            Fail "npm $($installArgs[0]) failed in the frontend directory." @(
                "Check your internet connection and free disk space.",
                "Run this command for details: cd frontend; npm $($installArgs[0]) --no-audit --no-fund",
                "Then rerun .\install.ps1."
            )
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-NpmDependencies -NpmPath $nodeInfo.Npm -FrontendDirectory $frontendDir)) {
        Fail "npm finished, but the frontend dependency tree is still inconsistent." @(
            "Run: cd frontend; npm ci --no-audit --no-fund",
            "Then rerun .\install.ps1."
        )
    }
    Set-Content -Path $npmStamp -Value $currentNpmHash -NoNewline
    Write-Ok "Frontend npm dependencies installed and verified"
}

# ----------------------------------------------------------------------------
# [5/5] Validating installation...
# ----------------------------------------------------------------------------
Write-Step "[5/5] Validating installation..."

$env:PYTHONPATH = Join-Path $script:RootDir "backend"
& $venvPython -c "
import torch
from app.main import app
from app.core.config import settings
from app.services.media_service import check_ffmpeg_installed
from app.services.separation import separator_service

assert torch.__version__.split('+')[0] == '2.5.1', f'Unexpected PyTorch version: {torch.__version__}'
ff_ok, fp_ok = check_ffmpeg_installed()
assert ff_ok and fp_ok, 'FFmpeg or FFprobe validation failed'
print('  [OK] FastAPI application and routes verified')
print('  [OK] FFmpeg and FFprobe integration verified')
print(f'  [OK] FFmpeg path: {settings.FFMPEG_PATH}')
print(f'  [OK] PyTorch {torch.__version__} verified')
if torch.cuda.is_available():
    print(f'  [OK] CUDA runtime available through PyTorch (CUDA {torch.version.cuda})')
else:
    print('  [OK] CPU runtime verified (no CUDA device in use)')
if separator_service.is_model_available():
    print('  [OK] TIGER-DnR AI model weights found in local cache')
else:
    print('  [INFO] TIGER-DnR AI model will download on first use')
"
if ($LASTEXITCODE -ne 0) {
    Fail "Backend validation failed." @(
        "Review the error printed above.",
        "Run: .venv\Scripts\python.exe -c ""import sys; sys.path.insert(0, 'backend'); import app.main""",
        "Then rerun .\install.ps1."
    )
}

if (-not (Test-Path $viteBin)) {
    Fail "The frontend Vite binary was not found in frontend\node_modules\.bin." @(
        "Run: cd frontend; npm install --no-audit --no-fund",
        "Then rerun .\install.ps1."
    )
}
Write-Ok "React + Vite frontend verified"

Write-Host ""
Write-Host "SUCCESS:" -ForegroundColor Green
Write-Host "VideoMusicRemover AI installation completed!" -ForegroundColor White
Write-Host "VideoMusicRemover AI is ready!" -ForegroundColor Green
Write-Host ""
Write-Host "Installation summary:" -ForegroundColor White
if ($torchInfo.cuda_available) {
    Write-Host "  Acceleration: NVIDIA CUDA ($($torchInfo.cuda_version))" -ForegroundColor Green
} else {
    Write-Host "  Acceleration: CPU" -ForegroundColor Green
}
Write-Host "  Python:       $venvPython"
Write-Host "  FFmpeg:       $($ffmpegInfo.Ffmpeg)"
Write-Host "  AI model:     downloads automatically on first video-processing run"
Write-Host "  Model cache:  data\models (preserved across updates)"
Write-Host ""

if (-not $NoLaunch.IsPresent) {
    Write-Host "Starting the application automatically..." -ForegroundColor Cyan
    Write-Host ""
    & (Join-Path $script:RootDir "start.ps1")
} else {
    Write-Host "Installation completed without launching." -ForegroundColor Cyan
    Write-Host "To start later, run: .\start.ps1" -ForegroundColor Cyan
    Write-Host "Application URL: http://localhost:5173" -ForegroundColor Cyan
}
Write-Host ""
