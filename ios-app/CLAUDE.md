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
