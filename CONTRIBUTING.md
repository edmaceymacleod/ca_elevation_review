# Contributing to CA Elevation Review

Thanks for helping build an honest, open verification layer. This repo is a
three-language monorepo, and its tests + CI are deliberately the project's
*memory*: Claude builds in fast episodic sessions, and the only thing that
carries discipline from one session to the next is a green, honest test suite.
Keep it green and keep it honest.

This document covers per-component dev setup, the testing model, the fixture and
registry discipline to respect, and commit conventions. The principles here are
ported from the design doc (`docs/design.md`, section "Porting the testing / CI /
fixture discipline"); deeper detail lives in `docs/testing.md`.

---

## Repository layout

| Path | Component | Language | Build target |
|---|---|---|---|
| `engine/` | OSS core engine | Python 3.10+ | Linux |
| `revit-addin/` | Revit desktop add-in | C# / .NET | Windows |
| `ios-app/` | iPhone capture app + `CaElevationKit` | Swift | macOS |

Each component is independently buildable and testable so a break is localized.
You do **not** need Revit or an iPhone to work on the engine.

---

## Dev setup per component

### Engine (Python) -- start here for Phase 0

```bash
# From the repo root.
python -m venv .venv && source .venv/bin/activate
pip install -e "engine[dev,report]"        # add ,heavy only when you need native backends
```

What CI runs (mirror it locally before pushing):

```bash
ruff check engine
ruff format --check engine
cd engine && mypy                           # blocking in CI
cd engine && pytest -q -m "not heavy" --cov=ca_elevation_engine
python engine/tools/validate_schemas.py -v --strict-unknown  # schemas + fixtures
python engine/tools/regen_fixtures.py --check                # fixtures match seeders
```

Config lives in `engine/pyproject.toml`: ruff (line length 100; rules E/F/I/W/UP/B),
mypy (`packages = ["ca_elevation_engine"]`), pytest markers (`unit`, `integration`,
`heavy`), the extras (`dev` / `heavy` / `report`), and the `ca-elevation` console
script.

### Revit add-in (C#) -- Phase 1

```bash
dotnet restore revit-addin/CaElevationReview.sln
dotnet format  revit-addin/CaElevationReview.sln --verify-no-changes
dotnet build   revit-addin/CaElevationReview.sln -c Release
dotnet test    revit-addin/CaElevationReview.sln -c Release
```

The Revit API reference assemblies are **not** redistributable and are absent on
hosted CI, so the CI build/test steps are non-blocking. Anything that needs a
live Revit session is a *live* test (see below) and runs on a developer machine.

### iOS app (Swift) -- Phase 2

Only the pure `CaElevationKit` library builds and tests headlessly:

```bash
cd ios-app
swift build
swift test
```

The SwiftUI + ARKit app layer (`Sources/CaElevationApp`) is an Xcode App target
that depends on the kit; on-device LiDAR tests run only on real hardware.

---

## The tiered testing model (design principle #4)

Tests come in three tiers. Cheap ones run everywhere; expensive ones are gated
and never block the unit CI.

1. **Headless unit** -- the bulk. Pure engine math + IO, add-in logic without the
   Revit API, app logic without ARKit. No device, no Revit, no heavy backend.
   Runs on every push/PR across the whole CI matrix.
2. **Integration (golden)** -- the engine over fixture capture packages producing
   golden reports, compared by snapshot/golden-file for determinism. A changed
   golden must be an intentional, reviewed diff.
3. **Live / gated** -- the Revit add-in against a real Revit install, the iOS app
   on a real LiDAR device. Largely manual, attested per-SHA, **never blocking the
   unit CI.** Hosted runners cannot run these (no Revit license, no LiDAR).

Mark engine tests with the pytest markers: `unit`, `integration`, `heavy`. CI
runs `-m "not heavy"`; heavy/live work is opt-in.

---

## Fixture discipline (design principle #1)

**The fixture is the immutable single source of truth. Seeders build it. Tests
read it and never write it.**

- Fixtures (a sample Revit-derived manifest, synthetic + at least one real
  capture package, golden expected reports) are built by deterministic,
  version-gated **seeder** scripts -- not edited by hand, not mutated by tests.
- Each fixture property gets an invariant id + a verifier, so "what this fixture
  guarantees" is enumerated, not folklore.
- A test that needs a *different* input writes a new fixture via a seeder; it does
  not mutate the shared one. Ad-hoc fixture mutation is forbidden.
- `engine/tools/validate_schemas.py` validates every fixture against its JSON
  Schema, fail-closed, in CI (the `validate schemas + fixtures` job in
  `.github/workflows/ci.yml`; see docs/ci.md).

Fixture filename convention (so the validator can route them):
`*.manifest.json` -> spec manifest, `*.capture.json` -> capture package,
`*.report.json` -> verdict report.

Goldens are machine-generated, never hand-edited. After an **intentional** engine
change, regenerate the synthetic-scenario payloads + goldens (f02-f07) by running,
from `engine/`:

```bash
python -m fixtures.seeders.regen_goldens
```

This re-runs the real pipeline and rewrites each `golden/*_verdict_report.json`
deterministically (it never touches f01). A changed golden must be an intentional,
reviewed diff -- if regen produces a diff you did not expect, treat it as a
regression, not a fixture update.

> **Regenerating fixtures (the one-stop tool).** Fixtures (manifest, capture,
> golden) are generated, never hand-edited. To change a scenario, edit its seeder
> under `engine/fixtures/seeders/` then run `python engine/tools/regen_fixtures.py`
> to rewrite the committed files for **every** registered scenario, and review the
> diff. CI runs `python engine/tools/regen_fixtures.py --check` and fails if the
> committed fixtures drift from their seeders. If an intentional engine change
> moves a golden, the same command updates it -- commit that as a reviewed diff. A
> **package version bump** also moves the golden's `engine_version`; re-run regen
> as part of the bump PR. (`regen_fixtures.py` derives every file from each
> seeder's `build_manifest()` / `build_capture()` plus the engine pipeline, so it
> is generic over scenarios and the serialization is byte-locked: synthetic
> payloads are authored-order with no trailing newline, goldens are the engine's
> key-sorted `render_json` with a trailing newline.)

## Registry + coverage ratchet (design principle #2)

A registry (`engine/src/ca_elevation_engine/registry.py`) is the single source of
truth for what the engine supports -- every verification check, every verdict
class, and every registered capture scenario is declared there with its
contract. Ratchet tests enforce a **one-way** coverage guarantee:

- A new check, verdict, or scenario must ship **with** fixture coverage and a
  golden case; the ratchet test fails if it does not.
- Coverage may only go up. New "smoke-only" or waived entries are capped (e.g.
  at zero new un-covered entries) and allowlists are purged of stale entries.

When you add a capability, add its registry entry, its fixture, and its golden in
the same change.

## Pure logic vs platform separation (design principle #7)

Keep pure, deterministic logic separate from platform-coupled IO so it stays
unit-testable without the platform:

- **Engine:** math/registration/verdict logic separate from file/format IO.
- **Add-in:** add-in logic separate from the Revit API surface.
- **App:** capture/bundle logic (`CaElevationKit`) separate from ARKit/SwiftUI.

If a piece of logic can only be tested with the platform present, it is probably
in the wrong layer.

---

## Pre-commit

Pre-commit mirrors CI per language (design principle #5). The default stage is
fast (ruff lint + format, secret scan, file hygiene); slow/toolchain-coupled
hooks (mypy, schema validation, `dotnet format`, `swift-format`, heavy pytest)
run on `pre-push` or `manual`.

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type pre-push

pre-commit run --all-files                          # fast default hooks
pre-commit run --hook-stage pre-push --all-files    # mypy + schema validation
pre-commit run --hook-stage manual dotnet-format    # opt-in toolchain hooks
```

The default stage also runs a **README freshness** guard
([`tools/check_readme_freshness.py`](tools/check_readme_freshness.py)): a
structural change -- a top-level directory added or removed, `engine/pyproject.toml`,
or any `docs/` file -- must also stage `README.md`, so the top-level docs don't
go stale while a phase is worked. It blocks the commit but is always bypassable
with `git commit --no-verify` when a change genuinely needs no README update.

---

## Commits and pull requests

- Use clear, conventional-ish commit subjects: `engine: add presence verdict`,
  `addin: extract mounting height`, `ios: bundle round-trip`, `ci: ...`,
  `docs: ...`, `fix: ...`, `test: ...`. Imperative mood, scoped by component.
- One logical change per PR; keep the CI matrix green for the component(s) you
  touched. Path filters mean you only trigger the relevant jobs.
- New capability = code + registry entry + fixture + golden, together.
- A changed golden file must be intentional and explained in the PR description.
- Live/gated test results are attested separately and are not a merge gate.

By contributing you agree your contributions are licensed under Apache-2.0.
