# Spec — Deepen the pyRevit non-Revit CPython seams

Work item: **pyrevit**. Target repo: `/home/user/ca_elevation_review`,
branch `claude/codebase-capabilities-0s8u05`.

Status: **hardened / build-ready**. This is the final spec; the adversarial
review's blockers and majors are resolved (see §6, "Adversarial review
resolutions"). Every claim below was re-verified against the real code and the
engine schemas before this revision was written.

## 0. Context and boundary (read first)

The pyRevit front door (`pyrevit-extension/CaElevationReview.extension/lib/ca_elevation_revit/`)
splits cleanly into:

- **Pure / headless seams** (CI-tested on Linux today, 39 tests pass):
  `manifest_builder.py`, `bundle_io.py`, `engine_runner.py`, `config.py`,
  `writeback.py`, `_compat.py` (the `eid_value`/`make_eid` probe helpers).
- **LIVE Revit seams** (NOT reachable here, DO NOT TOUCH):
  `revit_extract.py`, `revit_export.py`, `revit_writeback.py`, and the 3
  `script.py` pushbutton entrypoints. Their Revit imports are function-local;
  the modules import under CPython but the Revit-touching functions are
  Ed-gated on hardware.

This work **only strengthens the pure seams**. Every new test must run on the
default `cd pyrevit-extension/tests && pytest` invocation with no Revit, no
iPhone, no `dotnet`, no `swift`, and no `[heavy]` backend. Tests that need the
engine package are marked `@pytest.mark.engine` and import the engine *inside*
the test function (per `conftest.py` they auto-skip on Python < 3.10 and never
fail collection on the floor jobs).

The whole point of the pyRevit pivot is **reuse of the engine's own
models/schemas**. Where a check already exists in the engine
(`ca_elevation_engine.ingest`, `.models`, `.geometry`, the JSON Schemas), the
new engine-tier tests assert the lib's output *through* the engine rather than
re-deriving the contract.

### Baseline confirmed by exploration (re-verified for this revision)

- `cd pyrevit-extension/tests && pytest -q` → **39 passed**
  (Python 3.11, engine importable, `ca-elevation` on PATH, reportlab present —
  so engine-tier additions WILL run on this host).
- Engine exposes: `ingest.parse_manifest(dict, *, validate=True)`,
  `ingest.load_manifest(path, *, validate=True)`, `ingest.parse_capture`,
  `ingest.load_capture`, `ingest.check_compatible(manifest, capture)`,
  `ingest.load_schema(name)` (returns the schema as a `dict`),
  `ingest.ValidationError`; `models.SpecManifest` / `CapturePackage` / `Verdict`;
  `geometry.pixel_to_model_xy(affine, px, py)`,
  `geometry.model_xy_to_pixel(affine, x, y)` (raises on singular),
  `geometry.affine_scale(affine)`.
- `ingest.check_compatible(manifest, capture)` **returns `list[str]`** of
  non-fatal warnings and **raises `ValidationError` only** on a project-id
  mismatch or a shot targeting a level absent from the manifest. (This shapes
  case 12's assertion — see B1 resolution.)
- Spec-manifest schema (`spec_manifest.schema.json`): root
  `additionalProperties: false`, root `required: [schema_version, project,
  levels, devices]` (NOT `default_tolerances` — the engine has a fallback);
  `$defs` are `tolerances, level, device, point3`. `levels.minItems = 1`.
  `width_px`/`height_px` are `type: integer` with `exclusiveMinimum 0`.
  `pixel_to_model` is exactly 6 numbers. Each tolerance has `exclusiveMinimum 0`.
  `project` has `additionalProperties: false`, props
  `{id, name, revit_file, exported_at, units}`, required `{id, name, units}`,
  `units` enum `{feet, meters}`. `coordinate_system` has
  `additionalProperties: false`, props `{name, north_angle}`. The `device`
  `$def` has `additionalProperties: false`, props
  `{id, family, type, level_id, elevation_id, position, mounting_height,
  orientation, tolerances, metadata}`, required `{id, family, type, level_id,
  position}`.
- Capture-package schema (`capture_package.schema.json`): `shots.minItems = 1`;
  each shot `required: [id, level_id, rgb_image, intrinsics, pose, pin]`. An
  empty `shots: []` is **schema-invalid** (this is why the draft's hand-built
  "minimal capture" failed — see B1).
- The engine synthetic fixtures (`engine/fixtures/synthetic/`) are
  `f01_office.manifest.json` and `f01_office.capture.json`. The capture's
  `project_id` is `demo-office-01`; its single shot's `level_id` is `L1`; the
  manifest's `project.id` is `demo-office-01` and its only level id is `L1`.
  `conftest.py` exposes them via the `engine_fixtures_dir` session fixture.
- `revit_export.export_floorplans` derives the affine `[a,b,c,d,e,f]` from a
  Revit crop box (LIVE) with a y-flip. The exact inline block
  (`revit_export.py:136-143`) is:
  ```python
  su = width_ft / width_px            # width_ft  = cmax_x - cmin_x
  sv = -(height_ft) / height_px       # height_ft = cmax_y - cmin_y
  a = su * bx_x
  b = sv * by_x
  c = o_x + cmin_x * bx_x + cmax_y * by_x
  d = su * bx_y
  e = sv * by_y
  f = o_y + cmin_x * bx_y + cmax_y * by_y
  ```
  The *math* (given crop floats) is pure but currently inlined in the LIVE
  function body and therefore untestable headlessly.

### Gaps this spec closes

1. `manifest_builder.build_manifest` raises on a curated subset of bad inputs
   but does **not** fail-fast on several genuinely schema-invalid shapes
   (non-positive `width_px`, `units` not in enum, extra/unknown device keys,
   non-positive tolerances, wrong `position` shape, non-finite coords). Only one
   engine-tier round-trip test exists and it only checks the happy path.
2. `bundle_io.read_capture_package` is a bare `json.load` — no error surface for
   malformed/partial bundles, and `write_field_bundle` has no test for the
   nested-basename / partial-manifest / idempotent re-export edges.
3. `engine_runner.run_engine` has no test for: corrupt `verdict_report.json` on
   disk, a report present despite non-zero exit, the report-format flag plumbing
   for `html`/`json`, or a `validate()` exit-code surface.
4. The affine produced by `revit_export` is never round-tripped through the
   engine's `geometry` helpers, so a sign/transpose regression in that math
   would not be caught headlessly. The math is not extracted into a pure helper.
5. `writeback.overrides_for_report` is not exercised against a *real* engine
   verdict report (only hand-built dicts), so the `device_id`/`verdict` key
   contract can drift from the verdict_report schema silently.

### Subset invariant (load-bearing — read before writing pre-checks)

The builder's fail-fast pre-checks MUST be a **true subset** of the engine
schema: **anything the builder rejects, `ingest.parse_manifest(..., validate=True)`
must also reject.** A pre-check that is *stricter* than the schema (rejects an
input the authoritative validator accepts) is a defect, not a feature — it makes
the front door refuse engine-valid manifests. Case 13 (§2.2) is a parametrized
guard over the whole pre-check surface that enforces this invariant.

One concrete consequence, confirmed empirically against the real engine:
`ingest.parse_manifest({... width_px: 1000.0 ...}, validate=True)` is **ACCEPTED**
(Python `jsonschema` draft-07 treats the integer-valued float `1000.0` as
satisfying `type: integer`). Therefore the builder MUST NOT reject a float-typed
dimension merely for being a `float` instance — see §1.1.

---

## 1. Files to add / change

### 1.1 CHANGE `…/lib/ca_elevation_revit/manifest_builder.py`

Add **output-shape validation** to `build_manifest` that catches the
schema-invalid cases the engine schema rejects but the current builder lets
through, raising `ManifestBuildError` (the lib's existing error type) so the
front door fails early with a clear message instead of deferring to a late
engine `ValidationError`. Keep it **pure stdlib** — do NOT import the engine
(the engine is the authoritative validator at test time; this is a cheap
fail-fast pre-check that mirrors a documented subset of the schema).

Add a module-level constant, a schema-mirroring device-key constant, and two
private validators:

```python
import math

_VALID_UNITS = ("feet", "meters")

# Mirrors spec_manifest.schema.json -> $defs.device.properties (additionalProperties:false).
# Pinned here to keep manifest_builder engine-import-free. Case 13b (engine-tier)
# asserts this set EQUALS the schema's device property keys so drift is caught.
_DEVICE_KEYS = frozenset(
    {"id", "family", "type", "level_id", "elevation_id",
     "position", "mounting_height", "orientation", "tolerances", "metadata"}
)
_TOLERANCE_KEYS = frozenset({"position", "mounting_height", "orientation"})


def _require_positive_int(value, what):
    # bool is an int subclass: reject it explicitly so True/False cannot pass.
    # Do NOT reject integer-valued floats here -- the schema accepts 1000.0 for
    # "type: integer", so rejecting a float instance would make the builder
    # STRICTER than the schema (forbidden -- see the subset invariant).
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestBuildError(f"{what} must be a positive integer, got {value!r}")


def _require_positive_number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ManifestBuildError(f"{what} must be a positive number, got {value!r}")


def _require_finite(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ManifestBuildError(f"{what} must be a finite number, got {value!r}")
```

Behaviour changes, all raising `ManifestBuildError`. Each one below is a
**confirmed subset** of the engine schema (the engine also rejects the same
input):

- **`project`**: require `id` (non-empty str), `name` (str), `units` in
  `_VALID_UNITS`. Today a bad/missing `units` sails through to the engine.
  (`units` enum is `{feet, meters}` — verified.) Do NOT reject extra project
  keys here even though `project.additionalProperties` is false — the fixture
  carries `revit_file`/`exported_at`, which are *valid* project props; an
  over-broad project-key guard would be stricter than the schema. Leave unknown
  *project* keys to the engine.
- **`_level_dict`**: in addition to the existing 6-element affine check, call
  `_require_positive_int(fp.width_px, ...)` and `_require_positive_int(fp.height_px, ...)`,
  and `_require_finite(v, ...)` on every `pixel_to_model` element (rejects
  `bool`, `str`, `NaN`/`inf`). A degenerate `width_px=0` is schema-invalid
  (`exclusiveMinimum 0`) and currently caught only downstream. Note
  `FloorplanExport.width_px` is typed `int` and `_level_dict` already does
  `int(fp.width_px)`; the guard is belt-and-suspenders against a caller that
  hands in a Python `int` ≤ 0.
- **`default_tolerances`** (and per-device `tolerances` if present in a device
  dict): each provided key must be in `_TOLERANCE_KEYS` (reject unknown keys —
  the tolerances `$def` is `additionalProperties: false`), and each value must
  pass `_require_positive_number` (each tolerance has `exclusiveMinimum 0`).
- **device dicts**: reject keys not in `_DEVICE_KEYS` (the device `$def` is
  `additionalProperties: false` — an unexpected key fails the engine; catch it
  here with the offending key name). Require `position` to be a dict containing
  exactly `x/y/z`, each a finite number (`_require_finite`).

`device_dict` already coerces `position[x/y/z]` to float and validates the id;
extend it only to call `_require_finite` on each coordinate *before* the float
coercion so a `NaN`/`inf` from a bad Revit param cannot reach the wire.

**Signatures unchanged.** All additions are internal validation; the public
`build_manifest` / `device_dict` signatures and return shapes are identical.
This is purely *more* fail-fast, so existing passing tests keep passing.

> Resolved review finding **B2**: the draft proposed rejecting `width_px=1000.0`
> (a float instance) as "schema wants integer". That is wrong — the engine
> ACCEPTS integer-valued floats — so this spec does NOT reject float-instance
> dimensions; `_require_positive_int` guards only `<= 0` and `bool`. See §6.

> Resolved review finding **M1**: the device-key allow-list is pinned as the
> named constant `_DEVICE_KEYS` with a comment referencing the schema, and
> case 13b (engine-tier) asserts `_DEVICE_KEYS` equals the schema's
> `$defs.device.properties` keys (read via `ingest.load_schema("spec_manifest")`),
> so a future schema device-property addition is caught instead of silently
> rejected. See §6.

### 1.2 ADD `…/lib/ca_elevation_revit/affine.py` (new, pure stdlib)

Extract the pixel→model affine **math** out of the LIVE `revit_export` body into
a pure, headlessly-testable helper, then have `revit_export` call it. This is
the one change that touches a LIVE file, but only to *delegate* the pure math —
no new Revit API surface is added.

```python
"""Pure pixel->model affine assembly (extracted from revit_export).

Given the plain float crop-box values revit_export already snapshots while a
Revit transaction is open, build the 6-element [a,b,c,d,e,f] row-major affine
the spec-manifest schema wants. No Revit import -- fully headless-testable.
"""
from __future__ import annotations
import math
from typing import List, Tuple

def build_pixel_to_model(
    *, origin_x, origin_y,
    basis_x: Tuple[float, float], basis_y: Tuple[float, float],  # crop BasisX, BasisY (each (x,y))
    crop_min_x, crop_max_x, crop_min_y, crop_max_y,
    width_px, height_px,
) -> List[float]:
    """Return [a,b,c,d,e,f] mapping pixel (px,py top-left, +py DOWN) -> model XY.

    Mirrors the math currently inlined in revit_export.export_floorplans
    (revit_export.py:136-143), operand-for-operand and in the same order:
        su = (crop_max_x - crop_min_x) / width_px
        sv = -(crop_max_y - crop_min_y) / height_px   # image top = max v (y flip)
        a = su * bx_x ; b = sv * by_x ; c = origin_x + crop_min_x*bx_x + crop_max_y*by_x
        d = su * bx_y ; e = sv * by_y ; f = origin_y + crop_min_x*bx_y + crop_max_y*by_y
    Raises ValueError on non-positive extents/pixels or non-finite inputs.
    """
```

Validation inside (raise `ValueError` on failure): `width_px > 0`,
`height_px > 0`, `crop_max_x > crop_min_x`, `crop_max_y > crop_min_y`, and every
scalar input (`origin_*`, both basis components, all four crop bounds, both
pixel dims) `math.isfinite`. `basis_x`/`basis_y` are `(x, y)` tuples; unpack as
`bx_x, bx_y = basis_x` etc. so the operand order matches the legacy block
exactly.

> Bit-identical requirement: the helper must compute `su`/`sv` from the
> **subtraction form** `(crop_max_x - crop_min_x)` rather than receiving a
> pre-computed `width_ft`, because the legacy block computes `width_ft` that way
> and reuses it. The operations and their order must be the same so the result
> is bit-for-bit identical to today's hardware-validated output. (Confirmed by
> review m2: the §1.2 expressions are bit-identical to the inline block.)

Then in `revit_export.export_floorplans`, **replace** the inlined `su/sv/a..f`
block (`revit_export.py:136-143`) with:

```python
from .affine import build_pixel_to_model
...
pixel_to_model = build_pixel_to_model(
    origin_x=o_x, origin_y=o_y, basis_x=(bx_x, bx_y), basis_y=(by_x, by_y),
    crop_min_x=cmin_x, crop_max_x=cmax_x, crop_min_y=cmin_y, crop_max_y=cmax_y,
    width_px=width_px, height_px=height_px,
)
```

and pass `pixel_to_model=pixel_to_model` into the `FloorplanExport(...)` call
(replacing the per-component `a..f`). The aspect-mismatch WARNING block
(`revit_export.py:150-158`) stays as-is. The top-level `from .affine import
build_pixel_to_model` is safe: `affine.py` has no Revit import, so importing it
at module top of `revit_export` pulls in no Revit; the Revit imports in
`revit_export` remain function-local (confirmed by review).

### 1.3 CHANGE `…/lib/ca_elevation_revit/bundle_io.py` (additive error surface)

The round-trip robustness lives in tests plus one small additive hardening:
`read_capture_package` becomes a typed error surface so a malformed bundle fails
with an actionable message instead of a bare `JSONDecodeError`:

```python
class BundleReadError(ValueError):
    """Raised when a capture package on disk cannot be read/parsed."""


def read_capture_package(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise BundleReadError(f"capture package not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BundleReadError(f"capture package is not valid JSON ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise BundleReadError(
            f"capture package must be a JSON object, got {type(data).__name__}: {path}"
        )
    return data
```

`MANIFEST_FILENAME` and `write_field_bundle` signatures/behaviour unchanged.
`read_capture_package` still does **no schema validation** — that is the
engine's job; bundle_io is JSON-safe, not schema-aware (case 17 documents this
boundary).

### 1.4 CHANGE `…/lib/ca_elevation_revit/engine_runner.py` (corrupt-report guard)

Harden the report read in `run_engine` (`engine_runner.py:209-213`) so a
written-but-corrupt or unreadable `verdict_report.json` does not raise mid
button-press; the run's success/status remains driven by the **exit code**, not
by report parseability:

```python
report = None
json_path = os.path.join(out_dir, "verdict_report.json")
if exists(json_path):
    try:
        with open(json_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except (json.JSONDecodeError, OSError):
        report = None  # written-but-unreadable; status still reflects exit code
```

`EngineRun.status`/`.ok` already derive solely from `returncode`
(`classify_exit`); this change keeps `report` independent of `status`/`ok`,
exactly as case 24 documents. No signature change.

### 1.5 Tests — files to add / extend (all under `pyrevit-extension/tests/`)

- **EXTEND `test_manifest_builder.py`** (FLOOR + ENGINE).
- **EXTEND `test_bundle_io.py`** (FLOOR + one ENGINE round-trip).
- **EXTEND `test_engine_runner.py`** (FLOOR, mocked subprocess).
- **ADD `test_affine.py`** (FLOOR + ENGINE round-trip via `geometry`).
- **EXTEND `test_writeback.py`** (add one ENGINE test driving a real report).

No new conftest needed (the `engine` marker + `engine_fixtures_dir`/`repo_root`
fixtures + `pythonpath` already exist).

---

## 2. Test plan (concrete cases, headless)

### 2.1 `test_manifest_builder.py` — new FLOOR cases (no engine)

Each FLOOR rejection case below is also asserted, in case 13 (§2.2), to be
rejected by the engine — i.e. every one is a confirmed schema subset.

1. `test_project_units_must_be_enum`: `build_manifest({"id":"p","name":"P","units":"inches"}, [_export()], [_device()])` raises `ManifestBuildError` matching `units`.
2. `test_project_missing_id_rejected`: `units` valid but `id` empty → raises matching `id`.
3. `test_nonpositive_width_px_rejected`: an `_export()` with `width_px=0` → raises matching `positive integer`.
4. `test_nonpositive_height_px_rejected`: an `_export()` with `height_px=-5` → raises matching `positive integer`. *(Replaces the draft's removed `test_float_dims_rejected`; this is a genuine schema subset since `exclusiveMinimum 0`.)*
5. `test_nonfinite_affine_rejected`: `pixel_to_model=[float("nan"),0,0,0,0.01,0]` → raises matching `finite` / `number`.
6. `test_negative_tolerance_rejected`: `default_tolerances={"position": -1}` → raises matching `positive`.
7. `test_unknown_tolerance_key_rejected`: `default_tolerances={"slop": 1.0}` → raises matching `slop` / `unknown`.
8. `test_unknown_device_key_rejected`: device dict with extra `"sku": "x"` → raises naming `sku`.
9. `test_device_position_must_have_xyz`: device whose `position` is `{"x":0,"y":0}` (no z) → raises.
10. `test_device_dict_rejects_nonfinite_coord`: `device_dict("uid","f","t","L1",{"x":float("inf"),"y":0,"z":0})` → raises.
11. Regression guard: keep all 7 existing FLOOR tests green (happy build, device-only-rejected, empty id, duplicate id, unknown level, bad affine length, device_dict requires id).

### 2.2 `test_manifest_builder.py` — ENGINE round-trip (3.10+)

Extend the existing `test_built_manifest_round_trips_and_validates` and add:

12. `test_built_manifest_round_trips_and_is_capture_compatible`
    (`@pytest.mark.engine`): build a manifest whose `project.id == "demo-office-01"`
    and that contains a level with id `"L1"` (matching the engine fixture
    capture), a `coordinate_system={"name":"Survey","north_angle":12.5}`, and at
    least one device on `L1`. Assert `ingest.parse_manifest(m, validate=True)`
    returns a `SpecManifest` with `coordinate_system.north_angle == 12.5`. Then
    load the **engine fixture capture** via the `engine_fixtures_dir` fixture
    (`ingest.load_capture(os.path.join(engine_fixtures_dir, "f01_office.capture.json"), validate=True)`)
    and assert `ingest.check_compatible(parsed, capture) == []` — i.e. the lib's
    manifest is compatible with a *real, schema-valid* capture and produces zero
    warnings. (Do NOT hand-build an empty-`shots` capture: `shots.minItems = 1`
    makes `[]` schema-invalid and `parse_capture(..., validate=True)` would raise
    — see B1. And assert on the **returned list**, not on absence of an
    exception, because `check_compatible` returns warnings and only raises on a
    hard project-id/level mismatch.)
13. `test_builder_prefilter_is_a_schema_subset`
    (`@pytest.mark.engine`): the subset-invariant guard. Define a list of
    builder-rejected fixtures — one per FLOOR rejection case 1–10 — each as the
    **raw manifest dict** the builder would produce *if it did not pre-check*
    (i.e. construct the bad manifest dict directly, bypassing `build_manifest`).
    Parametrize over them and assert each ALSO fails
    `ingest.parse_manifest(bad_dict, validate=True)` with `ingest.ValidationError`.
    This proves every builder pre-check is a true subset of the schema (nothing
    the builder rejects is engine-valid). Build the bad dicts off a known-good
    base (e.g. the fixture manifest deep-copied) so only the one offending field
    differs. *(Resolves B3: the guard now covers the whole pre-check surface, not
    just negative tolerance.)*
13b. `test_device_key_allowlist_matches_schema`
    (`@pytest.mark.engine`): assert
    `manifest_builder._DEVICE_KEYS == set(ingest.load_schema("spec_manifest")["$defs"]["device"]["properties"])`.
    Locks the lib's hardcoded device-key allow-list to the schema so a future
    schema device-property addition fails this test instead of silently making
    the builder reject engine-valid manifests. *(Resolves M1.)*

### 2.3 `test_bundle_io.py` — new FLOOR cases

14. `test_read_capture_missing_file_raises_bundle_error`: nonexistent path → `bundle_io.BundleReadError` matching `not found`.
15. `test_read_capture_malformed_json_raises_bundle_error`: write `"{not json"` → `BundleReadError` matching `not valid JSON`.
16. `test_read_capture_non_object_raises`: write `"[1,2,3]"` → `BundleReadError` matching `object`.
17. `test_read_capture_partial_payload_returns_dict`: a capture dict missing `shots` still *reads* (bundle_io does not schema-validate; that is the engine's job) — assert the returned dict **equals the written dict unchanged**. Documents the seam boundary: bundle_io is JSON-safe, not schema-aware.
18. `test_write_field_bundle_nested_basename_creates_subdir`: `_export(basename="floorplans/level_1.png")` (matching `revit_export`'s real `floorplans/level_<id>.png` convention); assert `(tmp_path/"floorplans"/"level_1.png").read_bytes() == image_bytes` and the manifest references the nested path. (`write_field_bundle` already `os.makedirs(os.path.dirname(dest))`; this locks the behaviour the live exporter relies on.)
19. `test_write_field_bundle_absolute_basename_rejected`: `_export(basename="/etc/evil.png")` → `ValueError` matching `relative`.
20. `test_write_field_bundle_partial_manifest_record_mismatch`: two exports but a manifest whose `levels` only references one image → existing `do not match` `ValueError` (assert with 2-vs-1 set). Strengthens the existing single-tamper test toward partial bundles.
21. `test_write_field_bundle_is_sole_writer_idempotent`: write the bundle twice into the same `tmp_path`; assert the second call overwrites cleanly (same bytes, no stale extra files) — documents re-export safety.

### 2.4 `test_bundle_io.py` — ENGINE round-trip (3.10+)

22. `test_written_bundle_loads_through_engine` (`@pytest.mark.engine`): build a
    manifest, `write_field_bundle` to `tmp_path`, then
    `ca_elevation_engine.ingest.load_manifest(os.path.join(tmp_path,"manifest.json"), validate=True)`
    returns a `SpecManifest`. Proves the *on-disk* bytes bundle_io writes (not
    just the in-memory dict) are schema-valid — closes the "engine never stats
    the image, mismatch surfaces late" gap at the manifest level.

### 2.5 `test_engine_runner.py` — new FLOOR cases (mocked subprocess)

All cases inject a `_Recorder` runner (the existing pattern) and an `exists`
callable; no real `ca-elevation` process is launched.

23. `test_run_engine_corrupt_report_does_not_crash`: write `out/verdict_report.json`
    containing `"{bad"`, with a mocked runner returning rc=0 and an `exists` that
    reports the json path present. With the §1.4 guard in place, assert
    `result.report is None`, `result.status == EngineStatus.SUCCESS`, and
    `result.ok is True` (exit code, not report parse, is the success signal).
    **Do NOT assert `result.report_path`** here — `report_path` is an independent
    surface (it depends on whether `report.pdf`/`report.html` exist on disk) and
    must stay decoupled from `report` exactly as case 24 documents. If the test
    writes no pdf/html, `report_path` happens to be `None`, but the case does not
    rely on that. *(Resolves M2.)*
24. `test_run_engine_report_present_despite_validation_exit`: rc=1 but a valid
    `verdict_report.json` on disk → `result.report is not None`,
    `result.status == EngineStatus.VALIDATION_ERROR`, `not result.ok`. Documents
    that report presence and exit status are independent surfaces.
25. `test_run_engine_format_flag_plumbed`: call with `report_format="html"` and
    assert `argv[argv.index("--format")+1] == "html"`; repeat for `"json"`. Plus
    `test_run_engine_json_format_finds_no_pdf_html`: with `report_format="json"`
    and only `verdict_report.json` on disk (no `report.pdf`/`report.html` — the
    injected `exists` returns False for both), `result.report_path is None` (the
    `_find_report` glob fallback returns None).
26. `test_run_engine_no_report_on_disk`: mocked runner rc=2, `exists` returns
    False for everything → `result.report is None`, `result.report_path is None`,
    `result.status == EngineStatus.CRASH`. The crash path leaves no artifacts.
27. `test_validate_returns_completed_process_surface`: `validate("m.json")` with
    a `_Recorder(returncode=1, stderr="bad manifest")` returns the
    `CompletedProcess`; assert `proc.returncode == 1` and that the argv contains
    `"validate"` and does NOT contain `"--capture"` (manifest-only). (Complements
    the existing capture-passed test by asserting the *error surface* the caller
    inspects.)
28. `test_run_engine_argv_order_is_stable`: assert the full argv ordering
    (`run --manifest M --capture C --out O --format F`) for a console-script
    command (`EngineCommand(config.CONSOLE_SCRIPT, [])`), locking the CLI
    contract the engine's `cli.py` parses.

### 2.6 `test_affine.py` — new file

FLOOR (no engine):

29. `test_identity_unrotated_plan`: un-rotated plan, `basis_x=(1,0)`,
    `basis_y=(0,1)`, `crop_min=(0,0)`, `crop_max=(10,8)`, `width_px=1000`,
    `height_px=800` → assert `a == 0.01`, `b == 0.0`, `c == 0.0`, `d == 0.0`,
    `e == -0.01`, `f == 8.0` (the documented closed form, manually re-verified in
    review m2).
30. `test_y_axis_is_flipped`: feeding the affine through the documented forward
    map, top-left pixel `(0,0)` maps to model y = `crop_max_y`; bottom-left pixel
    `(0, height_px)` maps to model y = `crop_min_y` (within 1e-9). Catches a sign
    regression in `sv`.
31. `test_nonpositive_extent_raises`: `crop_max_x == crop_min_x` → `ValueError`.
32. `test_nonpositive_pixels_raises`: `width_px=0` → `ValueError`.
33. `test_nonfinite_input_raises`: `origin_x=float("nan")` → `ValueError`.
34. `test_matches_legacy_inline_math`: a golden — pick a rotated basis
    (e.g. 90°: `basis_x=(0,1)`, `basis_y=(-1,0)`) with a non-zero origin and
    non-trivial crop, and assert the 6 outputs equal the values computed by the
    *exact* legacy expressions (`su/sv/a..f` from `revit_export.py:136-143`)
    copied inline into the test, proving the extraction is bit-identical to the
    old block. Use `==` (not `pytest.approx`) — the operation order is identical
    so the results are bit-for-bit equal.

ENGINE round-trip (3.10+, `@pytest.mark.engine`), reusing `geometry`:

35. `test_affine_round_trips_through_engine_geometry`: build an affine with
    `build_pixel_to_model`, then for several pixels `(px,py)` assert
    `geometry.model_xy_to_pixel(affine, *geometry.pixel_to_model_xy(affine, px, py))`
    returns `(px, py)` within 1e-6. Proves the lib's affine is invertible and
    consistent with the engine's own consumer of `pixel_to_model`.
36. `test_affine_scale_is_units_per_pixel`: for the identity case (case 29),
    `geometry.affine_scale(affine)` ≈ `0.01` (model-units-per-pixel), within
    1e-9. Ties the lib's affine to the engine's scale interpretation.
37. `test_built_affine_validates_in_full_manifest` (`@pytest.mark.engine`):
    feed an affine from `build_pixel_to_model` into a `FloorplanExport` →
    `build_manifest` → `ingest.parse_manifest(..., validate=True)` succeeds and
    `parsed.levels[0].floorplan.pixel_to_model == affine`. End-to-end: the
    extracted math survives manifest assembly and schema validation.

### 2.7 `test_writeback.py` — new ENGINE case (3.10+)

38. `test_overrides_from_real_engine_report` (`@pytest.mark.engine`): produce a
    *real* verdict report and feed it to `overrides_for_report`. **Preferred
    path** (matches `test_integration.py`, lowest coupling): run
    `engine_runner.run_engine` over the engine fixtures
    (`engine_fixtures_dir`/`f01_office.manifest.json` + `f01_office.capture.json`)
    into a `tmp_path` out dir using the real `ca-elevation` (located via
    `locate_engine()`), then assert `result.report is not None` and feed
    `result.report` into `writeback.overrides_for_report(...)`. Assert it yields
    one `DeviceOverride` per `device_results` entry and that
    `writeback.is_known_verdict(o.verdict)` is True for **every** override (the
    real report never emits a verdict outside `VERDICT_COLORS` — the verdict enum
    `{pass, flag, absent, type_mismatch}` equals the `VERDICT_COLORS` keys,
    confirmed in review). This catches drift between the verdict_report schema's
    `device_results[].{device_id, verdict}` keys and `overrides_for_report`'s
    reads.
    **Do NOT assert any `report.pdf` / `report.html` presence** — this case is
    about the JSON report only, and must pass on a no-reportlab job (the engine
    falls back to HTML/JSON). *(Keeps §4's "no PDF assertion in new tests" claim
    literally true — review M3.)*
    If a real-process run proves awkward in the test env, the in-process
    fallback is `ca_elevation_engine.pipeline` — but confirm the entrypoint name
    against `engine/src/ca_elevation_engine/pipeline.py` / `cli.py` first; prefer
    the `run_engine`-over-fixture path to avoid coupling to engine internals.

### Test count (advisory only)

The exact count is not load-bearing (review m5). The new tests take the suite
from 39 to roughly 70; the acceptance criterion is "all new tests pass" (§5),
not a pinned number. FLOOR-tier additions (the majority) run on every job
including the Python-3.8 floor jobs; ENGINE-tier additions run only on 3.10+.

---

## 3. Graceful degradation under this environment

- **No Revit**: every new test imports only `ca_elevation_revit.*` (pure) and,
  for engine-tier tests, `ca_elevation_engine.*` *inside* the function. No test
  imports the Revit-touching functions of `revit_extract`/`revit_export`/
  `revit_writeback`. `affine.py` is pure stdlib (`math`, `typing`) and is
  imported at module top safely; `revit_export` importing it does not pull in
  Revit.
- **No engine on floor jobs (Python < 3.10)**: all engine-dependent tests carry
  `@pytest.mark.engine`; `conftest.pytest_collection_modifyitems` auto-skips
  them and they import the engine lazily, so collection never fails. The new
  FLOOR tests have zero engine dependency.
- **No `[heavy]` backend**: nothing here touches open3d/pye57/opencv. The affine
  round-trip uses `ca_elevation_engine.geometry`, `ingest`, and `models`.
  **Correction (review m1):** `geometry.py` imports `numpy` at module top and
  uses 3.10+ syntax; the round-trip tests are therefore **engine-tier, 3.10+
  only**, where numpy is a core engine dependency. They do NOT run on floor jobs,
  and this spec does not claim otherwise. No `@pytest.mark.heavy` test is added.
- **Core deps stay light**: no new runtime dependency is added to the lib
  (still pure stdlib: `json`, `os`, `subprocess`, `math`, `typing`, `logging`).
  Tests add no dependency beyond pytest + the already-required engine on the
  3.10+ jobs.
- **Subprocess never actually spawned in unit tests**: all `engine_runner` FLOOR
  tests inject a `_Recorder` runner and an `exists` callable. The real-process
  path stays in `test_integration.py` and the new case 38 (both engine-tier).
- **Windows-only code paths**: the locator's Windows branch is already tested by
  injecting `platform="win32"`; no new OS-specific test is added that needs a
  real Windows host.
- **Python 3.8 syntax floor**: new lib code uses `from __future__ import
  annotations` and `typing.List/Dict/Tuple/Optional` (NOT `list[...]` /
  `X | None`) per `tests/pyproject.toml` (`target-version = "py38"`, with
  `UP006/UP007/UP035/UP045` ignored). `affine.py` follows that style.

---

## 4. Non-goals (explicit)

- **No live Revit work.** Do not modify the Revit-touching bodies of
  `revit_extract.py` / `revit_writeback.py`, the live stubs, or the `script.py`
  pushbuttons. The only edit to a LIVE file is extracting the *pure* affine math
  out of `revit_export.export_floorplans` into `affine.py` and calling it —
  producing bit-identical numbers; no new Revit API surface.
- **No live-doc write-back.** `revit_writeback`'s `OverrideGraphicSettings` /
  transaction / marker logic is out of scope; only the pure
  `writeback.overrides_for_report` mapping is tested.
- **No schema changes.** The engine's JSON Schemas under
  `engine/src/ca_elevation_engine/schemas/` are the contract; the lib's
  fail-fast pre-checks are a *subset* of (never stricter than) the schema, and
  cases 13 / 13b guard that invariant in both directions. Do not edit any
  `.schema.json`.
- **No re-implementation of engine validation in the lib.** The lib's
  `build_manifest` pre-check is a cheap UX fail-fast; the authoritative
  validation remains `ingest.parse_manifest(..., validate=True)`, asserted in
  engine-tier tests. Do not vendor `jsonschema` into the lib.
- **No iPhone / capture-package authoring.** `read_capture_package` only
  *reads*; the lib does not produce or schema-validate capture packages.
- **No new CLI surface / no engine CLI changes.** `engine_runner` continues to
  call the documented `run` / `validate` subcommands with the existing flags.
- **No `report.pdf` rendering asserted in new tests.** PDF presence is only
  checked in the pre-existing engine-tier `test_integration.py`. Case 38 reads
  the JSON report only and must pass on a no-reportlab job.

---

## 5. Acceptance criteria

1. `cd pyrevit-extension/tests && pytest -q` passes (all engine-tier tests run,
   engine installed) on a 3.10+ host. All new tests pass; the existing 39 stay
   green.
2. On a simulated floor job (`pytest` under Python 3.8, or with the engine
   uninstalled) collection succeeds and all `engine`-marked tests skip; the new
   FLOOR tests pass.
3. `ruff check --config tests/pyproject.toml CaElevationReview.extension/lib tests`
   and `ruff format --check` are clean (py38 target, the ignored UP rules
   respected).
4. `mypy --config-file tests/pyproject.toml CaElevationReview.extension/lib`
   passes (new `affine.py` + `manifest_builder` / `bundle_io` / `engine_runner`
   additions are typed).
5. The affine extracted into `affine.py` produces values bit-identical to the
   prior inline math (case 34 golden, `==` not approx), so the
   hardware-validated `revit_export` behaviour is provably unchanged.
6. The builder pre-check is a confirmed schema subset: case 13 (parametrized over
   every rejection fixture) shows every builder-rejected input is also engine-
   rejected, and case 13b shows the device-key allow-list equals the schema's
   device property set.
7. No new runtime dependency in the lib; nothing behind `[heavy]`; no
   `.schema.json` modified.

---

## 6. Adversarial review resolutions

Each blocker and major from `spec-pyrevit.review.md` is resolved below. Minors
folded into the body are noted too.

- **B1 (capture fixture schema-invalid — case 12 would error).** Resolved.
  Case 12 no longer hand-builds an empty-`shots` capture (`shots.minItems = 1`
  makes `[]` invalid). It loads the real engine fixture capture
  `f01_office.capture.json` via the `engine_fixtures_dir` fixture and asserts
  `check_compatible(parsed, capture) == []` (assert on the **returned warning
  list**, not on absence of an exception, since `check_compatible` returns
  `list[str]` and only raises on a hard project-id/level mismatch). The built
  manifest uses `project.id == "demo-office-01"` and contains level `L1` to match
  the fixture capture. See §2.2 case 12 and §0 baseline.

- **B2 (case 4 made the builder stricter than the schema).** Resolved by
  removing the draft's `test_float_dims_rejected` and forbidding float-instance
  rejection. Verified empirically: `parse_manifest({... width_px: 1000.0 ...},
  validate=True)` is ACCEPTED by the engine, so rejecting a float instance would
  violate the subset invariant. `_require_positive_int` now guards only `<= 0`
  and `bool` (bool is an int subclass and must be rejected). The replacement
  case 4 (`test_nonpositive_height_px_rejected`) is a genuine subset
  (`exclusiveMinimum 0`). See §0 (subset invariant), §1.1, §2.1 case 4.

- **B3 (case 13's guard self-contradicting unless B2 fixed).** Resolved. With
  B2 fixed, every pre-check is a subset. Case 13 is rewritten as a parametrized
  test over the **whole** pre-check surface (one fixture per rejection case
  1–10), asserting each builder-rejected input also fails
  `parse_manifest(..., validate=True)`. This prevents any future pre-check from
  drifting stricter than the schema. See §2.2 case 13.

- **M1 (unknown-device-key pre-check can reject schema-valid manifests if the
  schema grows).** Resolved. The allow-list is pinned as the named constant
  `manifest_builder._DEVICE_KEYS` with a comment referencing
  `spec_manifest.schema.json -> $defs.device.properties`, and case 13b
  (engine-tier) asserts `_DEVICE_KEYS` equals
  `ingest.load_schema("spec_manifest")["$defs"]["device"]["properties"]` keys, so
  a schema device-property addition fails the test instead of silently rejecting
  engine-valid manifests. (`load_schema` returns a `dict`, confirmed.) See §1.1,
  §2.2 case 13b.

- **M2 (case 23 under-specified `report_path` for a corrupt report).** Resolved.
  Case 23 asserts `result.report is None`, `status == SUCCESS`, `ok is True`, and
  **explicitly does not assert `report_path`** (it is an independent surface,
  decoupled from `report`, exactly as case 24 documents). See §2.5 case 23.

- **M3 (no-reportlab note / PDF assertion).** Resolved. Case 38 reads only the
  JSON report and asserts no PDF/HTML presence, so it passes on a no-reportlab
  job (engine falls back to HTML/JSON). Case 25 is FLOOR, mocks the subprocess,
  and never asserts PDF. §4's "no PDF rendering asserted in new tests" stays
  literally true. See §2.5 case 25, §2.7 case 38, §4.

- **m1 (the "numpy-free stdlib math" claim was wrong).** Corrected. `geometry.py`
  imports numpy at module top and is 3.10+ syntax; the affine round-trip tests
  (35–37) are engine-tier, 3.10+ only, where numpy is a core engine dependency.
  §3 no longer claims they are numpy-free or floor-runnable.

- **m2 (closed-form/golden values verified correct).** Acknowledged — case 29's
  closed form and the §1.2 bit-identical extraction are confirmed; case 34 uses
  `==` against the copied legacy expressions.

- **m3 (py38 typing style ok).** Acknowledged — `from typing import List/Tuple`
  + `List[float]` is correct under the py38 ruff config; `affine.py` follows it.

- **m4 (case 17 wording).** Adjusted — case 17 asserts the returned dict
  **equals the written dict unchanged** (not "is valid").

- **m5 (test-count advisory).** Adjusted — the acceptance criterion is "all new
  tests pass" (§5.1), not a pinned count; §2 marks the count as advisory.

### One point of partial disagreement with the reviewer (justified)

The review (M1) offered, as an alternative, to *downgrade the unknown-device-key
pre-check to a non-goal and let the engine own it*. This spec keeps the
pre-check rather than dropping it, because the device-key typo case is a likely
real-world front-door failure (a hand-edited or mis-ported extractor adding a
stray key) and catching it at build time with the offending key name is exactly
the cheap UX win this work item is about. The durability concern the reviewer
raised is fully addressed by case 13b (the allow-list is tested equal to the
schema), so the "silent stricter drift" risk is eliminated without sacrificing
the fail-fast. The pre-check stays.
