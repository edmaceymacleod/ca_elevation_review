# CA Elevation Review — iPhone capture app

The **field client** of the As-Built Elevation Verification Tool. It is a
deliberately *thin sensor client*: it loads a Revit-exported **field bundle**,
lets the operator pin location + heading on the floorplan, captures **RGB +
LiDAR depth + ARKit pose**, and exports a **capture package** back to the
desktop. **No analysis logic lives here** — registration, comparison, and
verdicts are the CPython engine's job (see `../engine`). See `../docs/design.md`,
sections "iPhone capture app", "Capture localization: the floorplan pin as
georeference anchor", and "Field flow (iPhone app)".

This component is **Phase 2** in the build plan and is scaffolded here ahead of
its phase so the schema contract is exercised from both ends early.

## What's in here

```
ios-app/
  Package.swift                  Swift Package for the pure-logic library + tests
  Sources/
    CaElevationKit/              PURE Foundation library — no UIKit/ARKit. Testable headlessly.
      FieldBundle.swift          Codable models for the incoming spec manifest
      CapturePackage.swift       Codable models for the outgoing capture package
      BundleIO.swift             Read field bundle / write capture package (directories)
      Affine.swift               Plan-pixel → model affine (mirrors the engine)
      JSONValue.swift            Lossless passthrough for free-form metadata
    CaElevationApp/              SwiftUI + ARKit APP LAYER — added to an Xcode App target
      CaElevationApp.swift       @main entry + app-wide session state
      Views/                     ProjectList / Capture / PlacePin / Coverage + plan canvas
      Capture/                   ARCaptureSession (ARKit/LiDAR), CaptureExporter
      Heading/                   CompassHeading (CoreLocation, pin pre-fill)
      Assets.xcassets/           AccentColor + AppIcon (placeholder); see ../docs/ui-conventions.md
  Tests/
    CaElevationKitTests/         XCTest: bundle decode, capture encode, affine math
```

### The pure / platform split (the testability rule)

The design doc mandates *separation of pure logic from platform-coupled code*.
Here that line is hard:

- **`CaElevationKit`** is pure Foundation — models, bundle IO, affine math. It
  builds and tests **headlessly** on Linux/macOS CI with `swift test`, no device.
  This is the part covered by the unit suite.
- **`CaElevationApp`** holds everything ARKit / CoreLocation / UIKit. It only
  builds in an Xcode **App** target on macOS and is exercised by **on-device
  live tests** (a real LiDAR iPhone — Ed's responsibility), never in unit CI.

## Requirements

- **iPhone Pro with LiDAR** for actual capture. ARKit `sceneDepth` (metric
  depth) is what forces native iOS — it is unavailable to web/Android, and **the
  iOS Simulator has no camera and no LiDAR**, so a real device is required to
  capture. The app degrades to RGB + pose without LiDAR but the engine then
  lacks metric depth for that shot.
- **Xcode 15+**, **iOS 17+** deployment target (matches `Package.swift` and `project.yml`).
- An **Apple Developer** signing identity to run on device.

## Open / build in Xcode

The pure library is a Swift Package; the app is an Xcode App target that depends
on it. Two parts because Claude can produce real Swift sources but not a full,
valid `.xcodeproj` headlessly.

**Pure library + tests (works anywhere with a Swift toolchain):**

```bash
cd ios-app
swift build          # builds CaElevationKit
swift test           # runs the headless XCTest suite
```

**The app target (in Xcode, on a Mac) — generated from `project.yml`:**

The App target is defined declaratively in `project.yml` (XcodeGen) — including
the Info.plist privacy usage strings (`NSCameraUsageDescription`,
`NSLocationWhenInUseUsageDescription`), `UIRequiredDeviceCapabilities: [arkit]`,
the local `CaElevationKit` dependency, and an iOS 17 floor. Generate and open it:

```bash
brew install xcodegen          # one time
cd ios-app && xcodegen generate # writes CaElevationReview.xcodeproj
open CaElevationReview.xcodeproj
```

Then set your **Apple Developer team** in Signing & Capabilities (locally; not in
`project.yml`) and build & run **on a real LiDAR device** — the Simulator has no
camera/LiDAR, so the capture path only works on an iPhone Pro.

> The binary `.xcodeproj` is intentionally not committed (unreviewable, can't be
> authored headlessly); regenerate it from `project.yml`. See
> `../docs/ios-mac-silicon-readiness.md` for the full Apple-Silicon checklist,
> `../docs/ui-conventions.md` for the app's look-and-feel policy and branding
> assets, and `CLAUDE.md` for the Claude Code build/run loop (XcodeBuildMCP).

## Bundle round-trip (local-first, no sync server)

Per the design's local-first decision, project data moves by **local file
exchange only** — no SaaS, no cloud processing.

```
Revit add-in  --(field bundle: manifest.json + floorplans)-->  iPhone
iPhone        --(capture package: capture.json + rgb/depth)-->  Revit add-in
```

- **In:** `Choose Folder` points the app at one **library root** — a folder
  synced onto the phone (e.g. a **OneDrive** folder via iOS Files) that holds one
  subfolder per project, each a field bundle (`manifest.json` + its floorplan
  images). The app lists those projects with thumbnails (a true multi-project
  picker) and remembers the chosen folder across launches via a security-scoped
  bookmark. A one-off bundle can still be picked directly. Ad-hoc transfer
  (AirDrop / Files / iCloud Drive) of a single bundle folder also works.
- **Out:** after the walk, `Export` assembles a capture-package folder
  (`capture.json` + staged `shots/<id>/rgb.jpg` and `depth.f32`) and hands it to
  the iOS **share sheet** — AirDrop it back, drop it in iCloud/Files, or cable
  it. The desktop add-in points the engine at that folder. *(Writing the package
  straight back into the OneDrive folder is the planned Phase 2 round-trip.)*

Files synced from a provider may be **dataless** (not downloaded yet): the app
reads them through `NSFileCoordinator` (`Library/FileProviderAccess`) so they
materialize on demand. The default transfer mechanism remains an open question in
the design doc; the app supports a synced OneDrive root plus the standard
importer/share sheet.

## Schema contract

The Codable models in `CaElevationKit` mirror the engine's JSON schemas
**field-for-field** (snake_case on the wire via explicit `CodingKeys`):

- `FieldBundle.swift`  ⟷  `engine/.../schemas/spec_manifest.schema.json`
- `CapturePackage.swift`  ⟷  `engine/.../schemas/capture_package.schema.json`

Conventions kept identical to the engine:

- **Floorplan affine** `pixel_to_model` is 2×3 row-major `[a,b,c,d,e,f]`:
  `X = a·px + b·py + c`, `Y = d·px + e·py + f` (see `Affine.swift`).
- **ARKit pose** is a **4×4 row-major** camera-to-world matrix in ARKit's world
  frame (right-handed, −Z forward, +Y up); `ARCaptureSession` converts simd's
  column-major transform to this row-major layout on export.
- **Pin heading** is **plan degrees** (0 = +X, CCW). The compass reports
  true-north degrees; `CompassHeading.planHeadingDegrees(northAngle:)` converts
  using the manifest's `coordinate_system.north_angle`.

If a schema field changes, update the matching Codable type and its round-trip
test, and bump `schema_version`.
