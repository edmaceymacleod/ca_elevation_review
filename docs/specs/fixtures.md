# Implementation Spec — Expand the fixture / golden-report corpus

Work item: **fixtures**. Status: hardened, build-ready. Target repo: `/home/user/ca_elevation_review`.
All work is headless CPython on Linux. No Revit, no iOS, no `[heavy]` deps touched.

This is a committed deliverable. The adversarial review of the draft returned **no blockers and no
majors** ("sound (ship with minor fixes)"); every minor finding is resolved below and itemized in
§10 "Adversarial review resolutions".

---

## 0. Context discovered (read this before implementing)

The engine today ships exactly one synthetic scenario, `f01_synthetic_office`, registered in
three coupled places that the ratchet test (`engine/tests/test_registry.py`) and the golden
test (`engine/tests/test_integration_golden.py`) enforce:

- Seeder: `engine/fixtures/seeders/f01_synthetic_office.py` — builds `build_manifest()` +
  `build_capture()` and `write(out_dir)`s `f01_office.{manifest,capture}.json` into
  `engine/fixtures/synthetic/`.
- Payloads: `engine/fixtures/synthetic/f01_office.manifest.json`, `.capture.json`.
- Golden: `engine/fixtures/golden/f01_verdict_report.json`.
- Registry binding: `registry.SCENARIO_GOLDENS = {"f01_synthetic_office": "f01_verdict_report.json"}`.

**There is no automated golden writer today.** The f01 golden was produced by running the
pipeline once and committing the output. This spec adds a small, explicit, opt-in regeneration
entry point (see §3.4) so goldens stay regenerable and the "tests never write fixtures" rule is
preserved (tests READ goldens; only an explicitly invoked `__main__` writes them).

### Engine behavior facts that constrain fixture design (verified by reading source)

1. **Verdict ladder** (`verdict.py`, first match wins): ABSENT → TYPE_MISMATCH → FLAG → PASS.
   - ABSENT when `match.observation is None`. Confidence `0.7` if `match.in_coverage` (expected in
     a captured frustum but nothing observed there) else `0.25` (coverage gap). These two values are
     **literal constants in `verdict.py`**, not geometry-derived (load-bearing for §5.3).
   - TYPE_MISMATCH only when `obs.detected_type` set, `obs.type_confidence >= 0.6`
     (`TYPE_MISMATCH_MIN_CONFIDENCE`), and `_types_disagree(expected, detected)` is true.
     `_types_disagree` is case-insensitive and treats substring containment as agreement.
   - FLAG when matched and ANY of position/mounting_height/orientation delta strictly exceeds its
     tolerance (`delta > tol`). Note: **strictly greater** — a delta exactly equal to tol is PASS.
   - PASS otherwise.
2. **Match gate** (`compare.py`): an observation associates with a device only if 3-D distance
   `<= max(pos_tol * 3.0, 0.5)` (`GATE_TOLERANCE_MULT=3.0`, `GATE_ABS_FLOOR=0.5`). An out-of-gate
   observation does NOT match → device goes ABSENT, not FLAG. So a "just-outside-tolerance but
   still-flaggable" device needs `tol < delta <= gate`. With default `pos_tol=0.083`,
   gate `= 0.5`, so a FLAG-on-position needs `0.083 < delta <= 0.5`.
3. **Coverage / frustum** (`compare.py::_coverage_for_device`): a device is "in coverage" for a
   shot only if it projects in front of the camera (`depth>0`) and within frame ±10%
   (`FRUSTUM_MARGIN_FRAC=0.10`). `_candidate_observations` restricts candidate observations to
   covering shots when any shot covers the device; otherwise (no frustum coverage) it falls back to
   all same-level shots. So: a device **behind the camera** / off-frame with NO same-level
   observation nearby → coverage-gap ABSENT (confidence 0.25). A device in-frame with no nearby
   observation → in-coverage ABSENT (confidence 0.7).
4. **`up_axis` is NOT compared.** The `Observation` model and capture schema have no `up_axis`
   field; `verdict.py` only compares `facing_angle` against the manifest device's `facing_angle`.
   The manifest device `orientation.up_axis` (enum `up|down|left|right`) round-trips through the
   model but never affects a verdict. **Honest consequence:** the work item's "orientation up/down"
   cannot change a verdict; it can only be exercised as a manifest-level round-trip / report
   passthrough. The *reachable* orientation verdict path is FLAG via `facing_angle` delta exceeding
   the orientation tolerance (default 10.0°) — a path f01 does NOT exercise (its orientation deltas
   are ≤2°). This spec exercises the reachable path and documents the un-reachable one as a non-goal.
5. **Mounting-height datum** (`compare.py::_expected_height`): if `device.mounting_height` is set it
   is used directly; else `position.z - level.elevation`. So multi-level manifests with nonzero
   `level.elevation` exercise the datum subtraction, and a device with explicit `mounting_height`
   vs one relying on `z - elevation` are distinct datum paths. Height delta =
   `abs(obs.mounting_height - expected_height)`; FLAG when `> mounting_height tol` (default 0.042).
6. **Schema constraints** (verified):
   - `spec_manifest`: `devices` array has **no** `minItems` → a **zero-device manifest is
     schema-valid**. `levels` `minItems:1`.
   - `capture_package`: `shots` `minItems:1` → a capture must have ≥1 shot even for a
     zero-device manifest. An empty-device scenario therefore = 0 devices, 1 (otherwise-ignored) shot.
   - `verdict_report`: `device_results` array (may be empty), `summary` required, `confidence`
     in `[0,1]`, `verdict` enum `pass|flag|absent|type_mismatch`.
7. **Report determinism**: `run_pipeline(..., generated_at=GENERATED_AT)` injects the timestamp;
   `engine_version` is stamped from `ca_elevation_engine.__version__` (currently `"0.1.0"`) and is
   popped before golden comparison in the existing test. `DeviceResult.confidence` is
   `round(..., 4)`. Floating deltas are NOT rounded in the report (e.g. f01 has
   `0.02236067977499742`) — goldens must store the engine's exact float output, which is why
   goldens are machine-generated, never hand-typed.
8. **The report `summary` counts** are derived in `VerdictReport.summary`; the
   `test_golden_summary` test currently hard-codes f01's summary. New scenarios get their own
   summary assertions (see §5) computed from their golden, not hand-guessed.
9. **Golden serialization format (verified byte-for-byte by the reviewer):** the committed
   `f01_verdict_report.json` is exactly `json.dumps(data, indent=2, sort_keys=True) + "\n"`, the same
   format `render_json` uses. The regen writer in §3.4 emits identically, so all goldens share one
   format and f01 is not perturbed.

---

## 1. Goals / non-goals

### Goals
Add deterministic synthetic scenarios + committed goldens that exercise verdict paths f01 cannot:

- **F02 multi-level + datum boundaries**: ≥2 levels with distinct nonzero elevations; devices whose
  expected mounting height comes from `z - level.elevation` vs explicit `mounting_height`; a
  mounting-height FLAG (height delta just over `mounting_height` tol) and a clean just-inside PASS.
- **F03 tolerance boundaries**: position/height/orientation deltas placed just-inside vs
  just-outside their tolerances (PASS vs FLAG), plus a per-device tolerance override (both ways).
- **F04 coverage & orientation**: an in-coverage ABSENT (conf 0.7) vs coverage-gap ABSENT
  (conf 0.25) in the SAME scenario; an orientation FLAG via `facing_angle` delta > orientation tol;
  a device whose manifest `up_axis="down"` round-trips (PASS, documenting the no-op).
- **F05 distinction scenario**: TYPE_MISMATCH vs ABSENT vs FLAG side-by-side, including a
  low-confidence (`type_confidence < 0.6`) detected_type that must NOT trigger TYPE_MISMATCH
  (stays PASS / human-confirmable), proving the confidence gate.
- **F06 dense device wall**: 12 coplanar devices in one shot's frustum at safe spacing,
  proving the matcher associates the correct observation per device under crowding (incl. a
  wrong-type decoy near a correct device, exercising the type-aware tie-break in
  `compare.match_device`).
- **F07 empty / zero-device manifest**: 0 devices, 1 shot; report has empty `device_results` and an
  all-zero summary; proves the pipeline + report schema tolerate the degenerate case.

Each scenario is registered in `registry.SCENARIO_GOLDENS`, has a seeder, committed payloads, and a
committed golden, and is parametrized into the golden integration test.

### Non-goals (explicit)
- **No engine behavior changes.** This work item only adds fixtures/goldens/tests. If a desired
  edge case is unreachable with current engine logic, it is documented, not forced by editing
  `verdict.py`/`compare.py`. Any engine change is a separate work item.
- **`up_axis` up/down does not change a verdict** (engine compares only `facing_angle`). We exercise
  the round-trip and the reachable `facing_angle` orientation FLAG; we do NOT add an `up_axis`
  comparison.
- **No new verdict classes.** The registry still enumerates exactly `{pass,flag,absent,type_mismatch}`;
  `test_registry_verdicts_match_enum` must stay green.
- **No heavy deps.** No point clouds, E57, open3d/pye57/opencv. All shots are pose+pin+synthetic
  `observations` (the deterministic headless path), exactly like f01. No `@pytest.mark.heavy` tests
  are added; none of the new tests need a heavy backend.
- **No real capture / images.** `rgb_image`/`depth_map` filenames are nominal strings; no binary
  assets are added (consistent with f01, which references `S1.jpg` without shipping it).
- **No change to f01.** f01 stays byte-for-byte; its golden and tests are untouched.
- **Not changing the schemas.** All new payloads validate against the existing draft-07 schemas.

---

## 2. Files to add / change

### Add — seeders (one per scenario)
- `engine/fixtures/seeders/f02_multilevel_datum.py`
- `engine/fixtures/seeders/f03_tolerance_boundary.py`
- `engine/fixtures/seeders/f04_coverage_orientation.py`
- `engine/fixtures/seeders/f05_distinctions.py`
- `engine/fixtures/seeders/f06_device_wall.py`
- `engine/fixtures/seeders/f07_empty_manifest.py`

### Add — package markers (make `fixtures.seeders` importable; see §3.3)
- `engine/fixtures/__init__.py` (empty)
- `engine/fixtures/seeders/__init__.py` (empty)

These are additive: `fixtures/` is not under `[tool.setuptools.packages.find] where=["src"]`, so
adding `__init__.py` files does not affect packaging (verified by the reviewer). The existing f01
seeder continues to run as a plain script.

### Add — generated payloads (committed; produced by the seeders, never hand-edited)
For each `fNN_<slug>`:
- `engine/fixtures/synthetic/fNN_<slug>.manifest.json`
- `engine/fixtures/synthetic/fNN_<slug>.capture.json`
- `engine/fixtures/golden/fNN_<slug>_verdict_report.json`

Filenames MUST end in `.manifest.json` / `.capture.json` / `_verdict_report.json` so
`validate_schemas.py` routes them to the right schema (it discovers files by suffix via `rglob`).

### Add — shared seeder helpers (DRY)
- `engine/fixtures/seeders/_common.py` — see §3.1. Also the single home of the `GENERATED_AT`
  determinism constant (§3.1, resolves review finding on constant duplication).

### Add — golden regeneration entry point
- `engine/fixtures/seeders/regen_goldens.py` — see §3.4. A single `python -m` runnable that
  regenerates ALL new synthetic payloads + goldens by running the real pipeline. This is the
  documented way to update goldens after an intentional engine change.

### Change — registry
- `engine/src/ca_elevation_engine/registry.py`: extend `SCENARIO_GOLDENS` with the 6 new entries and
  add `SCENARIO_PAYLOAD_STEMS` (see §5.5).

### Change — tests
- `engine/tests/conftest.py`: **no new fixtures required** — the parametrized tests read
  `registry.SCENARIO_GOLDENS`/`SCENARIO_PAYLOAD_STEMS` directly and use the existing `fixtures_dir`
  fixture. (Resolves the review's "dead conftest fixtures" finding: the draft's `all_scenarios` /
  `_slug_for` are dropped.) Keep all existing `f01_*` fixtures untouched.
- `engine/tests/test_integration_golden.py`: add parametrized golden + schema-validation tests over
  every registered scenario, plus the §5.3 intent-pinning tests and the §5.6 constant-agreement test.
  Keep existing f01 tests as-is.
- `engine/tests/test_registry.py`: update `test_golden_demonstrates_every_verdict_class` to scan
  ALL scenario goldens (so the verdict-coverage ratchet considers the whole corpus); add
  `test_scenario_payload_stems_complete`; leave `test_check_ratchet_count` unchanged (no checks added).

### Change — docs (lightweight, keep honest)
- `docs/testing.md`: under §1, append the scenario table (id → verdict paths it pins → golden).
- `CONTRIBUTING.md`: note `python -m fixtures.seeders.regen_goldens` (run from `engine/`) as the
  golden-regeneration command, reaffirming "a changed golden must be an intentional, reviewed diff".

---

## 3. Seeder design

### 3.1 `_common.py` (shared, pure, no heavy deps)
Extract the constants currently duplicated in f01 and helpers the new seeders share. Also defines the
single `GENERATED_AT` constant that regen and the tests import (no duplicated literals).

```python
from __future__ import annotations
import json
from pathlib import Path

# The fixed report timestamp the regen writer injects AND the golden tests inject.
# Defined ONCE here; regen_goldens.py and test_integration_golden.py import it.
GENERATED_AT = "2026-06-28T00:00:00Z"

# Identity ARKit pose (camera at world origin, looking down -Z, +Y up).
IDENTITY_POSE = [1.0,0.0,0.0,0.0, 0.0,1.0,0.0,0.0, 0.0,0.0,1.0,0.0, 0.0,0.0,0.0,1.0]
INTRINSICS = {"fx":1000.0,"fy":1000.0,"cx":640.0,"cy":360.0,"width":1280,"height":720}
# Floorplan affine: 1 px = 0.01 ft, origin top-left. [a,b,c,d,e,f].
PIXEL_TO_MODEL = [0.01,0.0,0.0, 0.0,0.01,0.0]

SYNTHETIC_DIR = Path(__file__).resolve().parents[1] / "synthetic"
GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"

def level(level_id, name, elevation, image):
    return {"id":level_id,"name":name,"elevation":elevation,
            "floorplan":{"image":image,"width_px":1000,"height_px":800,
                         "pixel_to_model":PIXEL_TO_MODEL}}

def device(did, family, dtype, x, y, z, *, level_id="L1", facing=0.0,
           mounting_height=None, up_axis="up", tolerances=None, elevation_id="E-NORTH"):
    d = {"id":did,"family":family,"type":dtype,"level_id":level_id,
         "elevation_id":elevation_id,"position":{"x":x,"y":y,"z":z},
         "orientation":{"facing_angle":facing,"up_axis":up_axis}}
    if mounting_height is not None:
        d["mounting_height"] = mounting_height
    if tolerances is not None:
        d["tolerances"] = tolerances
    return d

def shot(shot_id, level_id, observations, *, pin=(0.0,0.0,0.0,"high"),
         pose=None, depth=True, elevation_id="E-NORTH"):
    px,py,heading,conf = pin
    s = {"id":shot_id,"level_id":level_id,"elevation_id":elevation_id,
         "rgb_image":f"{shot_id}.jpg","intrinsics":INTRINSICS,
         "pose":pose or IDENTITY_POSE,
         "pin":{"x":px,"y":py,"heading":heading,"confidence":conf},
         "observations":observations}
    if depth:
        s["depth_map"] = f"{shot_id}_depth.bin"
        s["depth_size"] = [192,256]
    return s

def observation(x, y, z, *, mounting_height=None, facing=None,
                detected_type=None, type_confidence=None):
    o = {"position":{"x":x,"y":y,"z":z}}
    if mounting_height is not None: o["mounting_height"]=mounting_height
    if facing is not None:          o["facing_angle"]=facing
    if detected_type is not None:   o["detected_type"]=detected_type
    if type_confidence is not None: o["type_confidence"]=type_confidence
    return o

def write_payloads(slug, manifest, capture):
    """Write the manifest+capture for a scenario; return their paths."""
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    mpath = SYNTHETIC_DIR / f"{slug}.manifest.json"
    cpath = SYNTHETIC_DIR / f"{slug}.capture.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    cpath.write_text(json.dumps(capture, indent=2), encoding="utf-8")
    return mpath, cpath
```

Notes:
- `device(...)` always emits an `orientation` block. That's fine: `Device.to_dict` only drops
  orientation when `facing_angle is None and up_axis=="up"`; our seeders set facing explicitly.
- depth-bearing shots (`depth=True`) keep matches non-`approximate` (matching f01, where
  `approximate=false`). Keep all shots `depth=True`; none of the scenarios below require the
  approximate path.

> Refactor caution: do NOT modify `f01_synthetic_office.py` to use `_common.py` in this change —
> changing f01's serialization could perturb its committed payloads. Leave f01 alone; `_common.py`
> is for new seeders only. (A later cleanup may unify f01, separately.)

### 3.2 Per-scenario seeder shape
Each `fNN_*.py` mirrors f01's structure and imports `_common` via the package-relative import (the
single supported run path is `python -m`, see §3.3):

```python
from __future__ import annotations
from . import _common as c

SLUG = "fNN_<slug>"

def build_manifest() -> dict: ...
def build_capture() -> dict: ...

def write():
    return c.write_payloads(SLUG, build_manifest(), build_capture())

def main() -> None:
    mpath, cpath = write()
    print(f"manifest: {mpath}")
    print(f"capture: {cpath}")

if __name__ == "__main__":
    main()
```

`build_manifest`/`build_capture` are pure dict builders (deterministic, no randomness, no clock).

### 3.3 Import path — ONE supported strategy (package route)
The single supported invocation is the **package / module form** run from `engine/`:
`python -m fixtures.seeders.regen_goldens`. `-m` puts the CWD (`engine/`) on `sys.path`, so
`fixtures.seeders.*` resolves once the two empty `__init__.py` files (§2) exist; `ca_elevation_engine`
resolves via the editable install. The tests and `regen_goldens` use only this form.

We deliberately **do not** add the draft's per-seeder `__package__`-guard shim for direct
`python fNN_*.py` runs, nor the `spec_from_file_location` alternative (resolves the review's
"two import strategies / dead shim" finding). Reasons: (a) nothing in CI or regen exercises a direct
script run, so the shim could rot unnoticed; (b) it adds identical copy-pasted boilerplate to every
seeder, the exact copy-paste-drift surface this corpus is meant to reduce. If a human wants to run a
single seeder, the documented way is `python -m fixtures.seeders.fNN_<slug>` from `engine/`, which
works with the plain relative import and no shim.

### 3.4 `regen_goldens.py` (the golden writer — explicit, never run by tests)
Run from `engine/` as `python -m fixtures.seeders.regen_goldens`. Behavior:

```python
from __future__ import annotations
import importlib, json
from pathlib import Path
from ca_elevation_engine.pipeline import run_pipeline
from . import _common as c   # for GENERATED_AT and GOLDEN_DIR

SEEDERS = [   # (module, slug, golden_filename) -- mirror registry.SCENARIO_GOLDENS (new scenarios only)
    ("fixtures.seeders.f02_multilevel_datum",   "f02_multilevel_datum",   "f02_multilevel_datum_verdict_report.json"),
    ("fixtures.seeders.f03_tolerance_boundary", "f03_tolerance_boundary", "f03_tolerance_boundary_verdict_report.json"),
    ("fixtures.seeders.f04_coverage_orientation","f04_coverage_orientation","f04_coverage_orientation_verdict_report.json"),
    ("fixtures.seeders.f05_distinctions",       "f05_distinctions",       "f05_distinctions_verdict_report.json"),
    ("fixtures.seeders.f06_device_wall",        "f06_device_wall",        "f06_device_wall_verdict_report.json"),
    ("fixtures.seeders.f07_empty_manifest",     "f07_empty_manifest",     "f07_empty_manifest_verdict_report.json"),
]

def regen_one(module, slug, golden_name):
    mod = importlib.import_module(module)
    mpath, cpath = mod.write()                                       # writes payloads
    result = run_pipeline(mpath, cpath, generated_at=c.GENERATED_AT) # validates output schema too
    data = result.report.to_dict()
    c.GOLDEN_DIR.joinpath(golden_name).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return slug

def main():
    for m,s,g in SEEDERS:
        print("regenerated", regen_one(m,s,g))

if __name__ == "__main__":
    main()
```

Critical determinism rules (match the existing f01 golden format so the diff tooling is consistent):
- **`json.dumps(..., indent=2, sort_keys=True)` + trailing newline.** The committed
  `f01_verdict_report.json` is byte-identical to this (verified, §0.9); emit identically so all
  goldens share one format.
- `generated_at` is the single `c.GENERATED_AT` constant; `engine_version` is whatever the package
  reports (popped before comparison in tests, so it does not pin the corpus to a version).
- `run_pipeline` already calls `ingest.validate_report(...)` → regen fails closed if any new payload
  produces a schema-invalid report.
- **Regen lists f02–f07 only.** f01 is never written by regen, so it cannot be perturbed.

`regen_goldens.py` is invoked by humans/CI-regen only. **No test imports or calls it.** Tests read
the committed goldens. This preserves "tests never write fixtures."

---

## 4. Exact scenario definitions (deterministic inputs → expected verdict)

All positions in feet; default tolerances `position=0.083`, `mounting_height=0.042`, `orientation=10.0`
unless a device overrides. Match gate `= max(0.083*3, 0.5) = 0.5`. Camera at model origin (identity
pose + pin at (0,0) heading 0). Place in-frame devices at modest +X like f01's (x≈7–8) with a
co-located observation; place coverage-gap devices behind (x≤−6) like f01's `D-GAP` with NO same-level
observation nearby. The reviewer independently built and ran every scenario below through
`run_pipeline`; the stated verdicts/confidences/summaries reproduced exactly.

> Implementation guidance: do not hand-compute the projection. Use f01's proven placements as
> templates. The "expected verdict" column is the design intent the golden must satisfy; §5.3 adds
> assertions that pin the intent so an accidental geometry change is caught. After writing the
> seeders, run `regen_goldens` and read the produced golden — that is the source of truth for floats.

All FLAG cases keep their breached delta `<= 0.5` (the gate) so they FLAG rather than fall ABSENT
(see §9 R6).

### F02 — `f02_multilevel_datum` (multi-level + mounting-height datum)
Manifest: 2 levels.
- `L1` elevation `0.0`, floorplan `plan_L1.png`.
- `L2` elevation `12.0`, floorplan `plan_L2.png`.
Capture: 2 shots, `S1` on L1 (pin (0,0,0)), `S2` on L2 (pin (0,0,0)). Both depth-bearing.
Devices:
- `D-L1-PASS` L1, pos (8,0,4), `facing=0`, no explicit `mounting_height` (expected height =
  `4 - 0 = 4`). Obs on S1 at (8,0,4), `mounting_height=4.0`. → **PASS**.
- `D-L2-DATUM-PASS` L2, pos (8,0,16), no explicit mounting_height (expected = `16 - 12 = 4`).
  Obs on S2 at (8,0,16), `mounting_height=4.0`. → **PASS** (proves level-elevation subtraction;
  same observed height as L1 device but different z).
- `D-L2-HEIGHT-FLAG` L2, pos (8,2,16), explicit `mounting_height=4.0`. Obs on S2 at (8,2,16),
  `mounting_height=4.10` (height delta `0.10 > 0.042` tol; position delta 0 within tol). → **FLAG**
  with a "mounting height" breach note.
- `D-L2-HEIGHT-PASS` L2, pos (8,-2,16), explicit `mounting_height=4.0`. Obs at (8,-2,16),
  `mounting_height=4.03125` (delta `0.03125`, binary-exact, strictly `< 0.042` → **PASS**). This is a
  clean just-inside PASS using a power-of-two fraction; the exact `>`-vs-`>=` boundary is owned by
  F03, not here. (Renamed from the draft's `D-L2-HEIGHT-EDGE-PASS` and the exactly-equal paragraph
  removed — resolves the review's "EDGE name is misleading" finding.)
Expected summary: pass=3, flag=1, absent=0, type_mismatch=0, total=4.

### F03 — `f03_tolerance_boundary` (just-inside vs just-outside, + per-device override)
Single level L1, one depth shot S1. Use binary-exact deltas (powers-of-two) to avoid FP brittleness:
- `D-POS-INSIDE` pos (8,0,4), obs at (8.0625,0,4) → position delta `0.0625 < 0.083` → **PASS**.
- `D-POS-OUTSIDE` pos (8,1,4), obs at (8.25,1,4) → position delta `0.25` (`>0.083`, `<=0.5` gate)
  → **FLAG** (position breach).
- `D-HEIGHT-INSIDE` pos (8,2,4), mounting_height 4.0, obs height `4.03125` → delta `0.03125<0.042`
  → **PASS**.
- `D-HEIGHT-OUTSIDE` pos (8,3,4), mounting_height 4.0, obs height `4.125` → delta `0.125>0.042`
  → **FLAG** (height breach).
- `D-ORIENT-INSIDE` pos (8,-1,4), facing 0.0, obs facing `8.0` → orient delta `8.0<10.0` → **PASS**.
- `D-ORIENT-OUTSIDE` pos (8,-2,4), facing 0.0, obs facing `25.0` → orient delta `25.0>10.0`
  → **FLAG** (orientation breach). *(This is the orientation-FLAG path f01 lacks.)*
- `D-OVERRIDE-TIGHT` pos (8,-3,4), `tolerances={"position":0.02}`, obs at (8.0625,-3,4) → delta
  `0.0625 > 0.02` override → **FLAG** (proves per-device tolerance override beats default).
- `D-OVERRIDE-LOOSE` pos (8,4,4), `tolerances={"position":0.5}`, obs at (8.25,4,4) → delta
  `0.25 < 0.5` override → **PASS** (same 0.25 that FLAGs at default tol now passes).
All observations within the per-device match gate (override-tight gate = `max(0.02*3,0.5)=0.5`, so
0.0625 still matches). Expected summary: pass=4, flag=4, total=8.

### F04 — `f04_coverage_orientation` (coverage distinctions + orientation FLAG + up_axis no-op)
Single level L1, one depth shot S1 (camera at origin).
- `D-INVIEW-ABSENT` pos (8,0,4) IN frustum, but **no observation anywhere near it** → in-coverage
  ABSENT, **confidence 0.7**, note "expected in view but no matching device observed". S1 has
  observations only for OTHER devices, none within 0.5 of (8,0,4).
- `D-GAP-ABSENT` pos (-8,0,7), facing 180 (behind camera, like f01 D-GAP) → coverage-gap ABSENT,
  **confidence 0.25**, note "not within any captured view (coverage gap)". No same-level obs nearby.
- `D-ORIENT-FLAG` pos (8,2,4), facing 0.0, obs at (8,2,4) facing `30.0` → orientation delta
  `30>10` → **FLAG**.
- `D-DOWN-PASS` pos (8,-2,4), `up_axis="down"`, facing 0.0, obs at (8,-2,4) facing `1.0` → **PASS**.
  Manifest carries `up_axis:"down"`; report verdict is PASS regardless (documents §0.4: up_axis is
  not compared). §5.3 asserts both that the manifest round-trips `up_axis=="down"` AND that the
  verdict is pass, making the no-op explicit and intentional.
Expected summary: pass=1, flag=1, absent=2, total=4. (Both ABSENT confidences in one scenario,
asserted explicitly per-device.)

### F05 — `f05_distinctions` (TYPE_MISMATCH vs ABSENT vs FLAG vs low-confidence-no-mismatch)
Single level L1, one depth shot S1.
- `D-TYPE` "Card Reader"/"HID-R10" pos (7.5,1,4); obs at (7.5,1,4) `detected_type="Exit Sign"`,
  `type_confidence=0.9` → **TYPE_MISMATCH** (conf 0.9).
- `D-TYPE-LOWCONF` "Card Reader"/"HID-R10" pos (7.5,2,4); obs at (7.5,2,4) `detected_type="Exit Sign"`,
  `type_confidence=0.4` (`<0.6`) → must NOT be type_mismatch; position/height/orient within tol →
  **PASS** (proves the confidence gate; `identity_confirmed` stays False because confidence<0.6).
- `D-ABSENT` "Speaker"/"JBL-C6" pos (8,-2,4) in view, no nearby obs → **ABSENT** (conf 0.7).
- `D-FLAG` "Card Reader"/"HID-R10" pos (8,0,4); obs at (8,0.3,4) (pos delta 0.3, within gate 0.5,
  over tol 0.083) → **FLAG**.
- `D-PASS` "Card Reader"/"HID-R10" pos (8,3,4); obs at (8.02,3,4.01) tight → **PASS**.
Expected summary: pass=2, flag=1, absent=1, type_mismatch=1, total=5.
This scenario alone demonstrates all four verdict classes (useful for the ratchet).

### F06 — `f06_device_wall` (dense coplanar wall + type-aware tie-break)
Single level L1, one depth shot S1. 12 card readers on a vertical wall plane at x=8, with a single
concrete layout (resolves the review's 0.5-vs-0.6 ambiguity):

```python
ys = [-2.75 + 0.6 * i for i in range(12)]   # 12 positions, 0.6 ft apart, verified
```

Spacing 0.6 keeps a device's correct observation the unambiguous nearest: nearest correct obs at
distance 0.0–0.05, nearest wrong-device obs ≥0.55 (safely off the gate edge). Each device
`D-W00..D-W11` is at `(8, ys[i], 4)`, facing 0, with a co-located correct obs at `(8.02, ys[i], 4)`
(jitter ≤0.03 → PASS). The draft's 0.5 layout is deleted.

- One device `D-W05` additionally has a **decoy wrong-type observation** placed slightly closer than
  its correct obs: correct obs at `(8.02, ys[5], 4)` (type-agreeing), decoy at `(8.0, ys[5], 4)`
  with `detected_type="Exit Sign"`, `type_confidence=0.9`. The type-aware tie-break in
  `compare.match_device` (`key=(disagrees, d)`) must prefer the agreeing obs → **PASS**, not
  TYPE_MISMATCH. §5.3 asserts D-W05 verdict == pass. This pins the "nearby decoy of the wrong type
  can't mask the correct device" behavior the code comments promise but no golden currently proves.
Expected: all 12 PASS; summary pass=12, total=12. (Deterministic stress test of per-device
association under crowding.)

### F07 — `f07_empty_manifest` (zero devices)
Manifest: 1 level L1, `devices: []`. Capture: 1 shot S1 with some observations (which must be
ignored — there are no expected devices to match). Report: `device_results: []`,
summary `{total:0,pass:0,flag:0,absent:0,type_mismatch:0}`. Proves the pipeline + output schema
accept the degenerate empty corpus.

> Verdict-class coverage note: F07 emits no verdicts; the ratchet
> `test_golden_demonstrates_every_verdict_class` is satisfied by F05 (and f01). The §5.4 ratchet
> update unions across all goldens, so F07 contributes nothing and that's fine.

---

## 5. Test integration

### 5.1 conftest additions
**None.** The existing `fixtures_dir` (session-scoped `Path` to `engine/fixtures`) and the registry
maps are sufficient. The draft's `all_scenarios` session fixture and `_slug_for` helper are dropped
(they were never consumed). Keep all existing `f01_*` fixtures untouched (referenced by name elsewhere).

### 5.2 Parametrized golden + payload-validation tests (add to `test_integration_golden.py`)
```python
import json
import pytest
import ca_elevation_engine
from ca_elevation_engine import registry, ingest
from ca_elevation_engine.pipeline import run_pipeline
from fixtures.seeders._common import GENERATED_AT   # single source of the constant

@pytest.mark.parametrize("scenario,golden_name", list(registry.SCENARIO_GOLDENS.items()))
def test_scenario_reproduces_golden(scenario, golden_name, fixtures_dir):
    stem = registry.SCENARIO_PAYLOAD_STEMS[scenario]
    mpath = fixtures_dir / "synthetic" / f"{stem}.manifest.json"
    cpath = fixtures_dir / "synthetic" / f"{stem}.capture.json"
    golden = json.loads((fixtures_dir / "golden" / golden_name).read_text())
    result = run_pipeline(mpath, cpath, generated_at=GENERATED_AT)
    produced = result.report.to_dict()
    assert produced.get("engine_version") == ca_elevation_engine.__version__
    produced.pop("engine_version", None)
    golden.pop("engine_version", None)
    assert produced == golden, f"{scenario} drifted from golden"

@pytest.mark.parametrize("scenario", list(registry.SCENARIO_GOLDENS))
def test_scenario_payloads_validate(scenario, fixtures_dir):
    stem = registry.SCENARIO_PAYLOAD_STEMS[scenario]
    ingest.load_manifest(fixtures_dir / "synthetic" / f"{stem}.manifest.json")
    ingest.load_capture(fixtures_dir / "synthetic" / f"{stem}.capture.json")
```

`from fixtures.seeders._common import GENERATED_AT` works in the test process because pytest runs
from `engine/` (the repo's configured `rootdir`/`testpaths`), putting `engine/` on `sys.path`; if the
import resolution proves environment-sensitive, fall back to importing the constant from the package
test-support path used elsewhere — but **the constant must come from exactly one definition**
(§5.6 enforces agreement).

The parametrized test covers f01 too (f01 is in `SCENARIO_GOLDENS`). **Keep the existing
f01-specific tests** (`test_pipeline_reproduces_golden`, `test_golden_summary`) — acceptable
redundancy that keeps the f01 case readable and pins f01's exact summary.

### 5.3 Intent-pinning assertions (so geometry accidents are caught, not just "matches golden")
A golden that silently drifted to a different-but-self-consistent verdict mix would still pass §5.2;
these pin the categorical design intent plus the two fixed ABSENT confidences.

```python
def _golden(fixtures_dir, name):
    return json.loads((fixtures_dir / "golden" / name).read_text())

def _by_id(golden):
    return {r["device_id"]: r for r in golden["device_results"]}

def test_f02_datum_paths(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f02_multilevel_datum_verdict_report.json"))
    assert r["D-L2-DATUM-PASS"]["verdict"] == "pass"
    assert r["D-L2-HEIGHT-FLAG"]["verdict"] == "flag"
    assert any("mounting height" in n for n in r["D-L2-HEIGHT-FLAG"]["notes"])
    assert r["D-L2-HEIGHT-PASS"]["verdict"] == "pass"

def test_f03_boundary_directions(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f03_tolerance_boundary_verdict_report.json"))
    assert r["D-POS-INSIDE"]["verdict"] == "pass"
    assert r["D-POS-OUTSIDE"]["verdict"] == "flag"
    assert r["D-ORIENT-OUTSIDE"]["verdict"] == "flag"      # the orientation-FLAG path
    assert r["D-OVERRIDE-TIGHT"]["verdict"] == "flag"
    assert r["D-OVERRIDE-LOOSE"]["verdict"] == "pass"

def test_f04_coverage_confidences(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f04_coverage_orientation_verdict_report.json"))
    assert r["D-INVIEW-ABSENT"]["verdict"] == "absent"
    assert r["D-INVIEW-ABSENT"]["confidence"] == 0.7      # literal const in verdict.py (safe ==)
    assert r["D-GAP-ABSENT"]["verdict"] == "absent"
    assert r["D-GAP-ABSENT"]["confidence"] == 0.25        # literal const in verdict.py (safe ==)
    assert r["D-ORIENT-FLAG"]["verdict"] == "flag"
    assert r["D-DOWN-PASS"]["verdict"] == "pass"          # up_axis=down is a no-op on the verdict

def test_f04_manifest_up_axis_roundtrips(fixtures_dir):
    m = ingest.load_manifest(fixtures_dir / "synthetic" / "f04_coverage_orientation.manifest.json")
    d = next(x for x in m.devices if x.id == "D-DOWN-PASS")
    assert d.orientation.up_axis == "down"

def test_f05_distinctions(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f05_distinctions_verdict_report.json"))
    assert r["D-TYPE"]["verdict"] == "type_mismatch"
    assert r["D-TYPE-LOWCONF"]["verdict"] == "pass"       # confidence gate holds
    assert r["D-ABSENT"]["verdict"] == "absent"
    assert r["D-FLAG"]["verdict"] == "flag"
    assert r["D-PASS"]["verdict"] == "pass"

def test_f06_wall_all_pass_and_decoy(fixtures_dir):
    g = _golden(fixtures_dir, "f06_device_wall_verdict_report.json")
    assert all(r["verdict"] == "pass" for r in g["device_results"])
    assert g["summary"]["total"] == 12
    assert _by_id(g)["D-W05"]["verdict"] == "pass"        # agreeing obs beat the wrong-type decoy

def test_f07_empty(fixtures_dir):
    g = _golden(fixtures_dir, "f07_empty_manifest_verdict_report.json")
    assert g["device_results"] == []
    assert g["summary"] == {"total":0,"pass":0,"flag":0,"absent":0,"type_mismatch":0}
```

> The `== 0.7` / `== 0.25` exact-float equalities are intentional and SAFE: those confidences are
> literal constants in `verdict.py`, not geometry/rounding-derived. Do NOT "harden" them to
> `pytest.approx` (that would weaken the intent pin), and do NOT copy the exact-equality pattern to
> *match*-confidence values (those ARE geometry/rounding-derived and must be left to the golden diff,
> never asserted as literals). This is the only place exact-float assertion is correct.
>
> Workflow: after writing the seeders, run `regen_goldens`; if a categorical verdict or a 0.7/0.25
> confidence differs from these asserts, EITHER the geometry placement is wrong (fix the seeder) OR
> the intent is genuinely different (fix the assertion to a deliberate value) — never silently accept
> drift. The golden file remains the source of truth for all floats.

### 5.4 Registry ratchet update (`test_registry.py`)
- Change `test_golden_demonstrates_every_verdict_class` to union verdicts across ALL scenario
  goldens instead of only `f01_golden`:
  ```python
  import json
  def test_golden_demonstrates_every_verdict_class():
      seen = set()
      for golden_name in registry.SCENARIO_GOLDENS.values():
          g = json.loads((FIXTURES / "golden" / golden_name).read_text())
          seen |= {r["verdict"] for r in g["device_results"]}
      required = {v.value for v in registry.VERDICTS}
      assert not (required - seen)
  ```
  (Drop the `f01_golden` fixture parameter here; add `import json`. `FIXTURES` already exists in this
  test module.)
- `test_every_scenario_has_seeder_and_golden` already loops `SCENARIO_GOLDENS` → it automatically
  enforces the new seeders+goldens exist. No change needed beyond registering the scenarios.
- `test_check_ratchet_count` stays `== 7` / `== 5` (no checks added).
- Add `test_scenario_payload_stems_complete`:
  ```python
  def test_scenario_payload_stems_complete():
      assert set(registry.SCENARIO_PAYLOAD_STEMS) == set(registry.SCENARIO_GOLDENS)
  ```

### 5.5 Registry change (`registry.py`)
```python
SCENARIO_GOLDENS: dict[str, str] = {
    "f01_synthetic_office": "f01_verdict_report.json",
    "f02_multilevel_datum": "f02_multilevel_datum_verdict_report.json",
    "f03_tolerance_boundary": "f03_tolerance_boundary_verdict_report.json",
    "f04_coverage_orientation": "f04_coverage_orientation_verdict_report.json",
    "f05_distinctions": "f05_distinctions_verdict_report.json",
    "f06_device_wall": "f06_device_wall_verdict_report.json",
    "f07_empty_manifest": "f07_empty_manifest_verdict_report.json",
}
# Payload file stems are not derivable from scenario ids (f01 is the historical exception);
# bind them explicitly. Identity for f02-f07.
SCENARIO_PAYLOAD_STEMS: dict[str, str] = {
    "f01_synthetic_office": "f01_office",
    "f02_multilevel_datum": "f02_multilevel_datum",
    "f03_tolerance_boundary": "f03_tolerance_boundary",
    "f04_coverage_orientation": "f04_coverage_orientation",
    "f05_distinctions": "f05_distinctions",
    "f06_device_wall": "f06_device_wall",
    "f07_empty_manifest": "f07_empty_manifest",
}
SCENARIOS: tuple[str, ...] = tuple(SCENARIO_GOLDENS)
```

Option A (explicit stem map) is chosen over renaming f01's files or special-casing f01 in the test —
it avoids f01 file churn and the map is identity for every new scenario.

### 5.6 Constant-agreement test (centralize `GENERATED_AT`)
`GENERATED_AT` is defined once in `_common.py` (§3.1) and imported by both `regen_goldens.py` and the
golden tests. To guard against a future re-introduction of a divergent literal, add:

```python
def test_generated_at_single_source():
    from fixtures.seeders import _common, regen_goldens  # regen imports _common.GENERATED_AT
    # both must reference the same object/value; this fails if someone re-hardcodes a literal
    assert _common.GENERATED_AT == "2026-06-28T00:00:00Z"
    assert regen_goldens.c.GENERATED_AT == _common.GENERATED_AT
```

(Resolves the review's "three literal copies of the determinism constant" finding: there is now one
definition; this test pins it.)

---

## 6. Build / regen / verify procedure (the implementer runs this)

From `engine/` (the package dir with `pyproject.toml`), after `pip install -e "engine[dev]"`:

1. Add `engine/fixtures/__init__.py` and `engine/fixtures/seeders/__init__.py` (empty).
2. Write `_common.py` (incl. `GENERATED_AT`), the six seeders, `regen_goldens.py`, registry edits.
3. Generate payloads + goldens: `python -m fixtures.seeders.regen_goldens`.
4. **f01 safety check:** confirm regen did NOT touch f01. `git status` should show only new files
   under `synthetic/` and `golden/` (no `f01_*` changes). If `f01_office.*`/`f01_verdict_report.json`
   show as modified, the new code wrongly overwrote them — fix and revert f01 from git.
5. Validate schemas + fixtures, fail-closed: `python tools/validate_schemas.py -v` → must report all
   new manifests/captures/reports OK.
6. Run the suite headless: `pytest -q -m "not heavy"` → must stay green (79 existing engine tests +
   the new ones).
7. Lint/format: `ruff check . && ruff format --check .`. **mypy scope:** the repo's mypy config is
   `packages = ["ca_elevation_engine"]`; it does NOT type-check `engine/fixtures/**` or
   `engine/tests/**`. So "mypy clean" applies only to `ca_elevation_engine`, which this work item does
   not modify — there is no mypy gate on the seeders/tests, and no effort should be spent making them
   mypy-strict (resolves the review's "mypy overclaim" finding). Still keep
   `from __future__ import annotations` and simple annotations for readability.

If a golden's floats look noisy (FP residue), adjust the seeder to binary-exact values (powers-of-two
fractions: 0.0625, 0.03125, 0.125, 0.25) and regen — never hand-edit the golden.

---

## 7. Graceful degradation under this environment

- **No Revit / iOS / dotnet / swift:** nothing here touches them. Seeders emit JSON; the pipeline is
  pure CPython + numpy + jsonschema (all core deps). `revit-addin`/`ios-app` are untouched.
- **No heavy backends:** every shot is pose+pin+synthetic `observations`. No point clouds, no
  `depth_map` *content* (only nominal filenames, exactly as f01). `register.refine_registration`
  no-ops without a point cloud, so ICP is never reached. No `@pytest.mark.heavy` test is added;
  default CI (`pytest -m "not heavy"`) runs the lot.
- **No network / no clock / no randomness:** `generated_at` is injected from one constant; positions
  are literals; `engine_version` is popped before comparison. Re-running `regen_goldens` is idempotent.
- **PDF/HTML rendering not exercised here:** new golden tests call `run_pipeline` WITHOUT `out_dir`,
  so no report rendering, no `reportlab` dependency. (Existing f01 PDF/HTML tests cover those paths
  via `importorskip`.)
- **If `jsonschema` somehow absent:** `validate_schemas.py` exits 1 with a clear message;
  `run_pipeline(validate=True)` raises at ingest — fail-closed, consistent with the repo.

---

## 8. Acceptance criteria (definition of done)

1. Six new seeders + `_common.py` + `regen_goldens.py` exist; `python -m fixtures.seeders.regen_goldens`
   regenerates all f02–f07 payloads + goldens deterministically and idempotently, and leaves f01
   untouched.
2. `engine/fixtures/synthetic/` has 6 new `*.manifest.json` + 6 new `*.capture.json`;
   `engine/fixtures/golden/` has 6 new `*_verdict_report.json`. All committed.
3. `registry.SCENARIO_GOLDENS` and `SCENARIO_PAYLOAD_STEMS` list all 7 scenarios; ratchet tests in
   `test_registry.py` pass, including the all-goldens verdict-coverage union and
   `test_scenario_payload_stems_complete`.
4. `test_integration_golden.py` parametrized test reproduces every scenario's golden exactly (minus
   `engine_version`); the §5.3 intent assertions and §5.6 constant-agreement test pass; the existing
   f01 tests still pass unchanged.
5. `python tools/validate_schemas.py` passes fail-closed over the expanded corpus.
6. `pytest -q -m "not heavy"` green; `ruff check`/`ruff format --check` clean; **mypy clean for
   `ca_elevation_engine`** (the only mypy-scoped package; not modified). No heavy deps introduced; no
   engine source (`verdict.py`/`compare.py`/`register.py`/`models.py`/schemas) modified.
7. The verdict paths newly proven by a committed golden include: orientation-FLAG via facing_angle,
   in-coverage-ABSENT(0.7) vs gap-ABSENT(0.25) side-by-side, mounting-height datum via
   `z - level.elevation` across multiple levels, mounting-height FLAG, just-inside/just-outside
   position/height/orientation boundaries, per-device tolerance override (both directions),
   low-confidence-detected-type NON-mismatch, wrong-type-decoy tie-break, dense wall association,
   and the zero-device empty corpus.

---

## 9. Risks & mitigations

- **R1 Floating-point noise in goldens.** Binary-exact deltas (powers-of-two) + machine-generated
  goldens (never hand-typed). Intent asserts pin only categorical verdicts + the two fixed ABSENT
  confidences.
- **R2 Frustum geometry surprises** (a device intended in-view falls out, flipping ABSENT confidence
  or coverage). Copy f01's proven placements (in-view near (8,·,4); gap near (−8,·,·)); verify via the
  produced golden + §5.3 confidence asserts before committing. The reviewer ran every scenario and
  the placements reproduce the intended coverage.
- **R3 Golden format drift.** `regen_goldens` uses `indent=2, sort_keys=True` + trailing `\n`,
  byte-identical to the committed f01 golden (verified §0.9). Regen never writes f01.
- **R4 Seeder import path.** Single supported path: package route (`__init__.py` + `python -m`); no
  per-seeder shim to drift. Tests/regen use the module form only.
- **R5 Ratchet over-coupling.** The registry ratchet now unions verdicts across all goldens; a future
  scenario emitting no verdicts (like F07) is harmless. Documented in §4 F07 note.
- **R6 Match-gate masking a FLAG.** A device whose breached delta exceeds the *gate* (0.5) goes
  ABSENT, not FLAG. All FLAG cases here keep delta `<= 0.5`; asserted by §5.3. Do not place a
  0.6-ft "FLAG" that would silently go ABSENT.
- **R7 `up_axis` expectation.** Reviewers may expect up/down to drive a verdict; it does not in v1
  (§0.4, non-goals, F04 no-op assertion). This is honesty-preserving, not a gap to paper over.
- **R8 `GENERATED_AT` divergence.** One definition in `_common.py`; §5.6 test fails if a divergent
  literal is reintroduced.

---

## 10. Adversarial review resolutions

The review returned **no blockers and no majors** ("sound; ship with minor fixes"). All seven minor
findings are resolved here:

1. **mypy overclaims (seeders/tests not mypy-scoped).** Resolved in §6.7 and AC#6: "mypy clean" is
   scoped explicitly to `ca_elevation_engine` (the only package in `[tool.mypy] packages`); the spec
   no longer implies a mypy gate on seeders/tests and tells the implementer not to chase seeder
   mypy-strictness.
2. **Dead conftest fixtures (`all_scenarios`, `_slug_for`).** Resolved in §2/§5.1: dropped entirely;
   the parametrized tests read the registry maps and the existing `fixtures_dir` directly. No unused
   conftest additions.
3. **F02 `D-L2-HEIGHT-EDGE-PASS` misleading name + exactly-equal paragraph.** Resolved in §4 F02:
   renamed to `D-L2-HEIGHT-PASS`, the exactly-equal (`delta==0.042`) paragraph deleted, and a single
   clean just-inside value (`4.03125`, delta `0.03125`) specified. F03 owns the boundary semantics.
4. **Two import strategies, only one wired.** Resolved in §3.3: a single supported path (package
   route + `python -m`). The per-seeder `__package__` shim and the `spec_from_file_location`
   alternative are removed, eliminating per-file copy-paste boilerplate that CI never exercises.
5. **`GENERATED_AT` duplicated across three files.** Resolved in §3.1/§3.4/§5.2/§5.6: defined once in
   `_common.py`, imported by regen and tests, and pinned by a new constant-agreement test (§5.6).
6. **F06 spacing ambiguity (0.5 vs 0.6).** Resolved in §4 F06: one concrete layout,
   `ys = [-2.75 + 0.6*i for i in range(12)]`, with correct obs at `(8.02, y, 4)` and the decoy at
   `(8.0, ys[5], 4)`; the 0.5 variant is deleted. (Reviewer verified 0.6/12-device + decoy → all PASS,
   D-W05 PASS.)
7. **§5.3 exact-float `== 0.7 / 0.25` — document why it's safe.** Resolved in §0.1 and the §5.3 note:
   both confidences are literal constants in `verdict.py` (not geometry-derived), so exact equality is
   the correct intent pin; the note explicitly forbids weakening them to `approx` and forbids copying
   exact-equality to geometry-derived match confidences.

Non-issues the reviewer explicitly cleared (golden byte-format, heavy-dep absence, schema validity of
all payloads incl. empty devices / `up_axis:"down"` / partial tolerances, f01 left untouched, ratchet
union correctness, match-gate masking, payload-stem option A) are retained as designed and not
re-litigated.
