# CA Elevation Review — iOS app (Claude Code conventions)

Guidance for developing the iPhone capture app with Claude Code on an Apple
Silicon Mac. Adapted from community iOS+Claude-Code practice, tuned to this app.

## What this app is

A **deliberately thin** SwiftUI/ARKit field client (design doc §"iPhone capture
app"). It loads a field bundle, lets the user pin a location + heading on a
floorplan, captures RGB + LiDAR depth + ARKit pose, and exports a capture
package. **No analysis logic lives here** — that is the CPython engine's job.
The app is a sensor client; keep it one.

## Essential rules (Claude Code + iOS)

Hard rules that prevent the most common AI-assisted-iOS failures (adapted from
Kris Puckett's "Essential Rules for iOS work with Claude"). These are not
suggestions.

1. **Never let AI hand-edit `.pbxproj` / the `.xcodeproj`.** One corrupted
   project file burns hours. We go further than "add files manually": the Xcode
   project is **generated from `project.yml` (XcodeGen)** and the `.xcodeproj` is
   **gitignored**. To add a source file, put it under `Sources/...` and run
   `xcodegen generate` — never open and edit the `.pbxproj`, never let a tool
   rewrite it.
2. **Document platform gotchas the moment you hit one** — append to the
   "Platform gotchas" list below in the same change, with the symptom and the
   fix, so it is never rediscovered. (Puckett's example: `NO .background() before
   .glassEffect()`.)
3. **Feature-flag experimental / risky capture paths.** Anything that might need
   to be turned off at 11pm without a rebuild goes behind
   `CaElevationKit/FeatureFlags` (instant rollback), not a hardcoded branch.
4. **Always add debug logging to complex/async flows.** The ARKit session,
   depth/pose extraction, and bundle IO are async and only fail on-device — use
   the shared `os.Logger`s in `CaElevationApp/Log.swift` (`Log.capture`,
   `Log.bundle`, …) so issues are diagnosable from Console.app / `log` without a
   debugger. Gate verbose logs on `FeatureFlags.verboseCaptureLogging`.
5. **Test after every change — don't let breaks compound.** Kit change → run
   `swift test` (the CI-covered suite) before moving on. App/UI change →
   `xcodegen generate`, **clean build (Cmd+Shift+K)**, build to a Simulator for
   UI/nav, then run **on a real device** for anything in the capture/depth path
   and watch `Log.*` in Console.app / `log stream`. (Engine and pyRevit changes
   have their own `pytest` suites — run those too.)
6. **Keep each change scoped to one component.** Touch the kit, *or* the app
   layer, *or* a single view/flow — never "refactor the whole app." The kit/app
   seam below is the natural unit; smaller scope = better results and easier
   rollback.
7. **Leave a session record with rollback steps.** End a major change with a
   clear commit body (what changed, how it was verified, how to undo) and, for a
   multi-step or risky change, a dated note under `docs/sessions/` (template in
   `docs/sessions/README.md`). Rollback must be concrete: `git revert <sha>`, or
   flip the relevant `FeatureFlags` toggle (rule 3). Every session leaves the
   tree green and revertible.

## Platform gotchas (append as found — rule 2)

A living list. When a platform-specific surprise costs you time, add it here.

- **Simulator has no camera/LiDAR** — `ARCaptureSession` returns nil/black
  frames; the entire capture/depth/pose path is **device-only**. Treat simulator
  runs as UI/navigation checks.
- **`navigationDestination(item:)` is iOS 17+** — the deployment floor is iOS 17
  for exactly this reason; don't drop it to 16.
- **ARKit transforms are column-major `simd`** — convert to the schema's **16-
  element row-major** pose on export (`ARCaptureSession`), or the engine reads a
  transposed pose.
- **Depth ≠ RGB resolution** — `sceneDepth.depthMap` (~256×192) is far smaller
  than `capturedImage`; carry `depth_size` separately, never assume they align.
- **`Affine` det epsilon is `1e-12`** — matches the engine; don't use `!= 0`
  (near-singular affines must be rejected identically on both sides).
- **File Provider files can be dataless** — a floorplan/manifest synced from
  OneDrive (or any provider) into iOS Files may be a placeholder with no bytes on
  disk yet. `UIImage(contentsOfFile:)` / `Data(contentsOf:)` on a raw path do
  **NOT** trigger a download — they read whatever is local and silently
  return nil/partial. Route provider reads through `NSFileCoordinator`
  (`FileProviderAccess` in `Library/`), which materializes the item first.
- **No reliable "is it downloaded?" API for third-party providers** —
  `URLResourceKey.ubiquitousItemDownloadingStatusKey` is iCloud-only and absent
  for OneDrive. Don't poll status; always do a coordinated read and show a
  spinner while it materializes.
- **iOS folder bookmarks need no entitlement** — folders picked via
  `.fileImporter` are re-accessed with `bookmarkData(options: [])` /
  `resolvingBookmarkData(options: [])`. `.withSecurityScope` and
  `com.apple.security.files.bookmarks.*` are **macOS App Sandbox** concepts;
  `.withSecurityScope` throws on iOS. Don't copy macOS sample code (`RootFolderStore`).
- **CRLF checkout breaks local SwiftLint on Windows** — Git for Windows defaults
  to `core.autocrlf=true`, so a Windows checkout writes the LF-stored sources as
  CRLF on disk. SwiftLint then counts CR and LF as *separate* line breaks —
  doubling every file's line count — and fires false `comma` / `trailing_newline`
  / `file_length` violations on every Swift file, while CI (macOS/Linux, LF) stays
  clean. The root `.gitattributes` (`eol=lf`) fixes it: **a fresh clone checks out
  LF automatically — no action needed.** Only a working tree that *predates*
  `.gitattributes` keeps its CRLF bytes; flip it **once** (from the repo root, on a
  clean tree) with `git ls-files -z | xargs -0 rm -f && git checkout -- .` — it
  deletes and re-checks-out every tracked file as LF, leaving the index and
  untracked files alone. `git checkout -- .` / `git checkout-index -f` alone do
  **not** work: the stat cache makes git skip the rewrite. Verify with
  `git ls-files --eol` (no `w/crlf`). Lint with the CI-parity gate:
  `pwsh -File ios-app/scripts/win-swiftlint.ps1`.

## Architecture (do not blur this line)

- **`Sources/CaElevationKit/`** — pure, `Foundation`-only library (the SwiftPM
  package in `Package.swift`). Wire models, bundle IO, the pixel→model affine.
  Builds and unit-tests headlessly on Linux/macOS CI. **Never** `import`
  SwiftUI/UIKit/ARKit/CoreLocation here.
- **`Sources/CaElevationApp/`** — the SwiftUI + ARKit app layer, built as the
  Xcode App target via `project.yml` (XcodeGen). All platform-coupled code lives
  here, guarded with `#if canImport(ARKit)` etc.

When adding logic, ask: is it pure data/transform? → `CaElevationKit` (with a
test). Does it touch a sensor/UI? → `CaElevationApp`.

## Look and feel

**Native-default by policy** — the app inherits Apple's design language; we don't
invent a theme. Use semantic fonts (`.headline`/`.caption`, never hardcoded
sizes), semantic colors (`.secondary`; status colors carry meaning — green =
captured; floorplan pins encode role, blue `camera.fill` = a camera shot, red
`mappin.circle.fill` = the operator's location), SF Symbols, and stock controls
(`.borderedProminent`, `.segmented`). The one brand color is `AccentColor` (a
blueprint blue) in `Sources/CaElevationApp/Assets.xcassets`; rely on the global
tint rather than hardcoding it. The app icon there is a **placeholder**. Full
rationale, the color hex values, and the remaining open question (final icon)
are in [`../docs/ui-conventions.md`](../docs/ui-conventions.md) — read it before
restyling a screen or changing branding. (The app name is decided: **CA
Elevation Review**.)

## Targets & toolchain

- **Min iOS 17** (matches `Package.swift` and `project.yml`). All LiDAR iPhones
  (12 Pro+) run iOS 17+, so this loses no hardware.
- **Swift 5.9+ toolchain** (current Xcode). Prefer Swift Concurrency / `async`;
  if moving to Swift 6 language mode, fix strict-concurrency warnings, don't
  silence them.
- Prefer `NavigationStack`/`navigationDestination`, value types, `@Observable`
  (iOS 17) over `ObservableObject` for new view models. No force-unwraps.

## Build / run / test loop

- **Generate the Xcode project first:** `brew install xcodegen` then
  `cd ios-app && xcodegen generate` → `CaElevationReview.xcodeproj`.
- **Kit (headless, the CI-covered part):** `cd ios-app && swift test`.
- **App build / simulator run:** via XcodeBuildMCP (see `.mcp.json`) —
  `build_sim_name_proj`, `boot_simulator`, `install_app`, `launch_app`,
  `capture_logs`, `screenshot`. Add the server with:
  `claude mcp add --transport stdio XcodeBuildMCP --scope project -- npx -y xcodebuildmcp@latest`.
- **The LiDAR capture path cannot be exercised in the Simulator** (no camera/
  LiDAR). `ARCaptureSession` returns nil/black frames there. Depth, intrinsics,
  pose, and the whole capture flow are **device-only** — validate on a real
  iPhone Pro. Treat simulator runs as UI/navigation checks only.

## Signing / device (Ed-owned, not in-session)

Running on device needs an Apple Developer team set in the target's Signing &
Capabilities and a provisioned iPhone Pro w/ LiDAR. Set `DEVELOPMENT_TEAM`
locally (gitignored `.xcconfig` or the Xcode UI), not in `project.yml`.

## Don't

- Don't add an analysis/registration/scoring step here — it belongs in the
  engine. The app only captures and packages.
- Don't let ARKit/UIKit imports leak into `CaElevationKit`.
- Don't hand-author a `.pbxproj`; edit `project.yml` and regenerate.
- Don't assume the capture/depth path works from the Simulator.
