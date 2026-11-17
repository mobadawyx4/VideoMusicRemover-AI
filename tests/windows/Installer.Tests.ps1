<#
.SYNOPSIS
    Pester smoke tests for the VideoMusicRemover AI Windows scripts.

.DESCRIPTION
    These tests validate PowerShell parsing and the Windows installer contract.
    They do not install packages or start the application.

    Run on Windows (or PowerShell 7 on any OS) with:
        Install-Module Pester -Scope CurrentUser -MinimumVersion 5.0
        Invoke-Pester .\tests\windows\Installer.Tests.ps1
#>

Describe "VideoMusicRemover AI Windows scripts" {
    BeforeAll {
        $candidate = $PSScriptRoot
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            $candidate = Split-Path -Parent $MyInvocation.MyCommand.Path
        }

        $resolved = $null
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $parent = Split-Path -Parent $candidate
            if ($parent) {
                $resolved = Split-Path -Parent $parent
            }
        }

        if ([string]::IsNullOrWhiteSpace($resolved) -or
            -not (Test-Path (Join-Path $resolved "install.ps1"))) {
            $resolved = (Get-Location).Path
            while (-not (Test-Path (Join-Path $resolved "install.ps1"))) {
                $next = Split-Path -Parent $resolved
                if ([string]::IsNullOrWhiteSpace($next) -or $next -eq $resolved) {
                    break
                }
                $resolved = $next
            }
        }

        $RepoRoot = $resolved
        $WindowsScripts = @("install.ps1", "start.ps1", "stop.ps1", "update.ps1")
    }

    It "resolves the repository root" {
        $RepoRoot | Should -Not -BeNullOrEmpty
        Test-Path (Join-Path $RepoRoot "install.ps1") | Should -BeTrue
    }

    It "all Windows PowerShell scripts parse without errors" {
        foreach ($scriptName in $WindowsScripts) {
            $scriptPath = Join-Path $RepoRoot $scriptName
            Test-Path $scriptPath | Should -BeTrue

            $tokens = $null
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $scriptPath,
                [ref]$tokens,
                [ref]$errors
            ) | Out-Null

            $errors.Count | Should -Be 0 -Because "$scriptName must contain valid PowerShell"
        }
    }

    It "installer checks Windows architecture and 64-bit Python" {
        $content = Get-Content (Join-Path $RepoRoot "install.ps1") -Raw
        $content | Should -Match "Is64BitOperatingSystem"
        $content | Should -Match "PROCESSOR_ARCHITECTURE"
        $content | Should -Match "AMD64"
        $content | Should -Match "3\.10.*3\.11.*3\.12|3\.10-3\.12|3\.10–3\.12"
    }

    It "installer supports automatic prerequisite installation" {
        $content = Get-Content (Join-Path $RepoRoot "install.ps1") -Raw
        $content | Should -Match "Python\.Python\.3\.12"
        $content | Should -Match "OpenJS\.NodeJS\.LTS"
        $content | Should -Match "Gyan\.FFmpeg"
        $content | Should -Match "AutoInstallPrerequisites"
        $content | Should -Match "winget"
    }

    It "installer selects CPU or verified CUDA PyTorch 2.5.1" {
        $content = Get-Content (Join-Path $RepoRoot "install.ps1") -Raw
        $content | Should -Match "download\.pytorch\.org/whl/cpu"
        $content | Should -Match "download\.pytorch\.org/whl/cu121"
        $content | Should -Match "torch==2\.5\.1\+cpu"
        $content | Should -Match "torch==2\.5\.1\+cu121"
        $content | Should -Match "torch\.cuda\.is_available"
        $content | Should -Match "torch\.version\.cuda"
        $content | Should -Match "TorchMode"
    }

    It "installer verifies CUDA and can fall back to a CPU-only build" {
        $content = Get-Content (Join-Path $RepoRoot "install.ps1") -Raw
        $content | Should -Match "cuda_available"
        $content | Should -Match "Test-CudaCapability"
        $content | Should -Match "CPU fallback"
        $content | Should -Match "cuda_version"
    }

    It "installer validates the lazy model cache without downloading weights" {
        $content = Get-Content (Join-Path $RepoRoot "install.ps1") -Raw
        $content | Should -Match "is_model_available"
        $content | Should -Not -Match "ensure_model_cached"
        $content | Should -Match "downloads automatically on your first video-processing run"
    }

    It "installer verifies npm dependencies instead of trusting vite.cmd" {
        $content = Get-Content (Join-Path $RepoRoot "install.ps1") -Raw
        $content | Should -Match "npm ls"
        $content | Should -Match "package-lock\.json"
        $content | Should -Match "npm ci|npm install"
    }

    It "installer checks disk space and dependency versions" {
        $content = Get-Content (Join-Path $RepoRoot "install.ps1") -Raw
        $content | Should -Match "Insufficient disk space"
        $content | Should -Match "check_requirements\.py"
    }

    It "first-run start invokes the installer without recursive launch" {
        $content = Get-Content (Join-Path $RepoRoot "start.ps1") -Raw
        $content | Should -Match '"install\.ps1"\) -NoLaunch'
        $content | Should -Match "Installation did not complete successfully"
    }

    It "update guards local changes and preserves user data" {
        $content = Get-Content (Join-Path $RepoRoot "update.ps1") -Raw
        $content | Should -Match "git status --porcelain"
        $content | Should -Match "data\\models"
        $content | Should -Match "preserved"
        $content | Should -Match "\.env"
        $content | Should -Match "NoPull"
    }

    It "scripts do not change execution policy or Windows security settings" {
        foreach ($scriptName in $WindowsScripts) {
            $content = Get-Content (Join-Path $RepoRoot $scriptName) -Raw
            $content | Should -Not -Match "Set-ExecutionPolicy"
            $content | Should -Not -Match "Set-MpPreference"
            $content | Should -Not -Match "Add-MpPreference"
            $content | Should -Not -Match "DisableRealtimeMonitoring"
        }
    }
}
