# 2026-06-29 — OneDrive write-back round trip (Phase 2)

**Scope:** app layer (`CoverageView`, new `Library/WriteBack.swift`) + one kit
flag (`FeatureFlags`) and a path-guard visibility bump in `BundleIO`. Feature is
gated, so the seam stays narrow.

**What changed**
- `CaElevationKit/FeatureFlags`: added `writeBackToRoot` (default **off**), wired
  into `resolved(overrides:)`, plus a `FeatureFlagsTests` case.
- `CaElevationKit/BundleIO`: made the existing `resolvedURL(forRelativePath:in:)`
  path-escape guard `public` so the app can reuse it (no new logic).
- New `CaElevationApp/Library/WriteBack.swift`: when the flag is on, copies the
  already-built local capture package into
  `<projectDir>/Exports/<yyyyMMdd-HHmmss>-<shortUUID>/` via
  `NSFileCoordinator.coordinate(writingItemAt:options:[.forReplacing])` +
  `FileManager.copyItem`, holding the library root's security scope, creating
  intermediate dirs under coordination, and resolving the destination through
  `BundleIO`'s guard. Also a `FeatureFlags.current()` helper that resolves live
  flags from `UserDefaults` (runtime rollback without a rebuild).
- `CoverageView.exportPackage()`: after `CaptureExporter.exportPackage`, when the
  flag is on, runs the write-back **off the main actor**. The share sheet stays
  the unconditional fallback; failures log via `Log.bundle` and show a
  non-blocking toast ("Saved locally; couldn't sync to folder — use Share").
  Success surfaces "Saved to folder" (never "synced" — the OneDrive upload is
  async and outside our control).

**Why**
- Phase 2 of the round trip merged in PR #13: let the desktop pick up captures
  automatically by landing them in the synced folder, without removing the
  manual share-sheet path.

**How verified**
- `swift test` (kit, incl. new FeatureFlags case): not runnable in this Linux
  container (no Swift toolchain / Xcode); relies on the macOS CI jobs
  (`swift test` + `xcodegen generate` + `xcodebuild build`).
- Simulator build (UI/nav): same — covered by CI's app-build job.
- On-device (actual OneDrive upload): **device-only** — the Simulator has no
  File Provider, so the coordinated write + provider upload can only be
  validated on a real iPhone signed into OneDrive. Not exercised this session.

**Gotchas hit**
- None new. Re-used the existing File-Provider coordination pattern from
  `FileProviderAccess`; nothing added to CLAUDE.md "Platform gotchas".

**Rollback**
- Flip `writeBackToRoot` off (instant, no rebuild) — set the `writeBackToRoot`
  key to `false`/absent in `UserDefaults`; export falls back to share-sheet only.
- Or `git revert <sha>` of this change.
