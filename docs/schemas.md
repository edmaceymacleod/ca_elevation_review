# Payload schemas

The engine ingests two payloads and emits a third. Each is defined by a JSON
Schema (draft-07) under `engine/src/ca_elevation_engine/schemas/` -- **those files
are the source of truth.** This document is a high-level field-by-field guide to
read alongside them. The schemas are `additionalProperties: false` throughout, so
unknown keys are rejected; CI validates every fixture against them fail-closed
(`engine/tools/validate_schemas.py`, see `testing.md`).

| Payload | Schema file | Direction |
|---|---|---|
| Spec manifest | `spec_manifest.schema.json` | Revit add-in -> engine |
| Capture package | `capture_package.schema.json` | iPhone app -> engine |
| Verdict report | `verdict_report.schema.json` | engine -> add-in / report renderer |

All three carry a `schema_version` matching `^\d+\.\d+\.\d+$` (semantic version of
the *format*).

---

## Conventions: the affine and the pose

Two coordinate conventions recur and are easy to get wrong. They are implemented
in `engine/src/ca_elevation_engine/geometry.py`.

### `pixel_to_model` -- the floorplan affine

A **2x3 row-major affine**, `[a, b, c, d, e, f]`, mapping a floorplan pixel
`(px, py)` to model plan coordinates `(X, Y)`:

```
X = a*px + b*py + c
Y = d*px + e*py + f
```

It lives per-level on `levels[].floorplan.pixel_to_model` and is what turns the
operator's pin pixel into a model XY anchor. `geometry.pixel_to_model_xy` applies
it; `geometry.model_xy_to_pixel` inverts it (raising on a singular affine);
`geometry.affine_scale` returns approximate model-units-per-pixel (geometric mean
of the axes).

### `pose` -- the ARKit camera pose

A **4x4 row-major camera-to-world** transform (16 numbers) in ARKit's world frame:
right-handed, **-Z forward, +Y up**. The camera looks down its local -Z axis. The
translation column is the camera world position; `geometry.camera_position`,
`geometry.camera_forward`, and `geometry.heading_of_pose_deg` extract these.

### Angles and units

Headings/facing angles are degrees, **0 = +X, counter-clockwise**. Linear units
are the project's (`feet` or `meters`, set in the manifest `project.units` and
echoed in the report); tolerances are in those units except orientation, which is
degrees.

---

## Spec manifest (`spec_manifest.schema.json`)

The *expected* world extracted from the Revit model.

Top level (required: `schema_version`, `project`, `levels`, `devices`):

- **`project`** -- `id` (must match the capture's `project_id`), `name`, optional
  `revit_file`, optional `exported_at` (date-time), and `units` (`feet`|`meters`).
- **`coordinate_system`** (optional) -- `name` and `north_angle` (project north
  relative to true north, degrees).
- **`default_tolerances`** (optional) -- a `tolerances` object applied when a
  device omits its own.
- **`levels[]`** (>=1) -- each: `id`, `name`, `elevation` (Z of finished floor,
  project units), and `floorplan`.
- **`devices[]`** -- each expected device.

**`floorplan`** (per level; required `image`, `width_px`, `height_px`,
`pixel_to_model`):

- `image` -- relative path to the floorplan image in the bundle.
- `width_px` / `height_px` -- positive integers.
- `pixel_to_model` -- the 6-number affine described above.

**`device`** (required `id`, `family`, `type`, `level_id`, `position`):

- `id` -- stable unique device id (Revit ElementId / UniqueId).
- `family`, `type` -- Revit family and type names.
- `level_id` -- references a `levels[].id`.
- `elevation_id` (optional) -- which elevation/wall view it belongs to.
- `position` -- a `point3` (`x`, `y`, `z`), model coordinates.
- `mounting_height` (optional) -- height above finished floor; if omitted, derived
  from `position.z - level.elevation`.
- `orientation` (optional) -- `facing_angle` (degrees, 0=+X CCW) and `up_axis`
  (`up`|`down`|`left`|`right`, default `up`).
- `tolerances` (optional) -- per-device override of `default_tolerances`.
- `metadata` (optional) -- free-form object.

**`tolerances`** -- pass/flag thresholds, all `exclusiveMinimum: 0`: `position`
and `mounting_height` in project units, `orientation` in degrees.

---

## Capture package (`capture_package.schema.json`)

The *observed* world returned from the phone.

Top level (required: `schema_version`, `project_id`, `shots`):

- `project_id` -- must match the manifest `project.id`.
- `captured_at` (optional, date-time), `device_model` (e.g. "iPhone 15 Pro"),
  `app_version`.
- `shots[]` (>=1) -- the captures.

**`shot`** (required `id`, `level_id`, `rgb_image`, `intrinsics`, `pose`, `pin`):

- `id`, `level_id` (references a manifest level), optional `elevation_id`
  (user-tagged target wall).
- `rgb_image` -- relative path to the RGB image.
- `depth_map` -- relative path to a raw **float32 depth map in meters**, row-major
  HxW; if present, `depth_size` (`[height, width]`) is required.
- `point_cloud` -- relative path to an E57/PLY/PCD/XYZ/PTS cloud, an alternative
  to `depth_map`. When the optional `[heavy]` backend (Open3D/pye57) is present
  and the engine is run with the capture bundle dir, the cloud is loaded
  (`ca_elevation_engine.pointcloud`) and used to **refine** the coarse
  `arkit_to_model` transform via local rigid (no-scale) point-to-point ICP. The
  path is resolved bundle-relative and rejected if it escapes the bundle. Absence
  of the backend, the file, or the bundle dir degrades gracefully to the coarse
  transform with an explanatory note (see `device_results[].notes` below).
- `intrinsics` -- pinhole camera: `fx`, `fy` (>0), `cx`, `cy`, `width`, `height`.
- `pose` -- the 16-number 4x4 camera-to-world matrix described above.
- `pin` -- the georeference anchor (required `x`, `y`, `heading`): floorplan pixel
  the operator stood at, camera `heading` (degrees, 0=+X CCW), optional
  `confidence` (`low`|`medium`|`high`, default `medium`).
- `captured_at` (optional, date-time).
- `observations[]` (optional) -- pre-extracted candidate devices seen in this
  shot, in model coordinates, used by synthetic fixtures and as a vision-backend
  output channel. Each: `position` (required `point3`), optional `mounting_height`,
  `facing_angle`, `detected_type`, `type_confidence` (0..1).

---

## Verdict report (`verdict_report.schema.json`)

The engine's structured output -- consumed by the add-in for write-back and by the
report renderer.

Top level (required: `schema_version`, `project_id`, `device_results`, `summary`):

- `project_id`, optional `generated_at` (date-time), `engine_version`,
  `units` (`feet`|`meters`).
- `device_results[]` -- per-device outcomes.
- `summary` -- counts (all required, `minimum: 0`): `total`, `pass`, `flag`,
  `absent`, `type_mismatch`.

**`device_result`** (required `device_id`, `verdict`, `confidence`):

- `device_id`, optional `family`, `type`.
- `verdict` -- one of `pass` | `flag` | `absent` | `type_mismatch`.
- `confidence` -- 0..1.
- `matched_shot_id` -- the shot that observed it, or `null`.
- `identity_confirmed` -- boolean (default `false`); v1 leaves SKU identity
  human-confirmable rather than auto-resolved.
- `deltas` -- measured deviations, each `null` where not measurable from this
  capture: `position` (Euclidean, project units), `mounting_height`,
  `orientation` (facing-angle delta, degrees).
- `approximate` -- boolean (default `false`); true when geometry was derived
  without metric LiDAR or from a protruding/occluded device. The report never
  claims sub-inch accuracy.
- `notes[]` -- free-form strings. Registration notes for the **matched shot** are
  propagated here (prefixed `registration:`), including any ICP refinement
  residual.

> **ICP refinement honesty.** When a posed point cloud is present, ICP aligns it
> to a sparse, **floor-weighted**, device-derived model surface. It corrects small
> floor-height and planar drift in an already-good coarse transform; it is rigid
> (no scale), local (won't fix a wrong pin), and blind behind walls. Because part
> of the target is seeded from *expected* device positions, ICP must not be read as
> evidence a device is present -- it only sharpens the camera transform. The
> residual (RMSE) is reported in each affected device's `notes` (no new schema
> field) so reviewers can judge how much to trust the refinement. There is no
> sub-inch claim.
