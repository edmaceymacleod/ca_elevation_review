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

## 1B — Windows kit job (INFORMATIONAL, this PR)

The `swift build`/`swift test` Windows leg (`windows-2022`, Swift 6.3.2 via
`SwiftyLab/setup-swift@v1.14.0` + SHA-pinned `ilammy/msvc-dev-cmd`, `--scratch-path`
for MAX_PATH, SDKROOT diagnostic/fallback). **NON-GATING:** omitted from
`all-green` + job-level `continue-on-error`, so a Windows flake never fails the CI
**workflow** (which would block owner auto-merge for *all* iOS PRs). The hosted
Swift-on-Windows setup **worked first try** (setup-swift served 6.3.2, MSVC
activated, build + tests ran).

**It immediately earned its keep:** the first run caught a real **#28 regression**
— `BundleIO.resolvedURL` rejected *every* valid bundle path on Windows because
`resolvingSymlinksInPath()` expands the 8.3 short name (`ED0B62~1.MAC` →
`ed.macey-macleod`) for a fully-existing path but not for one with a not-yet-created
tail, so the independently-resolved ancestors mismatched. Fixed in **#33** (anchor
the containment check on the canonical `realBase`; compare by path components).
macOS/Linux never saw it; iOS (production) is unaffected (no short names). This
PR is rebased on #33, so its Windows job is green.

**Promotion to gating** (later, optional): the kit now builds green on Windows, but
keep it informational until the *setup* (toolchain download / action) is observed
stable across several runs; then add `ios_kit_windows` to `all-green`'s `needs:`
AND R-map in ONE commit.

> **Merge note:** every CI PR touches `.github/workflows/ci.yml`, which neither the
> auto-merge bot nor the local `gh` (scopes: `gist, read:org, repo`) can merge —
> needs `workflow` scope (`gh auth refresh -s workflow`) or a web-UI merge. So
> these land by manual merge, not auto-merge.
