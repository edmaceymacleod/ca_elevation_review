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

## Done this pass

- **Kit ⟷ engine schema cross-check (GATING).** New `xlang_schema` CI job
  (macOS): a shared `CaElevationFixtures` target + a `cek-emit` executable emit
  the kit's `CapturePackage` + `SpecManifest` through the kit's own encoder →
  JSON → validated against the **authoritative**
  `engine/src/ca_elevation_engine/schemas/{capture_package,spec_manifest}.schema.json`
  (`jsonschema`-only, engine-free, so the registered-golden check degrades to a
  NOTE). Fail-closed `test -s` guard (the validator exits 0 on an empty dir). PC
  repro: `ios-app/scripts/win-xlang-check.ps1` (verified locally 2026-06-30:
  emit + `Fixtures validated: 2`; 30/30 kit tests pass on Windows).
  **Honest scope:** validates schema *shape* against ONE rich positive sample —
  not date-time fidelity (neither side enforces `format`) and not a future
  optional field added on only one side. **CONTRIBUTING rule:** a new `Codable`
  field on a wire model MUST be populated in `Fixtures`, or it never reaches the
  wire and drift on it is invisible.

## Next steps (PC-buildable, Mac-free) — the reshaped "Windows CI leg"

Adversarial review of the original "gating Windows job" found a Windows compile
is **neither necessary nor sufficient** for the real *Foundation-only* invariant
(it skips `#if canImport(...)`-guarded leaks; corelibs-Foundation gaps false-
alarm), and a **non-gating** Windows job proves nothing under owner
auto-merge-on-green. So the original Item 1 is split into three:

1A. **Foundation-only import guard (GATING — the real enforcement).** A grep step
    in the existing `ios_kit` (macOS) job that fails if `Sources/CaElevationKit`
    imports UIKit/SwiftUI/ARKit/RealityKit/CoreLocation/AVFoundation/CoreMotion/
    Vision/AppKit. Flat grep (not a compile) catches `#if canImport(...)` leaks.
    Tiny, zero infra risk, gating. **Do this first.**

1B. **Windows kit job (INFORMATIONAL).** The `swift build`/`swift test` Windows
    leg from the original handoff — but pinned to `windows-2022` (the VS 2022 +
    Swift 6.3.2 env behind the local 29/29), with `timeout-minutes`,
    `--scratch-path` (MAX_PATH), an SDKROOT diagnostic/fallback, and SHA-pinned
    actions. **NOT** in `all-green`'s needs/R map. Must be observed green on a
    hosted runner BEFORE its PR merges (hold auto-merge / temporarily require the
    check) — SwiftyLab/setup-swift serving 6.3.2-on-Windows, SDKROOT export, and
    msvc-dev-cmd activating VS are all UNVERIFIED offline. Promote to gating only
    after 1C exists + branch protection requires only `CI / all-green` + N
    consecutive greens; the `needs:` entry + R-map line MUST land in ONE commit
    (an R-map line without the needs entry permanently reds the required check).

1C. **Linux Swift job (GATING — recommended).** `ubuntu-latest` + setup-swift,
    `swift build`/`swift test`: same cross-toolchain/non-Apple-framework signal as
    Windows with far less infra fragility, and it reconciles `Package.swift`'s
    "builds on Linux for CI" claim (no such job exists today). With 1A + 1C
    gating, 1B can stay permanently informational.
