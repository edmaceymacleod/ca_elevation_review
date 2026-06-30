# Handoff — CA Elevation Review

Transient scratchpad for notes to the **next** session. Keep durable facts out of
here — **persistent records live in `docs/`**.

The live-Revit validation of the LIVE `revit_*` stubs is **complete** (PRs #22,
#25); the pyRevit extension is registered + loads its ribbon (PR #26); the Swift
kit builds/tests on Windows (PR #24). Persistent records:

- `docs/live-validation-2026-06-29.md` — extract / write-back / bundle→engine
  evidence (Part 2) + the solid-fill eyeball.
- `docs/pyrevit-migration-plan.md` — pyRevit pin / CPython-floor (Open item 1)
  and remaining open migration items.

## Landed

- **Item 2 — kit ⟷ engine schema cross-check (GATING, merged #30).** `xlang_schema`
  CI job (macOS): a shared `CaElevationFixtures` target + a `cek-emit` executable
  emit the kit's `CapturePackage` + `SpecManifest` through the kit's own encoder →
  JSON → validated against the **authoritative**
  `engine/src/ca_elevation_engine/schemas/{capture_package,spec_manifest}.schema.json`
  (`jsonschema`-only, engine-free, so the registered-golden check degrades to a
  NOTE). Fail-closed `test -s` guard. PC repro: `ios-app/scripts/win-xlang-check.ps1`.
  **Honest scope:** schema *shape* vs ONE rich positive sample — not date-time
  `format` (neither side enforces it) and not a future optional field added on one
  side only. **CONTRIBUTING rule:** a new `Codable` wire field MUST be populated in
  `Fixtures`, or it never reaches the wire and drift on it is invisible.

- **1A + 1C — Foundation-only enforcement (GATING, PR for `claude/foundation-only-enforcement`).**
  *1A:* a grep import-guard step in `ios_kit` over the pure targets
  (`CaElevationKit` + `CaElevationFixtures` + `cek-emit`) — the real, *sufficient*
  check for the Foundation-only invariant; it catches `#if canImport(...)`-guarded
  leaks a Windows/Linux compile would skip. *1C:* a gating `ios_kit_linux` job
  (`container: swift:6.0`, no setup-swift action to drift) — the cross-toolchain
  leg `Package.swift` already claims. Both wired into `all-green` needs + R-map.

## Next step — 1B only

**Windows kit job (INFORMATIONAL).** The `swift build`/`swift test` Windows leg
from the original handoff — but now that 1A (the real enforcement) and 1C (a cheap
gating cross-toolchain leg) are landed, **1B is purely additive and can stay
permanently informational**. Pin to `windows-2022` (the VS 2022 + Swift 6.3.2 env
behind the local 30/30), with `timeout-minutes`, `--scratch-path` (MAX_PATH), an
SDKROOT diagnostic/fallback, and SHA-pinned actions. Must use the `revit`-style
`continue-on-error` so a Windows flake never fails the CI **workflow** (which would
block owner auto-merge for *all* iOS PRs, not just gate `all-green`). Open it as a
**draft** and confirm `swift test` actually EXECUTES on the hosted runner before
readying it — SwiftyLab/setup-swift serving 6.3.2-on-Windows, SDKROOT export, and
`msvc-dev-cmd` activating VS are all UNVERIFIED offline.

> **Merge note:** every CI PR touches `.github/workflows/ci.yml`, which neither the
> auto-merge bot nor the local `gh` (scopes: `gist, read:org, repo`) can merge —
> needs `workflow` scope (`gh auth refresh -s workflow`) or a web-UI merge. So
> these land by manual merge, not auto-merge.
