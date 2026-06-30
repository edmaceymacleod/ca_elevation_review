<#
.SYNOPSIS
    Build and test the pure CaElevationKit SwiftPM package on Windows.

.DESCRIPTION
    CaElevationKit is Foundation-only (no UIKit/ARKit/SwiftUI), so it builds and
    unit-tests on the Swift.org Windows toolchain -- the same suite CI runs on
    macOS/Linux. The SwiftUI/ARKit app layer (Sources/CaElevationApp) is NOT
    buildable here; that is Mac + device only.

    Two things the Swift Windows toolchain needs that a plain terminal lacks:
      1. The MSVC linker + Windows SDK (for linking). We enter the Visual Studio
         Developer environment via Enter-VsDevShell so link.exe + headers/libs
         are on PATH. Requires VS 2022 (any edition) with the "Desktop
         development with C++" workload.
      2. SDKROOT + the toolchain on PATH. The winget Swift.Toolchain installer
         sets these as USER environment variables; a session that predates the
         install won't have inherited them, so we read them explicitly.

.NOTES
    One-time install (already done on the main dev machine):
        winget install --id Swift.Toolchain -e
    Then run this script from anywhere:
        pwsh -File ios-app/scripts/win-kit-test.ps1
#>
[CmdletBinding()]
param(
    [switch]$BuildOnly  # skip `swift test`, just `swift build`
)

$ErrorActionPreference = 'Stop'

# --- 1. Visual Studio developer environment (MSVC linker + Windows SDK) --------
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "vswhere not found. Install Visual Studio 2022 with the 'Desktop development with C++' workload."
}
$vsPath = & $vswhere -latest -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
if (-not $vsPath) {
    throw "No VS install with the C++ toolchain (VC.Tools.x86.x64) found."
}
Import-Module (Join-Path $vsPath "Common7\Tools\Microsoft.VisualStudio.DevShell.dll")
Enter-VsDevShell -VsInstallPath $vsPath -SkipAutomaticLocation `
    -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null

# --- 2. Swift toolchain env (installer-set USER vars, version-agnostic) --------
$sdkRoot = [Environment]::GetEnvironmentVariable('SDKROOT', 'User')
if (-not $sdkRoot) {
    throw "SDKROOT not set. Install the Swift toolchain: winget install --id Swift.Toolchain -e"
}
$env:SDKROOT = $sdkRoot
# Prepend the installer's USER PATH (Swift toolchain bin + runtime DLLs).
$env:PATH = "$([Environment]::GetEnvironmentVariable('PATH','User'));$env:PATH"

Write-Host "Swift   : $((Get-Command swift.exe).Source)"
Write-Host "SDKROOT : $env:SDKROOT"
& swift.exe --version

# --- 3. Build + test the kit ---------------------------------------------------
$pkgDir = Join-Path (Split-Path $PSScriptRoot -Parent) ''  # ios-app/
Set-Location $pkgDir

Write-Host "`n=== swift build ===" -ForegroundColor Cyan
& swift.exe build
if ($LASTEXITCODE -ne 0) { throw "swift build failed ($LASTEXITCODE)" }

if (-not $BuildOnly) {
    Write-Host "`n=== swift test ===" -ForegroundColor Cyan
    & swift.exe test
    if ($LASTEXITCODE -ne 0) { throw "swift test failed ($LASTEXITCODE)" }
}

Write-Host "`nCaElevationKit: build + test OK on Windows." -ForegroundColor Green
