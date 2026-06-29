# Testing, CI, and fixture discipline

This repo ports a hard-won testing discipline from an earlier codebase as
*principles*, adapted to a three-language stack. The principles (numbered as in
`design.md`, "Porting the testing / CI / fixture discipline") are below, mapped
to this repo's actual layout. `CONTRIBUTING.md` has the day-to-day commands;
this document is the rationale and the rules.

The guiding idea: **the tests and CI are the project's memory.** Claude builds in
fast episodic sessions and is not an always-on daemon. What carries discipline
across sessions is a green, honest, fail-closed test suite.

---

## 1. Fixture as immutable single source of truth, built by seeders

The fixture is built by deterministic, version-gated **seeder** scripts and is
then immutable. **Tests read fixtures; they never write or mutate them.**

For this repo the fixtures are:

- a sample Revit-derived **spec manifest** for manifest-ingest tests,
- **synthetic + at least one real capture package** (E57/point cloud + posed
  images + pins), and
- **golden expected verdict reports**.

Rules:

- Each fixture property is enumerated as an invariant (an id + title + verifier),
  so what a fixture guarantees is declared, not folklore.
- Seeders build fixtures deterministically; ad-hoc fixture mutation is forbidden.
- A test needing a different input adds a new seeder/fixture; it does not edit the
  shared one.
- Fixture filename convention routes schema validation:
  `*.manifest.json`, `*.capture.json`, `*.report.json`.

### Synthetic scenario corpus

The synthetic scenarios (seeders under `engine/fixtures/seeders/`, payloads under
`synthetic/`, goldens under `golden/`) each pin a distinct set of verdict paths so
an accidental engine/geometry change is caught by a golden diff plus the
intent-pinning assertions in `tests/test_integration_golden.py`:

| Scenario | Verdict paths it pins | Golden |
|---|---|---|
| `f01_synthetic_office` | one of every verdict class (pass/flag/absent/type_mismatch), gap vs in-coverage absence | `f01_verdict_report.json` |
| `f02_multilevel_datum` | mounting-height datum via `z - level.elevation` across 2 levels; explicit `mounting_height` PASS vs height FLAG | `f02_multilevel_datum_verdict_report.json` |
| `f03_tolerance_boundary` | position/height/orientation just-inside (PASS) vs just-outside (FLAG); per-device tolerance override both ways | `f03_tolerance_boundary_verdict_report.json` |
| `f04_coverage_orientation` | in-coverage ABSENT (0.7) vs coverage-gap ABSENT (0.25); orientation FLAG via `facing_angle`; `up_axis="down"` no-op PASS | `f04_coverage_orientation_verdict_report.json` |
| `f05_distinctions` | TYPE_MISMATCH vs ABSENT vs FLAG vs low-confidence-detected-type non-mismatch (confidence gate) | `f05_distinctions_verdict_report.json` |
| `f06_device_wall` | dense 12-device association under crowding; wrong-type decoy tie-break | `f06_device_wall_verdict_report.json` |
| `f07_empty_manifest` | zero-device manifest; empty `device_results`, all-zero summary | `f07_empty_manifest_verdict_report.json` |

Goldens are machine-generated, never hand-typed. Regenerate after an intentional
engine change with `python -m fixtures.seeders.regen_goldens` (run from `engine/`);
a changed golden must be a deliberate, reviewed diff.

> **Registration-note invariant.** Registration notes for the *matched shot* now
> reach `device_results[].notes` (prefixed `registration:`). If a fixture's matched
> shot gains a registration note (e.g. it sets `point_cloud`, or its `coarse_register`
> emits the pose+pin-only "approximate" note because it has *neither* `depth_map` nor
> `point_cloud`), the golden's `notes` array changes -- **regenerate the golden** and
> record the diff. Today no synthetic fixture sets `point_cloud` and the f0x captures
> carry `depth_map`, so this note does not fire and goldens are unaffected.

## 2. Registry as single source of truth + coverage ratchets

A **registry** (`engine/src/ca_elevation_engine/registry.py`) declares every
engine check, every verdict class the engine can emit, and every registered
capture scenario, each with its contract. Ratchet tests enforce a *one-way*
coverage guarantee:

- A new check, verdict, or scenario must ship **with** a fixture and a golden
  case; the ratchet fails otherwise.
- Coverage only goes up. New smoke-only / waived entries are capped (e.g. at zero
  new un-covered entries) and allowlists are purged of stale entries.

Add a capability and its registry entry, fixture, and golden in the same change.

## 3. Schema / structure validation in CI

`engine/tools/validate_schemas.py` confirms each JSON Schema under
`engine/src/ca_elevation_engine/schemas/` is a valid draft-07 schema, then
validates every discovered fixture against the matching schema, **fail-closed**
(exit 1 on any error). The `validate schemas + fixtures` job in
`.github/workflows/ci.yml` runs it on every change to schemas, fixtures, or the
validator (see docs/ci.md). A malformed manifest / capture
package / report fails the build rather than the field. The script is robust to
fixtures not existing yet (Phase 0 bootstrap validates the schemas alone).

## 4. Tiered tests: cheap local -> CI -> live

| Tier | What | Where it runs |
|---|---|---|
| **Headless unit** | engine pure math + IO, add-in logic without Revit, app logic without ARKit | every push/PR, whole CI matrix; the bulk |
| **Integration (golden)** | engine over fixture capture packages -> golden reports, snapshot-compared for determinism | every push/PR (engine job) |
| **Live / gated** | Revit add-in against a real Revit install; iOS app on a real LiDAR device | manual, per-SHA attested, **never blocks unit CI** |

Engine pytest markers (`engine/pyproject.toml`): `unit`, `integration`, `heavy`.
CI runs `pytest -m "not heavy"`. Heavy native backends and live tests are opt-in.

### 4.1 Heavy registration path (Open3D ICP + real E57)

The optional `[heavy]` backends (Open3D, pye57, OpenCV) drive the fine-registration
path (`refine_registration` → Open3D ICP) and the E57 loader (`pointcloud._load_e57`
→ pye57). These deselect from default CI but are exercised end-to-end behind
`@pytest.mark.heavy` + `pytest.importorskip`, so they SKIP cleanly when the backend
is absent and run for real when it is present:

| Test module | Proves (heavy, runs only with the backend) |
|---|---|
| `test_register_icp_heavy.py` | ICP genuinely runs and pulls an off-by-known-offset coarse transform *toward* truth (PLY/Open3D). |
| `test_integration_heavy.py` | full `run_pipeline`: posed cloud → ICP → verdict report; asserts ICP improved alignment **and** the residual note reaches `DeviceResult.notes` + the rendered HTML/JSON. |
| `test_e57_heavy.py` | the production loader reads a **real, committed E57** (`fixtures/scanner/f08_posed_scan.e57`) and applies its pose/scaling (global ≠ local), then drives it end-to-end to a verdict. |

The E57 fixture is a genuine ASTM-E2807 container (not a stub), generated once by
`engine/tools/make_e57_fixture.py` and committed. E57 containers embed
GUIDs/timestamps so the bytes are not reproducible; regenerate (needs the `[heavy]`
extra) only when the geometry contract in that script changes:

```bash
pip install -e "engine[dev,report,heavy]"   # open3d is gated to python < 3.13
cd engine && python -m tools.make_e57_fixture
cd engine && pytest -q                        # heavy tests now run instead of skip
```

> Install note: the heavy extra pulls native wheels (Open3D drags in a large
> visualization stack). On a debian-managed system where pip cannot uninstall
> distro packages, install into a fresh virtualenv. `open3d` is pinned to
> `python_version < '3.13'`, so on Linux + py3.13 the heavy ICP tests have no
> backend and silently skip — a real coverage gap, not a guarantee.

## 5. Pre-commit mirrors CI, per language

`.pre-commit-config.yaml` recreates the CI checks locally:

- **Python:** ruff (lint + format), mypy (engine), schema validation.
- **C#:** `dotnet format --verify-no-changes` (manual stage; needs the SDK).
- **Swift:** `swift-format`/swiftlint (manual stage; needs the toolchain).
- **Secrets:** gitleaks on every commit.
- **Hygiene:** trailing-whitespace, end-of-file-fixer, check-yaml/json,
  check-merge-conflict.

The default (pre-commit) stage is kept fast; mypy, schema validation, the .NET /
Swift toolchains, and the heavy pytest suite run on `pre-push` / `manual`.

## 6. CI matrix across components

A single workflow (`.github/workflows/ci.yml`) runs per-component jobs, each on
its own OS, so a break is localized (see docs/ci.md for the full model):

| Job (in `ci.yml`) | Component | Runner | Notes |
|---|---|---|---|
| `engine` | engine | ubuntu-latest | matrix py3.10/3.11/3.12; ruff + mypy(blocking) + pytest cov |
| `revit-addin (windows)` | add-in | windows-latest | build/test non-blocking (Revit API assemblies gated); skips if no `.sln` |
| `CaElevationKit (macos)` | `CaElevationKit` | macos-latest | `swift build`/`test` of the pure kit; skips if no `Package.swift` |
| `validate schemas + fixtures` | schemas/fixtures | ubuntu-latest | fail-closed JSON Schema + fixture validation |

A `changes` job (dorny/paths-filter) selects which component jobs run, so
unrelated changes don't trigger them, and the platform-coupled jobs guard for the
component existing on disk before building. The single required status check is
`CI / all-green`.

## 7. Separation of pure logic from platform-coupled code

The testability rule, applied to all three components:

- **Engine:** math/registration/verdict logic vs file/format IO.
- **Add-in:** add-in logic vs the Revit API surface.
- **App:** capture/bundle logic (`CaElevationKit`) vs ARKit/SwiftUI.

If a unit of logic can only be exercised with the platform present, it is in the
wrong layer. The seam (the two JSON payloads) is what lets the engine run with no
Revit and no device.

## 8. Fail-closed gates keyed to immutable commit state

Gates fail closed and are keyed to immutable per-SHA commit state. Live/gated
results are attested per commit and decoupled from code review (a kill-switch
label can decouple review from the CI lock). The release flow is kept separate
from the PR flow. CI strictness only ratchets up.

---

## Running it locally

```bash
pip install -e "engine[dev,report]"
ruff check engine && ruff format --check engine
cd engine && mypy
cd engine && pytest -q -m "not heavy" --cov=ca_elevation_engine
python engine/tools/validate_schemas.py -v
```

For the add-in and app, see the per-component setup in `CONTRIBUTING.md`.
