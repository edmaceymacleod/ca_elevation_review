<#
.SYNOPSIS
    Lint the Swift sources on Windows with the SAME gate CI runs on macOS:
    `swiftlint lint --strict --config .swiftlint.yml`.

.DESCRIPTION
    The PC mirror of the GATING SwiftLint step in the "CaElevationKit (macos)" CI
    job (.github/workflows/ci.yml). Run it before pushing so a Windows dev gets
    the same pass/fail CI will give -- no surprise red on a macOS-only gate.

    What this needs that a plain terminal lacks, and what it deliberately does NOT:
      1. The Swift toolchain bin on PATH. SwiftLint analyses via SourceKit
         (sourcekitdInProc.dll), which ships in the Swift TOOLCHAIN -- not in the
         swiftlint install. With only swiftlint on PATH it HARD-CRASHES at startup
         ("Loading sourcekitdInProc.dll failed", 0xC0000409). The winget
         Swift.Toolchain installer puts its bin on the USER PATH; a shell that
         predates the install won't have inherited it, so we prepend the USER PATH
         explicitly. The same prepend also brings swiftlint.exe (installed onto the
         USER PATH). No hardcoded paths -- everything resolves via PATH.
      2. (Optional) SDKROOT. Unlike win-kit-test.ps1 / win-xlang-check.ps1, this
         script does NOT link, and SwiftLint's active rule set is SwiftSyntax-based,
         so SDKROOT is not required (verified: swiftlint lints clean with it unset).
         We set it defensively if the installer's USER var is present, but never
         throw on its absence.
      3. NO Visual Studio dev shell. `swiftlint lint` never invokes the MSVC
         linker, so -- unlike the build/test scripts -- we skip Enter-VsDevShell.

    LINE ENDINGS: SwiftLint on Windows counts CR and LF separately, so on a CRLF
    checkout every file trips false comma / trailing_newline / file_length (2x line
    count) violations. The repo's root .gitattributes (eol=lf) forces LF on
    checkout to match CI. If you still see these on a working tree that predates
    .gitattributes, do the one-time re-smudge in ios-app/CLAUDE.md "Platform
    gotchas".

    VERSION PARITY CAVEAT: CI installs SwiftLint via `brew install swiftlint`
    (floats to latest); this script uses whatever swiftlint.exe is on your PATH.
    The version is printed below -- if CI ever flags something this passes, suspect
    a SwiftLint version drift between the two.

.NOTES
    One-time installs (already done on the main dev machine):
        winget install --id Swift.Toolchain -e
        # plus swiftlint.exe on the USER PATH (e.g. ~\tools\swiftlint)
    Then run from anywhere:
        pwsh -File ios-app/scripts/win-swiftlint.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# --- 1. Swift toolchain on PATH (SourceKit) + optional SDKROOT -----------------
# Prepend the installer's USER PATH: brings the Swift toolchain bin (for
# sourcekitdInProc.dll) AND swiftlint.exe. Version-agnostic, no hardcoded paths.
$env:PATH = "$([Environment]::GetEnvironmentVariable('PATH','User'));$env:PATH"

# SDKROOT is optional for linting (we don't link); set it only if the installer
# left it as a USER var. Never throw -- swiftlint lints clean without it.
$sdkRoot = [Environment]::GetEnvironmentVariable('SDKROOT', 'User')
if ($sdkRoot) { $env:SDKROOT = $sdkRoot }

# Fail fast with a clear message if SourceKit cannot be found, instead of letting
# swiftlint hard-crash (0xC0000409) deep inside SourceKittenFramework.
$sourcekit = $env:PATH -split ';' |
    Where-Object { $_ } |
    ForEach-Object { Join-Path $_ 'sourcekitdInProc.dll' } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1
if (-not $sourcekit) {
    throw "sourcekitdInProc.dll not found on PATH. SwiftLint needs the Swift toolchain bin on PATH for its SourceKit analysis. Install it: winget install --id Swift.Toolchain -e"
}

$swiftlint = Get-Command swiftlint.exe -ErrorAction SilentlyContinue
if (-not $swiftlint) {
    throw "swiftlint.exe not found on PATH. Install SwiftLint for Windows and put it on your USER PATH (e.g. ~\tools\swiftlint)."
}

Write-Host "SwiftLint : $($swiftlint.Source)"
Write-Host "SourceKit : $sourcekit"
& swiftlint.exe version

# --- 2. Lint -- byte-identical to the gating CI step --------------------------
# CI ("CaElevationKit (macos)" job): working-directory ios-app, then
#   swiftlint lint --strict --config .swiftlint.yml
# included:[Sources,Tests] in .swiftlint.yml is cwd-relative, so we cd to ios-app
# the way the sibling scripts derive it from $PSScriptRoot (run-from-anywhere).
$iosApp = Split-Path $PSScriptRoot -Parent
Set-Location $iosApp

Write-Host "`n=== swiftlint lint --strict ===" -ForegroundColor Cyan
$out = & swiftlint.exe lint --strict --config .swiftlint.yml 2>&1
$code = $LASTEXITCODE
$out | ForEach-Object { Write-Host $_ }

# --- 3. Fail closed -----------------------------------------------------------
# (a) Non-zero exit = violations under --strict. PowerShell does NOT auto-throw on
#     a native non-zero exit even with $ErrorActionPreference='Stop', so guard
#     explicitly (the sibling scripts guard swift build/test the same way).
if ($code -ne 0) { throw "SwiftLint reported violations (exit $code)." }

# (b) swiftlint ALSO exits 0 when it lints ZERO files (wrong cwd, or a broken
#     `included:` path), so prove it actually linted something -- mirroring
#     win-xlang-check.ps1's empty-dir fail-closed guard.
$summary = $out | Select-String -Pattern 'Found .* in (\d+) files' | Select-Object -Last 1
if (-not $summary) {
    throw "Could not parse SwiftLint's file-count summary -- treating as a failure (fail-closed)."
}
$fileCount = [int]$summary.Matches[0].Groups[1].Value
if ($fileCount -lt 1) {
    throw "SwiftLint linted 0 files -- check the working dir / .swiftlint.yml 'included' paths."
}

Write-Host "`nSwiftLint: clean ($fileCount files) -- matches CI on Windows." -ForegroundColor Green
