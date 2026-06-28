# Architecture

This is a concise architecture reference. For product intent and the reasoning
behind each decision, read `design.md`; for the payload schemas read
`schemas.md`; for the testing model read `testing.md`.

## Three components, three languages, one repo

```
+--------------------+        local file        +-----------------------+
|  iPhone capture    |  ----- field bundle --->  |  Revit C# add-in      |
|  app (Swift/ARKit) |  <---- capture pkg ------  |  (.NET, Windows)      |
|  ios-app/          |                            |  revit-addin/         |
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
| Revit add-in | `revit-addin/` | C# / .NET | Spec source, engine invoker, result sink | Windows |
| iPhone app | `ios-app/` | Swift / SwiftUI / ARKit | Thin field capture client | macOS |

- **Engine** is independently runnable and headlessly testable. Heavy native
  backends (Open3D / pye57 / OpenCV / a vision model) are optional extras, loaded
  lazily, which is why the engine runs out-of-process from Revit -- those wheels
  are fragile to load inside Revit's process. The pure logic lives in modules
  like `geometry.py` (affine + pose math) and `models.py` (typed payloads),
  separated from format IO.
- **Revit add-in** is the desktop front door, chosen over a pyRevit extension so
  users do not have to install pyRevit first. It extracts the manifest from the
  live model, exports floorplans with their transforms, invokes the engine
  out-of-process on returned captures, colors devices by verdict, and opens the
  report.
- **iPhone app** is deliberately a sensor client with no analysis logic. The pure
  parts live in the `CaElevationKit` SwiftPM library (builds/tests headlessly,
  no ARKit dependency); the SwiftUI + ARKit layer is an Xcode App target on top.

## The internal seam

The engine only ever sees two documented payloads. This seam exists because the
out-of-process boundary needs a defined wire format anyway, and because it is
what makes the engine unit-testable with no live Revit session and no device.

- **Spec manifest** (add-in -> engine): the *expected* world. Devices with stable
  ids, family/type, 3D position, mounting height, orientation, per-device
  tolerances, and their level/elevation; plus floorplan images and the
  plan-pixel-to-model affine per level.
- **Capture package** (app -> engine): the *observed* world. Per shot: RGB image,
  depth map or point cloud, ARKit camera intrinsics + pose, and the operator's
  floorplan pin (x,y) + heading.
- **Verdict report** (engine output): per-device verdicts (`pass` / `flag` /
  `absent` / `type_mismatch`) with measured deltas, confidence, and a summary;
  consumed by the add-in for write-back and by the report renderer.

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
