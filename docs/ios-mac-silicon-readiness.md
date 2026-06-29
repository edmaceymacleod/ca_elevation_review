# iOS app readiness on Apple Silicon

**Status:** 2026-06-29. Assessment + prep for developing the CA Elevation Review
iPhone app on an Apple Silicon (M-series) Mac with Xcode + Claude Code. Combines
an audit of `ios-app/` with a distillation of the community guide
[keskinonur/claude-code-ios-dev-guide](https://github.com/keskinonur/claude-code-ios-dev-guide).

## Bottom line

The pure `CaElevationKit` library is in good shape — correctly separated,
`Foundation`-only, well-tested, and it builds/tests cleanly on Apple Silicon
**today** via `swift test`, with CI that exercises it properly. The entire gap
was **app-target packaging**: there was no Xcode project / Info.plist / privacy
strings / capabilities, plus a latent iOS-16-vs-17 deployment bug. This commit
closes the headless-fixable parts; what remains genuinely needs the Mac +
hardware + an Apple Developer account (Ed).

## What this commit fixed (headless, in-repo)

1. **iOS 16-vs-17 deployment bug.** `CaptureView.swift` uses
   `navigationDestination(item:)` (iOS 17+) while `Package.swift` declared
   `.iOS(.v16)`. Bumped the floor to **iOS 17** (every LiDAR iPhone — 12 Pro and
   later — runs iOS 17+, so no hardware is lost).
2. **No Xcode project for the app.** Added **`ios-app/project.yml`** (XcodeGen):
   a declarative, reviewable App-target definition that compiles
   `Sources/CaElevationApp`, depends on the local `CaElevationKit` SwiftPM
   package, and sets the Info.plist. Ed runs `xcodegen generate` to produce the
   `.xcodeproj` (no unreviewable `.pbxproj` in git).
3. **Privacy usage strings + capabilities** (the app would crash on first sensor
   use without them), declared in `project.yml` → generated Info.plist:
   `NSCameraUsageDescription`, `NSLocationWhenInUseUsageDescription`,
   `UIRequiredDeviceCapabilities: [arkit]`.
4. **Claude Code wiring:** `ios-app/.mcp.json` (XcodeBuildMCP) for the build/run/
   test loop, and `ios-app/CLAUDE.md` with the app's conventions (kit/app split,
   iOS 17, the device-only LiDAR reality).

## What the audit confirmed is already correct

- **Kit/app separation is enforced** two ways: `Package.swift` scopes the library
  target to `Sources/CaElevationKit` only, and every kit source imports only
  `Foundation` (no UIKit/ARKit leak). The app layer is not a SwiftPM target, so
  its ARKit/UIKit imports can't break `swift build`/CI.
- **ARKit/LiDAR usage is correct and device-guarded:** depth from
  `frame.sceneDepth?.depthMap` with `supportsFrameSemantics(.sceneDepth)`
  availability checks, correct intrinsics extraction, and a correct
  column-major→row-major 16-element pose conversion matching the schema.
- **CI (the `CaElevationKit (macos)` job in `ci.yml`) is right for its scope:**
  builds/tests only the kit on `macos-latest` (an Apple-Silicon runner), which is
  exactly the headless-testable surface (SwiftLint now runs there, non-blocking;
  see docs/ci.md).

## The guide's value — and where it stops (important for us)

The guide is excellent on **configuring Claude Code to drive iOS dev** and funnels
Xcode work through the **XcodeBuildMCP** MCP server (build/test/run/screenshot on
the Simulator). Adopt that: it's the build/run loop in `.mcp.json`.

**But the guide is silent exactly where our critical path is.** It has essentially
nothing on **on-device deployment, code signing, provisioning, or LiDAR** — and it
optimizes a **Simulator-centric loop that cannot exercise our core feature** (the
Simulator has no camera/LiDAR). It also pins dated specifics (Swift 6.0 / iOS 17 /
iPhone 15 simulator / older model IDs as of its Jan 2026 revision) — adjust to the
current Xcode/iOS on the Mac.

So: take the guide's Claude Code setup; **do not rely on it for the device/signing/
LiDAR half** — that's sourced below.

## Ready checklist for the Mac (Ed-owned)

Toolchain (the guide assumes these; install them):
- [ ] **Xcode** (current; accept license, run once) + Command Line Tools
  (`xcode-select --install`). Verify `xcodebuild -version`, `swift --version`.
- [ ] At least one iOS **Simulator runtime** installed (for UI/nav checks only).
- [ ] **Homebrew** tools: `xcodegen` (required — we ship `project.yml`), plus
  `swiftlint` / `swift-format` if adopting the guide's lint hooks.
- [ ] **Node/npx** (for `npx xcodebuildmcp@latest`).

Claude Code:
- [ ] Install Claude Code; `claude doctor`.
- [ ] `claude mcp add --transport stdio XcodeBuildMCP --scope project -- npx -y xcodebuildmcp@latest`; verify `/mcp`. (Config already in `ios-app/.mcp.json`.)

Project:
- [ ] `cd ios-app && xcodegen generate && open CaElevationReview.xcodeproj`.
- [ ] `swift test` (kit) passes on the Mac.
- [ ] Build the app for a Simulator destination via XcodeBuildMCP (compiles the
  SwiftUI/ARKit layer — catches app-layer breaks the kit CI can't see).

Device / signing (NOT in the guide; required for LiDAR):
- [ ] **Apple Developer Program** enrollment; Team ID; signing cert + provisioning
  profile. Set `DEVELOPMENT_TEAM` locally (gitignored `.xcconfig` / Xcode UI).
- [ ] A real **iPhone Pro with LiDAR** (12 Pro or later). The entire capture/depth/
  pose path is **device-only** and must be validated there — never in CI.
- [ ] Establish a device build/install/test path (XcodeBuildMCP `device` workflow /
  `devicectl`); plan all depth/ARKit validation as on-device.

## Remaining nice-to-haves (tracked, not blocking)

- Add an `xcodebuild` compile-only CI step (Simulator destination) once a project
  is generated, so app-layer source breaks are caught without a device; pin Xcode
  in the `CaElevationKit (macos)` job in `ci.yml`. (SwiftLint now runs there,
  non-blocking — see docs/ci.md.)
- Add an `ARSessionDelegate` for tracking-state / interruption / failure handling
  (today failures are silent).
- Add permission-denied UI (not just the implicit first-use prompt).
- Align the depth-file extension (`depth.f32` exporter vs `depth.bin` in a kit
  test) — cosmetic; the path string is arbitrary and the engine reads `depth_size`
  separately.
