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

## Next steps (PC-buildable, Mac-free)

Both are doable entirely on the Windows dev machine — no Mac, no Revit hardware.

1. **Windows CI leg for `CaElevationKit`.** Add a `windows-latest` job to
   `.github/workflows/ci.yml`, gated on the existing `ios` path filter and wired
   into the `all-green` `needs:` fan-in. It should install the Swift toolchain and
   `swift build` + `swift test` the kit, mirroring `ios-app/scripts/win-kit-test.ps1`
   (enter the VS Developer env for the MSVC linker; set `SDKROOT` + the toolchain
   on PATH). The macOS `ios_kit` job already builds/tests the kit, so this is
   **additive portability proof** that the kit stays Foundation-only across
   toolchains. Decide gating vs informational — hosted-runner Swift-on-Windows
   setup is slower; consider caching the toolchain. Verified locally 2026-06-29:
   Swift 6.3.2, 29/29 kit tests pass on `x86_64-unknown-windows-msvc`.

2. **Kit ⟷ engine capture-package schema cross-check (PC).** Add a small
   cross-language test: emit a sample `CapturePackage` from the Swift kit
   (`CapturePackage.swift` / `BundleIO.swift`) → JSON → validate against the
   **authoritative** `engine/src/ca_elevation_engine/schemas/capture_package.schema.json`
   (Python `jsonschema`, or the engine's own `ingest.load_capture`). Both sides run
   on the PC now (Swift kit + the engine venv). The kit's `CapturePackageTests`
   already check encode round-trip + snake_case keys, but only against *itself*;
   this catches **Swift ⟷ engine-schema drift** (required fields, snake_case
   `CodingKeys`, the 16-element row-major pose) the moment either side changes.
   Mirror the same idea for `FieldBundle.swift` ⟷ `spec_manifest.schema.json`.
