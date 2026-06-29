# Implementation Spec — Real point-cloud registration ingest (E57 + posed images, heavy path)

Work item: **registration**
Target: `engine/` (CPython OSS core, Linux, headless).
Status: build-ready (hardened after adversarial review — see §11).

## 1. Problem & intent

Phase 0's stated goal is to prove the engine on **real** SiteScape/Polycam exports
(E57 + posed images), not only synthetic `observations[]`. Today:

- `register.coarse_register()` builds a deterministic pin+pose → model transform.
- `register.refine_registration()` is a stub: it checks `shot.point_cloud is not None`,
  tries `import open3d`, and otherwise appends a note and returns `reg` unchanged.
  It never loads any actual point-cloud bytes, never runs ICP, and has no test that
  exercises a real cloud.
- `ingest.py` loads/validates the two JSON payloads but does **not** load the binary
  point-cloud files referenced by `shot.point_cloud` (a relative path into the bundle).

This work item implements the real ingest path for posed point clouds:

1. A point-cloud **loader** (`pointcloud.py`) that resolves `shot.point_cloud` relative
   to `bundle_dir`, reads E57 (via `pye57`) or generic formats (PLY/PCD/XYZ/PTS via
   `open3d`), and returns an in-memory `(N,3) float64` numpy array — behind lazy imports.
2. An **ICP refinement** in `refine_registration()` that aligns the shot's cloud
   (brought into the model frame by the coarse transform) against a model-surface
   target, and folds the correction into `reg.arkit_to_model`, setting
   `reg.refined=True` and `reg.residual`.
3. A **note-propagation seam** so the registration's residual/limitation notes reach
   the verdict report through the *existing* free-text `notes` arrays
   (`Match.notes` → `DeviceResult.notes`). **No schema change is required** (§9, §11/F1).
4. **Graceful degradation**: if `bundle_dir` is None, the file is missing, or the
   heavy backend is absent, the coarse path is returned unchanged with an explanatory
   note. The default `pytest -m "not heavy"` suite stays green with **zero** heavy
   deps installed.

Honesty constraint (encoded in notes + docs, and now actually wired to the report — §9):
ICP here is a **local rigid refinement** of an already-good coarse transform. With a
single posed cloud and a synthetic/sparse model-surface target it can correct small
translation/yaw drift; it **cannot** fix gross mis-pinning, cannot recover scale (we run
point-to-point **rigid** ICP, `with_scaling=False`), and cannot see behind walls. We do
not claim sub-inch accuracy. The model-surface target is partly seeded from *expected*
device positions, which couples refinement to the hypothesis under test; the spec
weights the target toward the hypothesis-free floor plane and documents the coupling
(§3.5, §11/F9).

## 2. Files to add / change

| File | Change |
|---|---|
| `engine/src/ca_elevation_engine/pointcloud.py` | **NEW** — lazy point-cloud loader + pure-numpy helpers (downsample, model-surface target builder). |
| `engine/src/ca_elevation_engine/register.py` | Implement real `refine_registration()` ICP; add `_icp_refine()` helper; new notes. (`bundle_dir` already threaded — §4.3.) |
| `engine/src/ca_elevation_engine/compare.py` | **Propagate** the matched shot's registration notes (incl. ICP residual) into `Match.notes` so they reach the report. Small, additive change (§4.4). |
| `engine/tests/test_register.py` | Add unit tests for graceful degradation (no heavy, missing file, no bundle_dir). (Heavy ICP test lives in its own file — §6, §11/F6.) |
| `engine/tests/test_register_icp_heavy.py` | **NEW** — the single `@pytest.mark.heavy` ICP test, in its own module so it does NOT inherit a module-level `unit` mark (§11/F6). |
| `engine/tests/test_pointcloud.py` | **NEW** — pure-helper tests (downsample, target builder, path resolution). Opens with `pytestmark = pytest.mark.unit` (§11/F7). |
| `engine/tests/test_compare.py` (existing) | Add a unit test that registration notes surface in `Match.notes`/`DeviceResult.notes` (§4.4, §6). |
| `engine/tests/conftest.py` | Add fixtures: `tiny_ply_path` (writes a synthetic ASCII PLY to tmp) and a `make_cloud` numpy factory. |
| `engine/pyproject.toml` | No dependency changes (heavy extra already lists `open3d`/`pye57`/`opencv`). |
| `docs/schemas.md` / `docs/architecture.md` | One-paragraph honesty note on what ICP refinement does/doesn't do, and how its residual reaches the report. |

**No wire-schema changes. No new wire fields.** `shot.point_cloud` already exists, and
`device_results[].notes` (free-text `array` of `string`) already exists in
`verdict_report.schema.json` — the residual is reported through that existing field
(§9, §11/F1).

Path-resolution helpers live in `pointcloud.py` and are tested there directly. We do
**not** add speculative `ingest.resolve_bundle_path` / `ingest.load_point_cloud`
wrappers in v1 (§11/F8): no current caller needs them, and `register` calls
`pointcloud` directly to keep the module boundary honest. If a concrete pyrevit/CLI
caller later needs the seam, add the thin wrapper then.

## 3. New module: `pointcloud.py`

Pure-numpy core + lazily-imported heavy readers. **No top-level `import open3d`/`import pye57`.**

```python
"""Optional point-cloud ingest for the heavy registration path.

Resolves and loads the binary point cloud a shot references (`shot.point_cloud`,
a path relative to the capture bundle) into an (N,3) float64 numpy array in the
capture's ARKit world frame. E57 is read via pye57; PLY/PCD/XYZ/PTS via Open3D.
Both are OPTIONAL [heavy] backends, imported lazily; absence is reported, never
fatal.

Pure helpers (downsampling, the model-surface target) are numpy-only so they are
unit-testable headlessly with no heavy backend installed.
"""
from __future__ import annotations
import math
import os
from pathlib import Path

import numpy as np


class PointCloudBackendMissing(RuntimeError):
    """Raised when a cloud is present but no heavy backend can read it."""


class PointCloudPathError(ValueError):
    """Resolution/containment failure for a bundle-relative cloud path.

    A ValueError subclass so callers that already degrade on ValueError catch it,
    while still letting tests assert the precise security signal by type.
    """


SUPPORTED_SUFFIXES = (".e57", ".ply", ".pcd", ".xyz", ".pts")
```

### 3.1 `resolve_cloud_path(rel_path: str | None, bundle_dir: str | None) -> Path | None`

Hardened against the path-traversal issues the review raised (§11/F2). Exact algorithm:

```python
def resolve_cloud_path(rel_path, bundle_dir):
    if not rel_path or bundle_dir is None:
        return None
    base = Path(bundle_dir).resolve()             # resolves symlinks on bundle_dir
    # Reject absolute rel_path outright (would escape the bundle by construction).
    if Path(rel_path).is_absolute():
        raise PointCloudPathError("point_cloud path must be bundle-relative")
    # Lexical normalization of the JOINED path (does NOT require the file to exist),
    # so an in-tree `clouds/../clouds/s.ply` normalizes back inside the bundle.
    cand = Path(os.path.normpath(base / rel_path))
    if cand != base and base not in cand.parents:
        raise PointCloudPathError("point_cloud path escapes bundle")
    return cand   # may or may not exist; the loader decides existence
```

Notes:
- We deliberately do **not** use `os.path.commonpath`. `commonpath` raises a bare
  `ValueError` on mixed absolute/relative inputs (and on differing Windows drives),
  which would leak as the wrong error type and get swallowed by `refine_registration`'s
  broad `ValueError` degrade-path as "not loadable" rather than the intended
  "escapes bundle" security signal. Using the `base not in cand.parents` containment
  check, raising our own `PointCloudPathError`, avoids that.
- We normalize **lexically** (`os.path.normpath` on the joined path) for the containment
  check — `Path.resolve()` on a non-existent candidate behaves inconsistently across
  Python versions and would also require the file to exist to resolve `..` through
  symlinks. `base` itself is `resolve()`d once so a symlinked bundle dir is handled.
- If `bundle_dir` does not exist, `base = Path(bundle_dir).resolve()` still returns a
  normalized absolute path (no error); the containment check still holds, and the
  loader's later existence check (§3.2) raises `FileNotFoundError` for the file. This
  keeps "bundle dir missing" and "file missing" on the same degrade path.
- Returns the `Path` even if it does not exist (caller/loader decides existence).

### 3.2 `load_point_cloud(rel_path, bundle_dir, *, max_points=200_000) -> np.ndarray`

- Resolve via `resolve_cloud_path`. If it returns `None` (no `rel_path` or no
  `bundle_dir`) → raise `ValueError("no point_cloud / no bundle_dir")`. (Callers in
  `register` catch broadly and degrade; see §4.)
- If the resolved path does not exist → `FileNotFoundError(path)`.
- Dispatch on the lowercased suffix:
  - `.e57` → `_load_e57(path)`
  - `.ply` / `.pcd` / `.xyz` / `.pts` → `_load_o3d(path)`
  - else → `ValueError(f"unsupported point-cloud format: {suffix}")`
- Drop NaN/Inf rows: `pts = pts[np.isfinite(pts).all(axis=1)]`.
- If `len(pts) == 0` after filtering → `ValueError("empty point cloud after NaN/Inf filter")`.
- If `len(pts) > max_points`, uniformly subsample via a **deterministic** stride —
  no RNG, so heavy tests are reproducible:
  `stride = math.ceil(len(pts) / max_points); pts = pts[::stride]`.
- Return `(N,3) float64`, C-contiguous.

### 3.3 `_load_e57(path) -> np.ndarray` (lazy) — PROVISIONAL API, highest-risk code

```python
def _load_e57(path):
    try:
        import pye57
    except Exception as exc:  # pragma: no cover - heavy
        raise PointCloudBackendMissing("pye57 not installed; cannot read E57") from exc
    e57 = pye57.E57(str(path))
    if e57.scan_count < 1:
        raise ValueError(f"E57 has no scans: {path}")
    data = e57.read_scan(0, ignore_missing_fields=True)  # verified against pye57 X.Y
    xyz = np.column_stack([data["cartesianX"], data["cartesianY"], data["cartesianZ"]])
    return np.ascontiguousarray(xyz, dtype=np.float64)
```

**Implementer obligation (verification, not assertion):** the `pye57` API
(`E57(...)`, `scan_count`, `read_scan(0, ignore_missing_fields=True)`, dict keys
`cartesianX/Y/Z`) varies across 0.x releases — some use `read_scan_raw`, some return
different keys, and scan 0 may not exist. Before merging, **pin and verify against the
actually-resolved `pye57` version** and replace the `# verified against pye57 X.Y`
placeholder with the real version. Guard `scan_count` so a 0-scan file degrades to a
clear `ValueError` rather than an IndexError.

**Known coverage gap (state it, don't paper over it):** the E57 read path has **zero
automated coverage in default CI** — the only test that can exercise it is the optional
`@pytest.mark.heavy` E57 round-trip, which is itself conditional on `pye57` being able
to *write* a fixture (§6). E57 read is therefore the **highest-risk code in this item**
and must be smoke-tested by hand against one real SiteScape/Polycam E57 export before
the Phase-0 "prove on real exports" claim is made. The module does **not** transform
coordinates — the coarse `arkit_to_model` does that downstream.

### 3.4 `_load_o3d(path) -> np.ndarray` (lazy)

```python
def _load_o3d(path):
    try:
        import open3d as o3d
    except Exception as exc:  # pragma: no cover - heavy
        raise PointCloudBackendMissing("open3d not installed; cannot read this cloud") from exc
    pcd = o3d.io.read_point_cloud(str(path))
    pts = np.asarray(pcd.points, dtype=np.float64)
    if pts.size == 0:
        raise ValueError(f"empty point cloud: {path}")
    return pts
```

### 3.5 `model_surface_target(manifest, level_id, *, spacing=0.5, floor_pad=3.0) -> np.ndarray | None`

Pure numpy. Build a sparse synthetic point set representing the model surfaces the
cloud should align to. **v1 is deliberately minimal and honest**: the engine inputs
carry no model mesh, only device positions and the level elevation. Build the target
from two parts, **weighting toward the hypothesis-free floor plane** (§11/F9):

- **Floor plane patch (primary, hypothesis-free):** a dense grid of points at
  `z = level.elevation` spanning the XY bounding box of the level's devices, padded by
  `floor_pad` project units, at `spacing` resolution. This is the dominant cue and is
  independent of whether any device is actually installed.
- **Device clusters (secondary, weak cue):** for each device on the level, a *small*
  cluster (e.g. a single representative point, or ≤3 points) at `device.position`. These
  are intentionally **down-weighted by count** (the floor grid contributes far more
  points), so a missing-on-site device — the exact thing this engine exists to catch —
  does not meaningfully pull the rigid fit toward a surface that isn't there.

Return `None` if the level has no devices (nothing to anchor the XY extent → caller
skips ICP with a note).

**Documented limitation (must be encoded in `reg.notes`, see §4.1 step 5):** the target
is sparse and partly device-derived. ICP should converge primarily on **floor height +
small planar drift**; device clusters are a weak secondary cue and couple refinement to
the expected model. We do not treat device-cluster agreement as evidence a device is
present.

Determinism: the grid is generated by `np.arange`/`np.meshgrid` with fixed ordering; no
RNG. Returns a deterministic `(M,3) float64` array.

### 3.6 `_downsample(pts, voxel) -> np.ndarray` (pure numpy, no Open3D)

Voxel-grid downsample that returns **real original input points** (not voxel-key floors),
**deterministically ordered**, and is the *first original point per occupied voxel in
input order* (§11/F3):

```python
def _downsample(pts, voxel):
    if voxel <= 0:
        raise ValueError("voxel must be > 0")
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) == 0:
        return pts
    keys = np.floor(pts / voxel).astype(np.int64)          # integer voxel coords
    # `return_index` gives the index of the first occurrence of each unique key in
    # SORTED order; sort those indices ascending to recover original (input) order,
    # then index back into `pts` so we return ACTUAL input points.
    _, idx = np.unique(keys, axis=0, return_index=True)
    idx = np.sort(idx)
    return pts[idx]
```

Documented contract: returns a subset of the *original* points (one representative per
occupied voxel), ordered by first appearance in the input. Used to bound ICP cost
without needing Open3D, and unit-testable headlessly.

## 4. `register.py` changes

### 4.1 `refine_registration(reg, shot, manifest, bundle_dir=None) -> ShotRegistration`

Replace the stub body with the degrade-on-any-failure flow (never raises out of this
function):

1. If `shot.point_cloud is None`: return `reg` unchanged (existing behavior — no note).
2. Try to load the cloud:
   ```python
   from . import pointcloud as pc
   try:
       pts = pc.load_point_cloud(shot.point_cloud, bundle_dir)
   except pc.PointCloudBackendMissing as exc:
       reg.notes.append(f"point cloud present but backend missing: {exc}; skipped ICP")
       return reg
   except (FileNotFoundError, ValueError) as exc:  # incl. PointCloudPathError (ValueError subclass)
       reg.notes.append(f"point cloud not loadable ({exc}); skipped ICP refinement")
       return reg
   ```
   When `bundle_dir is None` (the entire current headless/default flow),
   `load_point_cloud` raises `ValueError("no point_cloud / no bundle_dir")`, caught here →
   coarse path returned with a note. **No heavy import is attempted** in that case
   because dispatch happens only after path resolution. This is what keeps default CI
   green with zero heavy deps.
3. Build the model-surface target:
   ```python
   target = pc.model_surface_target(manifest, shot.level_id)
   if target is None:
       reg.notes.append("no model surfaces to align to on this level; skipped ICP")
       return reg
   ```
4. Run ICP via `_icp_refine(reg, pts, target)` (§4.2). On **any** exception (incl.
   a lazy `PointCloudBackendMissing` from the Open3D import inside `_icp_refine`),
   degrade with a note and return the un-refined `reg`:
   ```python
   try:
       correction, rmse = _icp_refine(reg, pts, target)
   except pc.PointCloudBackendMissing as exc:
       reg.notes.append(f"point cloud present but backend missing: {exc}; skipped ICP")
       return reg
   except Exception as exc:  # noqa: BLE001 - degrade, never propagate
       reg.notes.append(f"ICP failed ({exc}); kept coarse registration")
       return reg
   ```
5. On success, update the registration and surface the residual honestly:
   - `reg.arkit_to_model = correction @ reg.arkit_to_model`
   - `reg.refined = True`
   - `reg.residual = rmse`
   - Recompute `reg.camera_model_position = geo.transform_point(reg.arkit_to_model, geo.camera_position(shot.pose))`
     and `reg.camera_model_heading = geo.heading_of_pose_deg_from_matrix(reg.arkit_to_model, shot.pose)`.
   - Confidence policy (residual-gated): if `rmse < HIGH_RESIDUAL_FT` (a sane threshold,
     e.g. `0.25` project units) raise confidence modestly
     (`reg.confidence = min(0.9, reg.confidence + 0.15)`); else keep confidence and add
     `"high ICP residual (rmse={rmse:.4f}); refinement uncertain"`.
   - Honesty note (this is the one the report shows — §9): append
     `f"ICP refinement applied: rmse={rmse:.4f} {units}, {n_pts} pts (rigid, no scale; "
     f"aligned to sparse floor+device surfaces)"`.
   `units` comes from `manifest.project.units`; `n_pts` is the post-downsample source count.

### 4.2 `_icp_refine(reg, source_pts, target_pts, *, max_corr=0.5, max_iter=50) -> tuple[np.ndarray, float]` (NEW, heavy)

Lazy Open3D point-to-point **rigid** ICP. Returns `(correction_4x4, rmse)` where
`correction` is applied **in model space** (left-multiplied onto `arkit_to_model`). The
transform of the source cloud into model space is **vectorized** — no Python per-point
loop (§11/F5):

```python
def _icp_refine(reg, source_pts, target_pts, *, max_corr=0.5, max_iter=50):
    try:
        import open3d as o3d  # lazy
    except Exception as exc:  # pragma: no cover - heavy
        from . import pointcloud as pc
        raise pc.PointCloudBackendMissing("open3d not installed; cannot run ICP") from exc
    from . import pointcloud as pc

    R = reg.arkit_to_model[:3, :3]
    t = reg.arkit_to_model[:3, 3]
    src_model = (R @ source_pts.T).T + t          # vectorized, (N,3)
    src_model = pc._downsample(src_model, voxel=0.1)

    src = o3d.geometry.PointCloud()
    src.points = o3d.utility.Vector3dVector(src_model)
    tgt = o3d.geometry.PointCloud()
    tgt.points = o3d.utility.Vector3dVector(target_pts)

    result = o3d.pipelines.registration.registration_icp(
        src, tgt, max_corr, np.eye(4),
        o3d.pipelines.registration.TransformationEstimationPointToPoint(with_scaling=False),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iter),
    )
    correction = np.asarray(result.transformation, dtype=np.float64)  # model->model rigid
    return correction, float(result.inlier_rmse)
```

- **Scale locked** (`with_scaling=False`): rigid only — we do not invent scale.
- `correction` maps coarse-model-frame → refined-model-frame, so the new transform is
  `correction @ reg.arkit_to_model`. The heavy test (§6) asserts this composition order
  with a known synthetic offset.
- Uses the **post-0.10 Open3D namespace** (`o3d.pipelines.registration.*`), i.e.
  `open3d>=0.17` (matches the heavy extra pin in `pyproject.toml`).
- **Coverage caveat to call out:** `pyproject.toml` gates `open3d` off for Linux +
  Python ≥ 3.13 (`platform_system != 'Linux' or python_version < '3.13'`). On this box
  (CPython 3.11, Linux) open3d is installable, but a **Linux + py3.13 contributor gets
  no open3d at all**, so the heavy ICP test silently never runs there. This is a real
  coverage gap, not a guarantee — do not assume the heavy test protects the ICP path on
  every contributor's machine (§11/F4).

### 4.3 `register_capture` — no signature change

`bundle_dir` is already threaded `register_capture → refine_registration` (verified
`register.py:158-169`) and from `pipeline.run_pipeline` / `cli`. No signature churn.
Refinement now does real work when `bundle_dir` + heavy deps are present.

### 4.4 `compare.py` — propagate registration notes to the report (resolves F1)

This is the load-bearing fix for the spec's honesty story. Today
`compare.match_device` consumes `registrations` only for the geometric transform; it
**never** copies `ShotRegistration.notes` into `Match.notes`, and the report renders
`DeviceResult.notes` (← `Match.notes`). So every ICP note ("rmse=…", "high residual",
"backend missing") is dropped before the report.

Fix — additive, no schema change (the residual rides the **existing** free-text
`notes` array):

- In `match_device`, **after** `match.matched_shot_id` is set (the success branch,
  `compare.py` ~line 184), copy the matched shot's registration notes onto the match:
  ```python
  reg = registrations.get(shot_id)
  if reg is not None and reg.notes:
      # Prefix so the report makes the provenance obvious.
      match.notes.extend(f"registration: {n}" for n in reg.notes)
  ```
  Place this where `shot_id` is the matched shot (so we surface the residual of the shot
  the device was actually matched against, not every shot).
- `classify` already does `notes=list(match.notes)` (verdict.py:62), and the renderers
  already print `DeviceResult.notes` (pdf.py:196, html.py:161-162, text_summary.py:58).
  So once `Match.notes` carries the registration notes, `reg.residual` reaches the PDF/
  HTML/JSON/text report **with no schema change** — `verdict_report.schema.json` already
  declares `device_results[].notes` as `array<string>` (verified line 60).

**Why this is not the schema change the reviewer feared:** the reviewer's F1 fix
option (a) assumed surfacing the residual needed a new structured field in
`verdict_report.schema.json`, contradicting §8's "no schema changes." It does not: the
residual is reported as human-readable text in the *existing* `notes` array. We
therefore implement option (a)'s intent (residual reaches the report) **without** any
schema modification. §8's "no schema changes" stands, and the §1/§9 honesty story is now
actually implemented rather than asserted.

**Coarse notes already flow too:** note that `coarse_register` already appends notes
like "no depth/point-cloud: geometry from pose+pin only (approximate)". Before this fix
those were *also* being dropped at the compare seam. After this fix they correctly reach
the report. This is a behavior change for the matched-device path — see §6/golden
invariant and §11/F10 for how default goldens are protected.

## 5. Module boundaries (no speculative seam)

`register` imports `pointcloud` directly (lazy, in-function) for loading and ICP;
`register` does **not** import `ingest` (keeps the existing graph: `register → geometry,
models` only). `compare` already imports `register` for the `ShotRegistration` type, so
reading `reg.notes` there adds no new edge.

We **do not** add `ingest.resolve_bundle_path` / `ingest.load_point_cloud` wrappers in
v1 (§11/F8): no concrete CLI/pyrevit caller needs them, and adding dead public API plus a
`register→ingest` (or `ingest→pointcloud`) edge for no consumer is YAGNI. Path-resolution
and loader tests target `pointcloud` directly. If a real caller later needs the seam, the
thin wrapper is a one-liner to add then.

## 6. Test plan (headless-first)

All non-heavy tests must pass with **only** `jsonschema` + `numpy` installed
(no open3d/pye57/opencv). The single heavy test carries `@pytest.mark.heavy` and
`pytest.importorskip("open3d")` so it SKIPs (not fails/errors) when the backend is absent.

### conftest additions
- `tiny_ply_path(tmp_path)` → write a minimal **ASCII PLY** (≈30 points: a small floor
  grid + a cluster at a known device position) into a tmp bundle dir, return
  `(path, bundle_dir)`. Pure-text write — **no heavy dep needed to create it**.
- `make_cloud()` → numpy factory returning an `(N,3)` array (floor grid + device
  cluster), optionally with a **known applied offset** (e.g. +0.2 in X, +0.05 in Z) used
  as the ICP source so the heavy test can assert ICP recovers ≈ the inverse offset.

### Unit tests — default suite (every module below opens with `pytestmark = pytest.mark.unit`)

**test_pointcloud.py (NEW)** — `pytestmark = pytest.mark.unit` (§11/F7). Pure helpers +
path resolution, no heavy backend:
- `test_resolve_cloud_path_joins` — `resolve_cloud_path("clouds/s.ply", bundle)` →
  path under bundle.
- `test_resolve_cloud_path_none_without_bundle` — `bundle_dir=None` → `None`;
  `rel_path=""`/`None` → `None`.
- `test_resolve_cloud_path_accepts_in_tree_dotdot` — `"clouds/../clouds/s.ply"` is
  **accepted** and normalizes inside the bundle (§11/F2 regression guard).
- `test_resolve_cloud_path_rejects_traversal` — `"../../etc/passwd"` raises
  `PointCloudPathError` (a `ValueError`).
- `test_resolve_cloud_path_rejects_absolute` — `"/etc/passwd"` raises `PointCloudPathError`.
- `test_load_point_cloud_missing_bundle_raises` — `load_point_cloud("x.ply", None)` →
  `ValueError`.
- `test_load_point_cloud_missing_file_raises` — valid bundle, absent file →
  `FileNotFoundError`.
- `test_load_point_cloud_unsupported_suffix` — `"x.foo"` (file present) → `ValueError`.
- `test_downsample_collapses_voxel` — near-duplicate points collapse, count drops,
  **output points are a subset of the input** (assert each returned row is present in
  the input — guards the "real original point" contract), and output is input-ordered.
- `test_downsample_empty_and_bad_voxel` — empty input returns empty; `voxel<=0` raises.
- `test_model_surface_target_has_floor_and_devices` — target z includes
  `level.elevation`; contains a point near each device position; floor grid dominates
  the cluster point count (assert floor points ≫ device points → §11/F9 weighting);
  deterministic shape across two calls.
- `test_model_surface_target_empty_level_returns_none` — level with no devices → `None`.

**test_register.py** (existing module, `pytestmark = pytest.mark.unit`) — graceful
degradation, the load-bearing headless guarantees:
- `test_refine_noop_without_point_cloud` — `point_cloud=None` → `reg` unchanged,
  `refined is False`, **no new note**.
- `test_refine_degrades_without_bundle_dir` — shot WITH `point_cloud="s.ply"`,
  `bundle_dir=None` → `refined is False`, a note mentions skipped ICP. **Asserts no
  exception and that open3d/pye57 were never imported** (works with heavy absent). Core
  "default CI green" test.
- `test_refine_degrades_when_file_missing` — real tmp `bundle_dir`, `point_cloud`
  pointing at a non-existent file → `refined is False`, note about not loadable.
- `test_register_capture_still_covers_all_shots_with_cloud_refs` — a capture whose shots
  reference clouds but no bundle present still returns one registration per shot (no crash).
- `test_refine_backend_missing_note_via_monkeypatch` — monkeypatch
  `pointcloud.load_point_cloud` to raise `PointCloudBackendMissing`; assert the
  "backend missing" note path is taken **without** installing heavy deps (covers that
  branch headlessly).

**test_compare.py** (existing module) — F1 propagation:
- `test_registration_notes_surface_in_match_and_result` — register a capture where the
  matched shot's `reg.notes` carries a synthetic note (e.g. seed via a coarse "approximate"
  note, or set `reg.notes` directly), run `match_device` + `classify`, and assert the note
  appears in `Match.notes` and the resulting `DeviceResult.notes` (prefixed `registration:`).
  This pins the F1 fix and guards against regressing the residual-to-report path.

### Heavy test — `@pytest.mark.heavy`, in its OWN module (no `unit` mark)

**test_register_icp_heavy.py (NEW)** — this file does **not** set
`pytestmark = pytest.mark.unit`, so the heavy test is marked **only** `heavy`
(resolves F6: avoids the double `unit`+`heavy` marking that would let `pytest -m unit`
select a heavy test). `pytest -m "not heavy"` deselects it; `pytest -m unit` does not
select it.

```python
import pytest
import numpy as np

@pytest.mark.heavy
def test_icp_refines_known_offset(tmp_path, make_cloud, ...):
    o3d = pytest.importorskip("open3d")
    # Build a coarse reg + a synthetic source cloud = target surfaces + small known
    # offset; write the source to an ASCII PLY in a tmp bundle; set shot.point_cloud.
    reg2 = refine_registration(coarse_reg, shot, manifest, bundle_dir=str(bundle))
    assert reg2.refined is True
    assert reg2.residual is not None
    # Tolerance tied to the alignment geometry, NOT a magic 0.05 (resolves F3):
    # the goal is "ICP pulled the cloud toward truth", not a specific RMSE on a
    # downsampled cloud under Open3D version variance.
    assert reg2.residual < 0.5 * 0.1            # < 0.5 * voxel
    # Composition order: applying the refined transform lands the source on target
    # within max_corr, and the camera position is closer to known-true than coarse.
    assert <camera position closer to known-true than coarse>
```

Heavy assertion is **tolerance-tied** (`residual < 0.5 * voxel`, equivalently `< max_corr`),
not the fragile magic `< 0.05`, because the cloud is downsampled at `voxel=0.1` and
Open3D ICP RMSE varies by version (resolves F3).

**Optional E57 heavy case** — `pytest.importorskip("pye57")` and round-trip a tiny E57
**only if** the installed `pye57` can *write* one; if it cannot, **skip** E57 read-path
heavy coverage and rely on the PLY/Open3D path, **noting the limitation in the test
docstring**. Do not block the item on E57 write support. (This is why §3.3 flags E57
read as the highest-risk, lowest-coverage code.)

### CI invariants to re-confirm after implementation
- `cd engine && pytest -q -m "not heavy"` → all green with **NO heavy deps installed**
  (new degradation + pure-helper + compare-propagation tests run; the ICP test is
  deselected).
- `pytest -m unit` selects only `unit`-marked tests — **not** the heavy ICP test
  (guaranteed by putting it in a module without the `unit` `pytestmark`).
- `ruff check engine && ruff format --check engine` clean.
- `import open3d` / `import pye57` appear **only** inside function bodies (no
  module-level heavy imports). Add `test_pointcloud_imports_without_heavy` that
  `importlib.import_module("ca_elevation_engine.pointcloud")` succeeds with heavy absent
  (pins the lazy-import guarantee for the new module).
- **Golden invariant (resolves F10):** the F1 fix now propagates *matched-shot*
  registration notes into `DeviceResult.notes`. If a default fixture's matched shot
  carries coarse notes (e.g. the "approximate" note), the golden's `notes` array changes.
  Verified today: **no default fixture sets `point_cloud`** and the f01 fixtures use
  `depth_map`. But coarse `coarse_register` *can* emit notes (the pose+pin-only note
  fires only when **both** `depth_map` and `point_cloud` are None — f01 has `depth_map`,
  so it does not fire). **Action:** after implementing §4.4, run the integration/golden
  suite; if any golden's `notes` shifts, **regenerate the golden** and record the diff in
  the PR. Add an invariant comment to `docs/testing.md`: "registration notes for the
  matched shot now reach `device_results[].notes`; if a fixture's matched shot gains a
  registration note (or a `point_cloud`), regenerate goldens."

## 7. Graceful degradation summary (this Linux / no-Revit / no-heavy box)

| Condition | Behavior |
|---|---|
| `shot.point_cloud is None` | coarse transform only; no note change (unchanged). |
| `point_cloud` set, `bundle_dir is None` | resolve → `None` → `ValueError` caught → note "skipped ICP", coarse returned. **No heavy import attempted.** |
| `point_cloud` absolute / escapes bundle | `PointCloudPathError` (a `ValueError`) caught → note "not loadable", coarse returned. |
| `point_cloud` set, file missing | `FileNotFoundError` caught → note, coarse returned. |
| file present, open3d/pye57 absent | `PointCloudBackendMissing` caught → note "backend missing", coarse returned. |
| level has no devices | `model_surface_target` → `None` → note, coarse returned. |
| ICP raises mid-run | caught → note "ICP failed", coarse returned. |
| ICP high residual | `refined=True`, residual recorded, confidence NOT raised, "high residual" note. |
| everything present + good | `refined=True`, residual set, transform updated, confidence nudged, residual note reaches report. |

The default headless suite never hits a heavy import because every default test either
has no `point_cloud`, no `bundle_dir`, or monkeypatches the loader.

## 8. Non-goals (explicit)

- **No new wire schema fields, and no schema changes at all.** `point_cloud` already
  exists (consumed); `device_results[].notes` already exists (the residual rides it as
  text — §4.4, §9). `verdict_report.schema.json` is untouched.
- **No model mesh ingest.** The engine inputs carry no Revit geometry; the ICP target is
  a sparse floor+device surrogate (floor-weighted — §3.5), not a real BIM mesh.
- **No scale recovery.** ICP is rigid (`with_scaling=False`).
- **No global/coarse registration (RANSAC + FPFH).** v1 ICP is a *local refinement* of a
  known-good coarse transform; it will not rescue a badly mis-placed pin.
- **No depth-map → cloud conversion** in this item (`depth_map` ingest stays separate).
- **No OpenCV use yet.** `opencv` stays in the heavy extra for future vision work.
- **No change to `verdict` logic.** `compare` change is limited to *propagating* existing
  registration notes; verdict classification rules are unchanged.
- **No observation extraction from clouds.** Refinement only sharpens `arkit_to_model`;
  turning points into `Observation`s is a separate, later item. The cloud improves the
  *transform*, not device detection.
- **No new runtime dependency in the core.** `pyproject.toml` core deps unchanged; heavy
  stays optional.

## 9. Honesty notes (surfaced in the report and docs)

Encoded in `reg.notes` (now propagated to `device_results[].notes` via §4.4 — and
verified to render in pdf/html/json/text) and added to `docs/schemas.md` /
`docs/architecture.md`:

> ICP refinement aligns a posed point cloud to a sparse, **floor-weighted**,
> device-derived model surface. It corrects small floor-height and planar drift in an
> already-good coarse transform; it is rigid (no scale), local (won't fix a wrong pin),
> and blind behind walls. Because part of the target is seeded from *expected* device
> positions, ICP must not be read as evidence a device is present — it only sharpens the
> camera transform. The residual (RMSE) is reported in each affected device's notes so
> reviewers can judge how much to trust the refinement.

## 10. Determinism guarantees

- Loader subsampling uses a fixed integer stride (no RNG).
- `_downsample` returns input-ordered original points (no RNG, no sort-order surprise).
- `model_surface_target` is grid-generated with fixed ordering (no RNG).
- ICP init is `np.eye(4)`; iteration count is fixed. The only residual variance is
  Open3D's internal nearest-neighbor numerics across versions, which is why the heavy
  assertion is tolerance-tied (§6), and why the heavy test is excluded from default CI.

## 11. Adversarial review resolutions

Every blocker/major from `spec-registration.review.md` is resolved below; minors resolved
where cheap, with justification where we diverge.

- **F1 (BLOCKER) — "notes already wired to report" was false.** Resolved by §4.4: add
  explicit propagation in `compare.match_device` copying the *matched shot's*
  `ShotRegistration.notes` (which now include `rmse=…`) into `Match.notes`, which
  `classify` already forwards to `DeviceResult.notes`, which all renderers already print.
  **Crucially, this needs NO schema change** — `verdict_report.schema.json` already
  declares `device_results[].notes` as `array<string>` (verified line 60), so the
  residual is reported as text. This implements the reviewer's option (a) intent
  (residual reaches the report) while keeping §8's "no schema changes" true, dissolving
  the contradiction the reviewer flagged. The §1/§9 honesty story is now implemented,
  not asserted. A new `test_compare.py` test pins it.

- **F2 (MAJOR) — path-traversal guard mis-fires / wrong error type.** Resolved by §3.1:
  `base = Path(bundle_dir).resolve()`, lexical `os.path.normpath(base / rel_path)`,
  containment via `cand != base and base not in cand.parents`. We **avoid
  `os.path.commonpath`** (its bare `ValueError` would be swallowed as "not loadable").
  Absolute `rel_path` is rejected explicitly. Behavior when `bundle_dir` doesn't exist is
  pinned (resolves to a normalized path; file existence is the loader's job). A
  dedicated `PointCloudPathError(ValueError)` lets tests assert the security signal by
  type while still degrading through the existing `ValueError` path. Added a regression
  test that in-tree `clouds/../clouds/s.ply` is **accepted**.

- **F3 (MAJOR) — non-deterministic/incorrect `_downsample` + fragile heavy assertion.**
  Resolved by §3.6: compute integer voxel keys, `np.unique(keys, return_index=True)`,
  `np.sort(idx)`, then `pts[idx]` — returns **real original points** in **input order**,
  deterministically. Heavy assertion loosened from magic `< 0.05` to `residual < 0.5*voxel`
  (≈ `< max_corr`), tied to the alignment geometry (§6), since the goal is "ICP pulled
  toward truth," not a specific RMSE on a downsampled cloud under Open3D version variance.

- **F4 (MAJOR) — backend APIs asserted, not verified.** Resolved by §3.3: the `pye57`
  call is marked **PROVISIONAL**, requires the implementer to pin/verify against the
  resolved `pye57` version (replace the `# verified against pye57 X.Y` placeholder), and
  guards `scan_count`. The spec **states explicitly** that E57 read has **zero automated
  CI coverage** and is the **highest-risk code in the item**, to be hand-smoke-tested
  against a real export. The Open3D namespace/version pin and the **py3.13-Linux open3d
  coverage gap** are called out in §4.2 as a real gap, not a guarantee.

- **F5 (MAJOR) — mandated "vectorized" transform but shipped an O(N) Python loop.**
  Resolved by §4.2: the reference code is now **normatively vectorized**
  (`(R @ source_pts.T).T + t`); the per-point `geo.transform_point` loop is removed from
  the snippet so it can't be copied.

- **F6 (MINOR) — heavy ICP test double-marked `unit`+`heavy`.** Resolved by §2/§6: the
  heavy test lives in a **new module `test_register_icp_heavy.py` with no module-level
  `pytestmark`**, so it is marked only `heavy`. `pytest -m unit` will not select it.

- **F7 (MINOR) — new `test_pointcloud.py` lacked a marker.** Resolved by §6: the module
  opens with `pytestmark = pytest.mark.unit`.

- **F8 (MINOR) — speculative `ingest` wrappers.** Resolved (agreed with reviewer) by §2/§5:
  **dropped from v1** (YAGNI). `register` calls `pointcloud` directly; path/loader tests
  target `pointcloud`. No `register→ingest` edge, no dead public API. Re-add the thin
  wrapper only when a concrete CLI/pyrevit caller needs it.

- **F9 (MINOR) — device-cluster target biases ICP toward devices that may not exist.**
  Resolved by §3.5: target is **floor-weighted** (dense floor grid dominates; device
  clusters are ≤ a few points each, down-weighted by count), so a missing-on-site device
  does not meaningfully pull the rigid fit. The §9 honesty note states ICP must not be
  read as evidence of device presence, and a unit test asserts floor points ≫ device
  points.

- **F10 (MINOR) — golden determinism relied on implicitly.** Resolved by §6 "Golden
  invariant": stated explicitly. Verified no default fixture sets `point_cloud` and f01
  uses `depth_map` (so the coarse pose+pin-only note does not fire). Because the F1 fix
  now lets matched-shot registration notes reach goldens, the spec **requires** running
  the golden suite post-implementation and regenerating any moved golden, plus a
  `docs/testing.md` invariant note tying golden regeneration to registration-note changes.

### Things the review confirmed correct (preserved, not regressed)
Lazy in-function heavy imports with a no-module-level-import guard test; degrade-on-any-
failure in `refine_registration` (never raises); `bundle_dir` already threaded (no
signature churn); rigid ICP / no RANSAC-FPFH / no depth→cloud / no opencv / **no schema
fields**; `geo.transform_point` / `heading_of_pose_deg_from_matrix` and the
`correction @ arkit_to_model` composition consistent with `coarse_register`.
