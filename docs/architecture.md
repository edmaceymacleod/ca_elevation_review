# Architecture

This is a concise architecture reference. For product intent and the reasoning
behind each decision, read `design.md`; for the payload schemas read
`schemas.md`; for the testing model read `testing.md`.

## Three components, three languages, one repo

```
+--------------------+        local file        +-----------------------+
|  iPhone capture    |  ----- field bundle --->  |  pyRevit extension    |
|  app (Swift/ARKit) |  <---- capture pkg ------  |  (Python, Windows)    |
|  ios-app/          |                            |  pyrevit-extension/   |
+--------------------+                            +-----------+-----------+
                                                              | invokes (out-of-process)
                                                              v
                                                  +-----------------------+
                                                  |  CPython engine       |
                                                  |  (the OSS core)       |
                                                  |  engine/              |
                                                  +-----------------------+
```

| Component | Path | Language | Role | Build target |
|---|---|---|---|---|
| Engine | `engine/` | Python 3.10+ | The OSS core: ingest -> register -> compare -> verdict -> report | Linux |
| Revit front door | `pyrevit-extension/` | Python (pyRevit CPython) | Spec source, engine invoker (out-of-process), result sink | Windows |
| Revit add-in (legacy) | `revit-addin/` | C# / .NET | The original front door; kept one cycle, CI-gated off, pending live validation | Windows |
| iPhone app | `ios-app/` | Swift / SwiftUI / ARKit | Thin field capture client | macOS |

> **Front-door pivot:** the Revit front door moved from the standalone C# add-in
> to a **pyRevit extension** (`pyrevit-extension/`) so the manifest-assembly /
> bundle-IO / engine-invocation / verdict-mapping logic becomes real, CI-tested
> CPython instead of untestable C#. The engine is unchanged and still invoked
> out-of-process. The C# `revit-addin/` is retained one cycle (it is the only
> artifact preserving a signed-installer / closed-tier commercial option). See
> [`pyrevit-migration-plan.md`](pyrevit-migration-plan.md).

- **Engine** is independently runnable and headlessly testable. Heavy native
  backends (Open3D / pye57 / OpenCV / a vision model) are optional extras, loaded
  lazily, which is why the engine runs out-of-process from Revit -- those wheels
  are fragile to load inside Revit's process. The pure logic lives in modules
  like `geometry.py` (affine + pose math) and `models.py` (typed payloads),
  separated from format IO.
- **Revit front door** is the pyRevit extension, written in Python and run by
  pyRevit's CPython runtime, so the manifest-assembly / bundle-IO /
  engine-invocation / verdict-mapping logic is real, CI-tested CPython rather than
  untestable C#. It extracts the manifest from the live model, exports floorplans
  with their transforms, invokes the engine out-of-process on returned captures,
  colors devices by verdict, and opens the report. The original C# `revit-addin/`
  is retained legacy, CI-gated off, pending live validation.
- **iPhone app** is deliberately a sensor client with no analysis logic. The pure
  parts live in the `CaElevationKit` SwiftPM library (builds/tests headlessly,
  no ARKit dependency); the SwiftUI + ARKit layer is an Xcode App target on top.

## The internal seam

The engine only ever sees two documented payloads. This seam exists because the
out-of-process boundary needs a defined wire format anyway, and because it is
what makes the engine unit-testable with no live Revit session and no device.

- **Spec manifest** (front door -> engine): the *expected* world. Devices with stable
  ids, family/type, 3D position, mounting height, orientation, per-device
  tolerances, and their level/elevation; plus floorplan images and the
  plan-pixel-to-model affine per level.
- **Capture package** (app -> engine): the *observed* world. Per shot: RGB image,
  depth map or point cloud, ARKit camera intrinsics + pose, and the operator's
  floorplan pin (x,y) + heading.
- **Verdict report** (engine output): per-device verdicts (`pass` / `flag` /
  `absent` / `type_mismatch`) with measured deltas, confidence, and a summary;
  consumed by the front door for write-back and by the report renderer.

All three are defined by JSON Schema under
`engine/src/ca_elevation_engine/schemas/` and are the contract every component
codes against. See `schemas.md`.

## Capture localization: the floorplan pin

The operator drops a pin for *where they stood* and an arrow for *which way the
camera faced*. This is the georeferencing primitive -- the hard-to-automate input
only a person supplies quickly -- that drops the capture into the building's
coordinate system. The arrow is pre-filled from the device compass so the user
confirms rather than guesses. ARKit pose then provides full relative 6DOF, the
pin georeferences ARKit's arbitrary world frame into Revit coordinates, and
LiDAR depth gives metric per-pixel 3D.

## Engine pipeline shape

```
ingest -> coarse georeference -> refine registration -> locate devices
       -> compare (position / height / orientation / presence / type)
       -> verdict (per-device tolerance ruleset) -> emit (results + report)
```

1. **Ingest** manifest + capture package; validate both against their schemas.
2. **Coarse georeference** from pin + heading -> initial transform to model coords.
3. **Refine** by registering the capture to nearby model geometry (point-cloud
   ICP and/or 2D photo-to-elevation registration), seeded by step 2.
4. **Locate** each expected device in view (geometry candidates + vision typing).
5. **Compare** position/height/orientation deltas; assess presence and type.
6. **Verdict** via the per-device tolerance ruleset, each with a confidence;
   device *identity* stays human-confirmable.
7. **Emit** the structured verdict report (Revit write-back) and the report.

The coarse-human-anchor -> sensors -> fine-registration -> compare -> report
shape is the heart of the system. Known v1 limit: a single viewpoint carries
occlusion shadows and LiDAR is coarse (~256x192, reliable to ~5 m); geometry from
protruding/occluded devices is labeled approximate in the report.
