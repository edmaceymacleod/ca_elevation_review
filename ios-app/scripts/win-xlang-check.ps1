<#
.SYNOPSIS
    Run the kit <-> engine schema cross-check on Windows (the PC mirror of the
    `xlang_schema` CI job).

.DESCRIPTION
    Emits the Swift kit's CapturePackage + SpecManifest samples as JSON via the
    `cek-emit` executable (which encodes the shared CaElevationFixtures with the
    kit's own BundleIO.makeEncoder), then validates them against the
    AUTHORITATIVE engine JSON Schemas with engine/tools/validate_schemas.py. This
    catches Swift <-> engine-schema drift the kit's self-only round-trip tests
    cannot see.

    Swift on Windows needs the same two things win-kit-test.ps1 sets up:
      1. The MSVC linker + Windows SDK (Enter-VsDevShell).
      2. SDKROOT + the toolchain on PATH (installer-set USER env vars).

    The Python side needs only `jsonschema` (NOT the engine: installing the
    engine makes validate_schemas.py's registered-golden check assert the
    engine's goldens exist under our kit-samples dir and fail -- engine-free, that
    check degrades to a harmless NOTE). Pass -Python to point at the interpreter
    that has jsonschema (e.g. your engine venv); it defaults to `python`.

.NOTES
    One-time installs (already done on the main dev machine):
        winget install --id Swift.Toolchain -e
        pip install jsonschema            # into the interpreter you pass as -Python
    Then run from anywhere:
        pwsh -File ios-app/scripts/win-xlang-check.ps1
        pwsh -File ios-app/scripts/win-xlang-check.ps1 -Python C:\path\to\venv\Scripts\python.exe
#>
[CmdletBinding()]
param(
    [string]$Python = 'python'  # interpreter that has `jsonschema` (e.g. engine venv)
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent  # ios-app/scripts -> repo root
$iosApp = Join-Path $repoRoot 'ios-app'

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
$env:PATH = "$([Environment]::GetEnvironmentVariable('PATH','User'));$env:PATH"

# --- 3. Preflight: the Python validator needs jsonschema -----------------------
& $Python -c "import jsonschema" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "jsonschema not importable by '$Python'. Activate your engine venv or pass -Python <interpreter that has jsonschema>."
}

Write-Host "Swift   : $((Get-Command swift.exe).Source)"
Write-Host "Python  : $((Get-Command $Python).Source)"
& swift.exe --version

# --- 4. Emit the kit samples ---------------------------------------------------
$samples = Join-Path ([System.IO.Path]::GetTempPath()) "cek-xlang-$(New-Guid)"
Set-Location $iosApp

Write-Host "`n=== swift run cek-emit ===" -ForegroundColor Cyan
& swift.exe run cek-emit "$samples" kit_sample
if ($LASTEXITCODE -ne 0) { throw "cek-emit failed ($LASTEXITCODE)" }

# Fail-closed: the validator exits 0 on an empty dir, so prove both files exist.
$capture = Join-Path $samples 'kit_sample.capture.json'
$manifest = Join-Path $samples 'kit_sample.manifest.json'
if (-not (Test-Path $capture) -or ((Get-Item $capture).Length -eq 0)) { throw "missing/empty $capture" }
if (-not (Test-Path $manifest) -or ((Get-Item $manifest).Length -eq 0)) { throw "missing/empty $manifest" }

# --- 5. Validate against the authoritative engine schemas ----------------------
Write-Host "`n=== validate_schemas.py ===" -ForegroundColor Cyan
& $Python (Join-Path $repoRoot 'engine\tools\validate_schemas.py') --fixtures "$samples" --strict-unknown -v
if ($LASTEXITCODE -ne 0) { throw "schema validation failed ($LASTEXITCODE)" }

Remove-Item -Recurse -Force $samples -ErrorAction SilentlyContinue
Write-Host "`nkit <-> engine schema cross-check OK on Windows." -ForegroundColor Green
