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

## 2. Registry as single source of truth + coverage ratchets

A **registry** declares every engine check and every supported device family /
capture scenario with its contracts. Ratchet tests enforce a *one-way* coverage
guarantee:

- A new check or supported device family must ship **with** a fixture and a golden
  case; the ratchet fails otherwise.
- Coverage only goes up. New smoke-only / waived entries are capped (e.g. at zero
  new un-covered entries) and allowlists are purged of stale entries.

Add a capability and its registry entry, fixture, and golden in the same change.

## 3. Schema / structure validation in CI

`engine/tools/validate_schemas.py` confirms each JSON Schema under
`engine/src/ca_elevation_engine/schemas/` is a valid draft-07 schema, then
validates every discovered fixture against the matching schema, **fail-closed**
(exit 1 on any error). The `schema-validation.yml` workflow runs it on every
change to schemas, fixtures, or the validator. A malformed manifest / capture
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

Each component builds and tests on its own OS, independently, so a break is
localized:

| Workflow | Component | Runner | Notes |
|---|---|---|---|
| `engine.yml` | engine | ubuntu-latest | matrix py3.10/3.11/3.12; ruff + mypy(non-blocking) + pytest cov |
| `revit-addin.yml` | add-in | windows-latest | build/test non-blocking (Revit API assemblies gated); skips if no `.sln` |
| `ios-app.yml` | `CaElevationKit` | macos-latest | `swift build`/`test` of the pure kit; skips if no `Package.swift` |
| `schema-validation.yml` | schemas/fixtures | ubuntu-latest | fail-closed JSON Schema + fixture validation |

Each workflow is `paths:`-filtered to its component so unrelated changes do not
trigger it, and the platform-coupled jobs guard for the component existing on
disk before building.

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
