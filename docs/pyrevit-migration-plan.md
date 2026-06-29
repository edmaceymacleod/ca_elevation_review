# Migration plan: standalone C# add-in → pyRevit extension

**Status:** Proposal for review — 2026-06-29. No code written yet. This documents
the concrete shape of pivoting the Revit *front door* from the standalone C#
add-in (`revit-addin/`) to a **pyRevit extension**, per the decision to target
pyRevit's **CPython runtime** with the engine invoked **out-of-process**.

The CPython engine (`engine/`) does **not** change. Only the desktop front door
is replaced. This plan exists so the trade-offs and file layout can be reviewed
before any code moves.

---

## 1. Why this produces more real product

The standalone C# add-in cannot be compiled or tested in our Linux/CI
environment (no .NET toolchain, no Revit API assemblies), so everything in
`revit-addin/` today is "compilable-in-spirit" plus xUnit tests that never run
here. The pivot does **not** make the Revit-API-touching code runnable headlessly
— that is irreducibly Revit-coupled in any language. What it does is move the
*surrounding* band of logic from untestable C# into **real, CI-tested CPython**
that reuses the engine's own models and schemas.

| Today (C# stub) | After (pyRevit / CPython) |
|---|---|
| `SpecManifestModels.cs`, `VerdictReportModels.cs` (DTOs) | **Deleted.** Reuse `ca_elevation_engine.models` + JSON schemas. |
| `EngineRunner.cs`, `EngineLocator.cs` | ~1 small real Python module: locate (Windows/POSIX branches, `EngineCommand` executable+prefix-args) + `subprocess` the `ca-elevation` CLI. Unit-tested both branches in CI; real `run` covered by the integration tier. |
| Ribbon assembly + `.addin` + signed installer | Real pyRevit `bundle.yaml` + folder layout. Complete, not stubbed. |
| Command orchestration (3 commands) | Real Python orchestration; testable except the live API calls. |
| Manifest *assembly* (raw values → manifest) | Real, CI-tested dict builders (device dicts **+** per-level floorplan records) that round-trip through `SpecManifest` and validate against the schema. |
| Verdict→colour mapping, which-elements logic | Real, CI-tested pure functions, with an exhaustiveness ratchet over `models.Verdict`. |

Estimated **~60–70%** of the current Revit stub surface becomes real, tested code.

## 2. What stays a live-Revit stub (irreducible)

These need a running Revit and can only be validated by Ed on a real install.
They are isolated into three small modules (`revit_*`) so everything around them
is real:

1. **Model walk** — `FilteredElementCollector` reading element params (location,
   mounting height, facing, family/type).
2. **View/floorplan export** — exporting the plan image and computing the
   pixel→model affine for each level.
3. **Graphic-override write-back** — colouring elements by verdict in the model.
   Must open a `Transaction` on the active doc and apply
   `OverrideGraphicSettings` per element per view; the active view / element
   selection comes from pyRevit's `revit`/`__revit__` globals. Must also
   **clear prior CA-Elevation overrides first** so a re-import is idempotent
   (the C# `VerdictWriteback.Clear` we retire did this — without it a second
   import leaves stale colours on devices dropped from the new report). Idempotent
   re-import is an explicit acceptance criterion for the live validation pass.

`script.py` pulls `doc`/`uidoc`/`selection` from pyRevit's context and injects
them into the `revit_extract` / `revit_export` / `revit_writeback` calls, keeping
the pure `lib` modules free of pyRevit globals (the stubs take a doc handle).

## 3. Runtime & version decisions (locked for this plan)

- **pyRevit CPython runtime** (`#! python3` shebang on each script). IronPython is
  *not* targeted (it cannot host the in-Revit code path we want, and can't load
  numpy anyway).
- **Engine runs out-of-process.** The extension never imports `numpy` / Open3D /
  the heavy pipeline inside Revit's process — it shells out to the `ca-elevation`
  CLI, which lives in its **own Python ≥3.10 venv**. This is what keeps both the
  engine testable and Revit's process free of fragile native wheels (the exact
  concern raised in the design doc).
- **Two Python version floors, on purpose:**
  - In-Revit extension code (`lib/`): target **Python 3.8+** (conservative, to
    match whatever CPython pyRevit bundles). Concretely: **pyRevit 4.8.x ships
    CPython 3.8; pyRevit 5.x ships CPython 3.12.** Recommended floor is **pyRevit
    4.8+ / CPython 3.8** as the `lib/` syntax target. This floor is **enforced
    executably, not by convention** (see below), because the engine's own ruff/
    mypy pins are `py310` and would silently *permit* 3.10-only constructs.
  - The engine (its own venv): stays **3.10+**, unchanged.
  - **Resolve Open item 1 (pyRevit/CPython floor) *before* building** — it sets
    the real syntax floor, and the whole point is to catch 3.10-only syntax
    before it reaches Ed's slow, hardware-gated Revit install.
- **Enforcing the 3.8 floor (executable, not asserted):**
  - `lib/` gets its **own** ruff/mypy config (`ruff target-version = "py38"`,
    `mypy python_version = "3.8"`) rather than inheriting the engine's `py310`.
    Add `from __future__ import annotations` to every `lib/` module so
    annotation-only PEP 604/585 forms are safe — but note this does **not**
    neutralise *runtime* 3.10 constructs (PEP 604 `X | Y` as a default/cast/
    `isinstance` arg, builtin generics in runtime-evaluated positions, `match`
    statements, `tomllib`); those are what the py38 lint floor catches.
  - CI runs the **pure `lib/` tests on Python 3.8 and 3.9 *without* installing
    the engine** (it is `requires-python>=3.10` and `numpy>=1.24` will refuse to
    install on 3.8). The engine-import round-trip tests are gated to the 3.10+
    jobs. See Section 6.
- **In-Revit footprint is stdlib + pythonnet + Revit API only.** The hard
  invariant: **`lib/` runtime modules import NO `ca_elevation_engine` module;
  engine imports live only under `tests/`.** (Even in tests, only
  `models`/`ingest` are numpy-free; `pipeline`/`register`/`geometry` pull numpy
  at import — so round-trip tests run on the 3.10+ matrix where numpy is
  installed.) Manifest *assembly* builds plain dicts. **Runtime validation is
  best-effort and engine-coupled:** `ca-elevation validate` only accepts file
  paths and runs *after* `bundle_io` has written the manifest + floorplan images
  to disk (it cannot validate an in-memory dict), and it also enforces
  cross-field rules — duplicate ids, dangling `level_id` — beyond raw schema. So
  if the engine is mis-located or absent the user gets no validation feedback
  until a full `run`; `engine_runner` must surface a clear "engine not found,
  cannot validate" state. **Builder correctness is guaranteed at test time** by
  importing the engine in CI and calling `SpecManifest.from_dict` + schema
  validate (Section 7 tier 1) — a *different* mechanism from runtime `validate`.

## 4. Proposed file layout

```
pyrevit-extension/
├─ README.md                         # install via pyRevit, CPython requirement, dev/test
├─ CaElevationReview.extension/
│  ├─ CaElevationReview.tab/
│  │  └─ Verify.panel/
│  │     ├─ ExportBundle.pushbutton/
│  │     │  ├─ bundle.yaml           # title, tooltip, author
│  │     │  ├─ script.py             # "#! python3" — thin entry → lib
│  │     │  └─ icon.png              # (placeholder; real icon later)
│  │     ├─ ImportCaptures.pushbutton/
│  │     │  ├─ bundle.yaml
│  │     │  ├─ script.py
│  │     │  └─ icon.png
│  │     └─ OpenReport.pushbutton/
│  │        ├─ bundle.yaml
│  │        ├─ script.py
│  │        └─ icon.png
│  └─ lib/
│     └─ ca_elevation_revit/         # the importable, testable library (the real product)
│        ├─ __init__.py
│        ├─ config.py                # engine path resolution, defaults, settings
│        ├─ manifest_builder.py      # REAL: raw extracted values → manifest dict
│        ├─ bundle_io.py             # REAL: write field-bundle dir / read capture package
│        ├─ engine_runner.py         # REAL: locate + subprocess the ca-elevation CLI
│        ├─ writeback.py             # REAL: verdict → override-colour mapping, element grouping
│        ├─ revit_extract.py         # STUB: the live FilteredElementCollector walk
│        ├─ revit_export.py          # STUB: live view/floorplan export + transform
│        └─ revit_writeback.py       # STUB: live graphic-override application
└─ tests/                            # run in normal CPython CI — NO Revit, NO pyRevit
   ├─ pyproject.toml / mypy.ini      # lib-only ruff (target py38) + mypy (py3.8, ignore_missing_imports)
   ├─ conftest.py
   ├─ test_manifest_builder.py       # builds a manifest WITH floorplan records, asserts SpecManifest.from_dict + schema-valid
   ├─ test_bundle_io.py              # field-bundle write / capture read round-trips
   ├─ test_engine_runner.py          # arg-building + locator order, both OS branches (mock subprocess) — UNIT
   ├─ test_writeback.py              # verdict→colour mapping, grouping, exhaustiveness ratchet
   └─ test_integration.py            # INTEGRATION: drives the real `ca-elevation run` over a repo-relative fixture (3.10+ jobs only)
```

The lib-only ruff/mypy config sets `target-version = "py38"` / `python_version =
"3.8"` (not the engine's `py310`) and `ignore_missing_imports = true` (mirroring
`engine/pyproject.toml`) so mypy does not fail on the unresolvable
`Autodesk.Revit.DB` / `pyrevit` imports in the three `revit_*` stubs — the
function-local-import trick keeps them runtime-importable but static analysis sees
them regardless of nesting.

**Integration fixture source.** `test_integration.py` reaches the existing engine
fixtures (`engine/fixtures/synthetic/f01_office.{manifest,capture}.json`) by a
**repo-relative path** — *not* `importlib.resources`: pip-installing the engine
does **not** install `engine/fixtures/` (they are outside the package, not in
`package-data`, which only ships `schemas/`, `report/templates/`, `py.typed`).
The test invokes `ca-elevation run` over them and asserts `verdict_report.json`
parses.

### The seam, file by file

- **`script.py` (×3)** — thin: pull `doc`/`uidoc`/`selection` from pyRevit's
  context, call one `lib` function, show progress/result via pyRevit `forms`.
  ~15 lines each. The `#! python3` shebang **MUST be the literal first line**
  (no BOM, no license header or `# -*- coding -*-` above it) or pyRevit silently
  falls back to IronPython, where `subprocess`/stdlib behave differently. pyRevit
  reads the shebang **per script**, so all three need it independently. (pyRevit
  also supports an `engine:` key in `bundle.yaml`; the shebang is the mechanism
  we use here.)
- **Floorplan data-flow (the affine hand-off).** The schema *requires* per level
  a `floorplan` with `image`, `width_px`, `height_px`, and a 6-element
  `pixel_to_model` affine — and these originate in the live export, not device
  values. The hand-off, made explicit so three modules don't hand-wave it:
  `revit_export` returns, per level, a record `(image_bytes_or_path, width_px,
  height_px, pixel_to_model[6])` — it both **computes** the affine (from the
  exported view crop box / scale) and carries the dimensions. `manifest_builder`
  takes **both** the device dicts **and** these per-level floorplan records as
  input. `bundle_io` writes the images to disk and writes the manifest
  referencing **relative** image paths. (A device-only manifest is schema-INVALID
  — `required: levels[].floorplan` — so the round-trip test fixture must include
  floorplan records.)
- **`manifest_builder.py`** — pure. Input: a list of plain device dicts (from
  `revit_extract`) **and** the per-level floorplan records (from `revit_export`).
  Output: a manifest dict matching `spec_manifest.schema.json`. No Revit imports.
  Stamps `default_tolerances` explicitly — **carry over the C# extractor values
  `position=0.25, mounting_height=0.083, orientation=10.0`** (these differ from
  the engine's own fallback `0.083/0.042/10.0`, applied only when a manifest
  omits them; a literal port that drops them would silently change verdict
  thresholds vs the C# front door). Pin the chosen values as a golden in the
  test. **Fully tested** (round-trip includes floorplan records, so the assertion
  exercises a schema-valid manifest).
- **`bundle_io.py`** — pure stdlib. Assemble the field-bundle directory (manifest
  JSON + floorplan images written to disk, manifest referencing relative paths),
  and read back the returned capture package. **Tested.**
- **`engine_runner.py`** — locate the `ca-elevation` CLI (explicit path → env var
  → bundled venv → PATH, ported from the C# `EngineLocator` order), then
  `subprocess.run` and read the report. Port details that are part of the
  contract:
  - Mirror the C# `EngineCommand` (executable + prefix-args), replicating
    `Wrap()`: a resolved **python interpreter** → `['-m',
    'ca_elevation_engine.cli']`, else treat the path as a console script
    directly. Keep the explicit/env "configured-but-missing **throws**" vs "PATH
    fallback returned **unprobed**" semantics.
  - Build bundled-venv paths from `os.name` / `sys.platform`, **not** hardcoded
    separators: `engine-venv/Scripts/ca-elevation.exe` (+ `Scripts/python.exe`)
    on Windows, `engine-venv/bin/ca-elevation` on POSIX. Revit (and thus real
    execution) is **Windows-only**, but CI is ubuntu — so the existence-probe and
    OS detection are **injected/mocked** and the test covers **both** branches on
    ubuntu. Real on-OS invocation is Ed-gated; these unit tests are the *only*
    automated guard for the locator, so they must assert the chosen executable
    **and** prefix args, not just the run flags.
  - Run contract: invoke `run --manifest … --capture … --out … --format pdf`,
    then **read `OUT/verdict_report.json` from disk** (always written) — do **not**
    scrape stdout. The CLI prints the text summary to **stdout** and
    `warning:`/`wrote …:` lines to **stderr** (stdout is non-contractual). With
    `--format pdf`, if `reportlab` is absent the engine **silently falls back to
    HTML** and `report.pdf` will not exist — so `OpenReport` / the runner must
    glob `report.pdf|report.html` (or check the result), not hard-assume
    `report.pdf`. Map exit codes: **0** success, **1** validation/usage error,
    **2** unexpected crash — surface stderr to pyRevit `forms` and distinguish
    1 (validation) from 2 (crash). **Unit-tested** with a mocked subprocess
    (both locator branches); the **real** `run` is exercised by
    `test_integration.py`.
- **`writeback.py`** — pure. Map verdict → override colour
  (pass→green / flag→orange / absent→red / type_mismatch→purple), group device
  results by element id for application. **Tested**, including an **exhaustiveness
  ratchet** asserting `set(MAPPING) == set(ca_elevation_engine.models.Verdict)`
  (the lib already imports the engine in tests) — the same drift-guard pattern as
  `engine/tests/test_registry.py::test_registry_verdicts_match_enum`, so adding a
  fifth verdict to the engine forces the mapping to cover it.
- **`revit_extract.py` / `revit_export.py` / `revit_writeback.py`** — the *only*
  modules that do `from Autodesk.Revit.DB import …` (inside functions, so the
  module still imports in CI). Each function is small and marked
  `# LIVE: requires Revit`. These are Ed's to validate.

## 5. Engine contract (unchanged)

The extension uses the existing, stable CLI surface — no engine changes:

```
ca-elevation run      --manifest M --capture C --out DIR --format pdf
ca-elevation validate --manifest M [--capture C]
```

`run` **always** writes `DIR/verdict_report.json`; the rendered report is
`report.pdf` **unless** `reportlab` is missing, in which case it falls back to
`report.html` with a warning. `engine_runner` orchestrates it, reads the JSON back
from disk for write-back, and discovers the rendered report by glob rather than
assuming `report.pdf`.

## 6. CI, pre-commit, docs changes

- **New workflow `pyrevit-extension.yml`**, `paths`-filtered to
  `[pyrevit-extension/**, .github/workflows/pyrevit-extension.yml]` (matching the
  existing four workflows) so it triggers only on relevant changes. Two job
  groups, on **ubuntu**:
  - **Floor jobs — Python 3.8 + 3.9:** run the **pure `lib/` tests only**
    (manifest_builder / bundle_io / writeback / engine_runner-mocked) and `ruff`
    (`target-version=py38`) + `mypy` over `lib/ca_elevation_revit`. These **do
    NOT install the engine** (`requires-python>=3.10`, `numpy>=1.24` won't install
    on 3.8). This is what makes the 3.8 syntax floor *executable* rather than
    asserted.
  - **Engine jobs — Python 3.10/3.11/3.12:** install the engine (`pip install
    ./engine`, with pip caching to keep the numpy build fast) and run the
    engine-importing round-trip tests + `test_integration.py`. Use
    `pip install ./engine[report]` for the jobs whose integration assertions
    depend on PDF output; otherwise the `--format pdf` → HTML fallback changes
    what the test sees, so decide and pin the expectation (the integration test
    should assert the chosen output file actually *exists*, e.g. via glob).
  - Unlike the dead C# job, this **actually runs** — but "**blocks**" also
    requires adding `pyrevit-extension (py3.x)` to the repo's **required status
    checks in branch protection** (a GitHub setting outside the YAML). Without
    that step, "blocks" is aspirational.
- **Pre-commit** — extend ruff/mypy/pytest scope to the new lib (lib config at
  the py38 floor); drop the `dotnet format` hook (or keep, gated, only if the C#
  tree is retained).
- **Docs** — update `docs/architecture.md` and root `README.md`: front door is a
  pyRevit extension; note pyRevit becomes a **user prerequisite** and the
  distribution implication (the design.md signed-standalone-installer path is
  abandoned — see Section 8); live Revit tests stay gated/manual.
- **Retire `revit-addin/` — gated, not a coin-flip.** Keep it for one cycle,
  CI-gated off, until Ed's live-Revit validation pass (step 6) is green, then
  delete in a follow-up. Rationale: it is the **only** artifact preserving the
  signed-installer / commercial-tier optionality from design.md, and the live
  `revit_*` modules are validated only on Ed's hardware *after* a possible
  delete — so deleting first risks "C# gone → live validation fails → nothing to
  fall back to." The verdict-colour semantics and CLI contract carry over.

## 7. Testing tiers (how the win shows up)

| Tier | Where | Runs in CI? |
|---|---|---|
| Syntax floor — pure `lib/` import-smoke + ruff(py38)/mypy, **no engine** | CPython **3.8/3.9**, ubuntu | **Yes — enforces the 3.8 floor** |
| Headless unit — `lib/` round-trip via `SpecManifest.from_dict` + schema validate | CPython **3.10+**, imports engine | **Yes — the new gain** |
| Integration — extension drives the real `ca-elevation` CLI over the engine's repo-relative fixture | CPython 3.10+, CI | Yes (engine installed; `[report]` extra if asserting PDF) |
| Live — `revit_extract` / `revit_export` / `revit_writeback` inside Revit | Ed's Revit install | No — gated/manual |

The two CI tiers are *different mechanisms*: the headless tier proves builder
correctness in-process (`from_dict` + `_validate`, which also enforces cross-field
rules); the integration tier proves the real subprocess seam (locate → `run` →
read `verdict_report.json` from `--out`).

## 8. Distribution / product note (the trade-off to accept)

The design doc deliberately chose standalone C# so users would **not** need
pyRevit first, and because "a signed .NET add-in with a real installer is how a
commercial Revit product ships." This pivot makes **pyRevit a prerequisite** and
changes the distribution story to "install via pyRevit's extension manager /
clone URL / drop into the extensions dir." Four points for a conscious sign-off:

- **Licensing (the most understated item).** pyRevit is **GPL3**; our extension
  and engine stay **Apache-2.0** and are **not a derivative work of pyRevit** —
  the extension scripts run *on* the host runtime, and the engine is a separate
  **out-of-process** CLI (the FSF treats a subprocess/CLI-boundary plugin as a
  borderline-but-generally-non-derivative case; a pyRevit *extension* is likewise
  not a derivative of pyRevit). So the OSS license is unaffected. The real cost
  is that any **paid/commercial tier now sits on top of a GPL3 prerequisite** the
  user installs separately — the conscious trade against design.md's "commercial
  Revit product ships signed" rationale.
- **The "signed installer" was never built.** The current C# install story is
  *manual* (per `revit-addin/README.md`: copy `CaElevationReview.addin` into the
  `Addins/<year>\` dir, edit its `<Assembly>` path, replace the placeholder
  `<AddInId>` GUID once before release). There is no installer, no code signing,
  no produced engine venv. So we are **abandoning the design.md
  signed-standalone-installer path as a future option**, not losing a built
  capability — don't over-weight it as a regression. The one real loss: the C#
  path at least left that door *open*; you cannot wrap a "pyRevit-required" tool
  in the clean signed MSI design.md envisioned, so pyRevit closes it.
- **End-user onboarding friction (the substantive product cost, not just
  "polish").** Setup goes from "one installer" (aspirational) to "install pyRevit
  — the correct version for your Revit year, itself a multi-step install with its
  own compatibility matrix — **plus** provision the engine venv (Open item 4)
  **plus** drop in the extension." design.md's first stated reason for C# (line
  81) was exactly that paying/free users would not have to install pyRevit first.
- **Scope: desktop-only.** This pivot does **not** touch the iPhone capture app's
  App Store / Apple-IAP path (design.md Monetization, lines 264–293) — Revit
  add-ins ship on Windows and never go through any Apple store. The only
  monetization impact is on the desktop front door, where the paid/signed-tier
  story becomes harder.

## 9. Migration steps (when approved)

1. Scaffold `pyrevit-extension/` tree (layout above), engine untouched.
2. Implement the four real `lib` modules + their unit tests; get them green in CI.
3. Stub the three `revit_*` modules with `# LIVE` markers and clear TODOs.
4. Wire the three `script.py` entries + `bundle.yaml` + placeholder icons.
5. Add `pyrevit-extension.yml` (floor + engine job groups, path filter, branch-
   protection required check); update pre-commit + docs. **Keep `revit-addin/`**
   CI-gated off.
6. Hand Ed a checklist for the live-Revit validation pass — including the
   **idempotent re-import** criterion (writeback clears prior overrides first).
7. **Only after step 6 is green:** retire `revit-addin/` in a follow-up. "Delete
   C#" must not precede live sign-off (Section 6 rationale).

## 10. Rough effort

- Real lib + tests + ribbon + CI + docs: **~1 focused session** (most of it
  genuinely runnable and verified here).
- Live `revit_*` fill-in + on-Revit validation: **Ed-gated**, separate, hardware-bound.

## Open items to confirm before building

1. **pyRevit version floor** (and therefore the bundled CPython the `lib/` code
   must support). **Resolve before building** — it sets the lint floor.
   *Recommendation:* pyRevit 4.8+ / CPython 3.8 as the `lib/` syntax target
   (4.8.x → 3.8; 5.x → 3.12).
2. **C# add-in: keep one cycle, then remove.** *Recommendation:* keep
   `revit-addin/` CI-gated off (it preserves the signed-installer / commercial-
   tier optionality from design.md), delete once pyRevit-as-prerequisite is
   validated with real users and Ed's live pass is green. Tied to the
   monetization trade (Section 8), not a coin-flip.
3. **Icons** — placeholder now, real artwork later.
4. **Settings storage** — where the engine path / venv location is configured
   (pyRevit config vs a repo-level settings file). Couples to the runtime-
   validation UX (Section 3): a mis-located engine means no validation until a
   full `run`.
