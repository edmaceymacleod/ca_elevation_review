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
   mounting height, facing, family/type). **Identity invariant:** `revit_extract`
   MUST stamp the Revit **`UniqueId`** (the stable GUID-like string), **not the
   `ElementId`** (an int, not stable across sessions/files), as `device.id`. The
   write-back round-trip depends on this: `revit_writeback` resolves elements via
   `doc.GetElement(uniqueId: str)`, a different overload from
   `doc.GetElement(ElementId)`. The engine treats `device_id` as an opaque string
   and echoes it from manifest to report unchanged, and the schema example text
   says "e.g. Revit ElementId or UniqueId" — so stamping the wrong one passes
   **every** CI test (ids are just strings) yet silently resolves nothing (or the
   wrong element) at live write-back. The C# `Apply()` only works because
   `device_id == UniqueId` (`VerdictWriteback.cs`). This is a **live-validation
   acceptance criterion** alongside idempotent re-import (step 6); `manifest_builder`
   should also assert ids are non-empty strings as a cheap guard.
2. **View/floorplan export** — exporting the plan image and computing the
   pixel→model affine for each level.
3. **Graphic-override write-back** — colouring elements by verdict in the model.
   Must open a `Transaction` on the active doc and apply
   `OverrideGraphicSettings` per element per view; the active view / element
   selection comes from pyRevit's `revit`/`__revit__` globals. Revit API access
   here is via **pythonnet** (the CLR bridge the CPython engine uses), so the
   stub body is pythonnet-idiom code — CLR enum access, generic-method
   invocation (`FilteredElementCollector.OfClass`), `ref`/`out` handling — **not**
   "the same C# calls in Python." This is the single biggest live-validation
   surprise surface.
   Must also be **idempotent on re-import**, and this is **genuinely new logic,
   not a port**: the C# `VerdictWriteback.Clear` exists but was **never wired**
   (`ImportCapturesCommand` calls `WriteBackVerdicts` and never `Clear`), and even
   if it had been, it takes a `deviceIds` set — the only id set available at
   import time is the *new* report's device ids, which by definition does **not**
   contain a device dropped from the new report. So clearing by the new report's
   ids cannot remove stale colours on dropped devices. The correct mechanism:
   clear by the **previously applied** override set, **before** applying the new
   report. **Chosen mechanism (no persistence): enumerate-and-reset by marker.**
   `revit_writeback`, when it applies an override, also stamps a CA-Elevation
   **marker** (a project parameter / shared-parameter flag, or a named element
   set) on each overridden element. On re-import it first enumerates all elements
   in the active view carrying that marker and resets their `OverrideGraphicSettings`
   + clears the marker, then applies the new report and re-stamps. This avoids a
   persisted prior-override store (extensible storage with its own schema GUID and
   its own stale/partial-set failure modes) entirely — the model itself is the
   record. `revit_writeback.py` therefore owns **both** application and
   marker-based clearing (Section 4). Idempotent re-import (including the
   drop-a-device case) is an explicit acceptance criterion for the live validation
   pass.

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
    match whatever CPython pyRevit bundles). Concretely: **pyRevit 4.8.x bundles
    CPython 3.8; pyRevit 5.x bundles CPython 3.11** (the 5.x cpython-version
    threads confirm 3.11, not 3.12 — no 5.x release ships a 3.12 engine). The
    current shipping line is already **6.x**; verify its bundled CPython against
    the target release's `bin/cengines` rather than assuming. The plan is
    **scoped to a pinned pyRevit release** (Open item 1) — the floor recommendation
    stands regardless: **CPython 3.8** as the `lib/` syntax target, since that is
    the oldest engine we may land on. This floor is **enforced executably, not by
    convention** (see below), because the engine's own ruff/mypy pins are `py310`
    and would silently *permit* 3.10-only constructs.
    **The 3.8 floor is a syntax/lint target, not the runtime.** The actual runtime
    is whatever the pinned pyRevit release bundles — almost certainly *newer* than
    3.8 (5.x/6.x lines bundle 3.11; the host in this environment is CPython 3.11).
    The py38/py39 floor jobs are a guard against accidental 3.10-only syntax, **not**
    proof "we run on 3.8." pyRevit has **no runtime CPython-version gate** (there is
    no `bundle.yaml` min-engine-version key — see Section 4); the only runtime floor
    we can enforce is the `script.py` code guard (`sys.version_info` check), and the
    only build-time floor is this CI lint matrix.
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
    statements, `tomllib`); those are what the py38 lint floor catches. One subtler
    case ruff/mypy will **not** reliably flag: with the future import, dataclass
    field annotations are stored as strings and are safe — but a runtime
    `get_type_hints()` / `dataclasses.fields()` + hint re-evaluation on a lib
    dataclass whose field is `X | None` **raises on 3.8/3.9**. That is caught only
    by actually *importing and exercising* every `lib/` module on the floor jobs
    (the import-smoke requirement in Section 6), not by static analysis.
  - CI runs the **pure `lib/` tests on Python 3.8 and 3.9 *without* installing
    the engine.** The hard gate is the engine's own **`requires-python = ">=3.10"`**
    (`engine/pyproject.toml`): `pip install ./engine` errors on 3.8/3.9 before any
    dependency resolution. (Note `numpy>=1.24` alone is *not* the blocker — numpy
    shipped cp38 wheels through 1.24 and dropped 3.8 only at 1.25; `requires-python`
    is the reliable gate.) The engine-import round-trip tests are gated to the
    3.10+ jobs. See Section 6.
- **In-Revit footprint:** the `lib/` **runtime** modules (`config`,
  `manifest_builder`, `bundle_io`, `engine_runner`, `writeback`) need **stdlib
  only** (`subprocess`, `json`, `pathlib`, `os`, `sys`). The three `revit_*` stubs
  additionally touch the **Revit API / pyRevit globals via pythonnet** — both
  provided by the pyRevit CPython host; **nothing is pip-installed into Revit's
  process** (pythonnet is not vendored or pinned). This keeps the "no native
  wheels in Revit" argument clean. The hard invariant: **`lib/` runtime modules
  import NO `ca_elevation_engine` module; engine imports live only under
  `tests/`.** (Even in tests, only `models`/`ingest` are numpy-free;
  `pipeline`/`register`/`geometry` pull numpy at import — so round-trip tests run
  on the 3.10+ matrix where numpy is installed.) Manifest *assembly* builds plain
  dicts. **Runtime validation is best-effort and engine-coupled:** `ca-elevation
  validate` accepts file paths only, so `bundle_io` must write the **manifest
  JSON** to disk first (it cannot validate an in-memory dict); the **floorplan
  images need not exist** for validate to pass — the schema treats
  `floorplan.image` as a plain string path and `ingest` never opens or `stat`s it
  (a missing image surfaces only later, in register/render). The manifest-internal
  checks it adds beyond raw schema are **duplicate ids and dangling `level_id`**
  (`_check_manifest_internal`); the **project-id mismatch and shot-targets-unknown
  -level** checks live in `check_compatible`, which validate runs **only when
  `--capture` is passed** — manifest-only validate cannot catch them. So if the
  engine is mis-located or absent the user gets no validation feedback until a full
  `run`; `engine_runner` must surface a clear "engine not found, cannot validate"
  state. **Builder correctness is guaranteed at test time** by importing the engine
  in CI and calling `SpecManifest.from_dict` + schema validate (Section 7 tier 1)
  — a *different* mechanism from runtime `validate`.

## 4. Proposed file layout

```
pyrevit-extension/
├─ README.md                         # install via pyRevit, CPython requirement, dev/test
├─ CaElevationReview.extension/
│  ├─ CaElevationReview.tab/
│  │  └─ Verify.panel/
│  │     ├─ ExportBundle.pushbutton/
│  │     │  ├─ bundle.yaml           # title, tooltip, author, engine block (no version floor)
│  │     │  ├─ script.py             # "#! python3" — thin entry → lib
│  │     │  └─ icon.png              # placeholder; missing degrades to default. icon.dark.png variant later
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
│        └─ revit_writeback.py       # STUB: live graphic-override application + marker-based clear of prior overrides
└─ tests/                            # run in normal CPython CI — NO Revit, NO pyRevit
   ├─ pyproject.toml / mypy.ini      # lib-only ruff (target py38) + mypy (py3.8, ignore_missing_imports); pytest pythonpath → ../lib
   ├─ conftest.py
   ├─ test_manifest_builder.py       # ENGINE (3.10+): from_dict + schema-valid round-trip, WITH floorplan records
   ├─ test_bundle_io.py              # FLOOR: field-bundle write / capture read round-trips (stdlib only)
   ├─ test_engine_runner.py          # FLOOR: arg-building + locator order, both OS branches (mock subprocess) — UNIT
   ├─ test_writeback.py              # FLOOR: verdict→colour mapping + grouping (no engine import)
   ├─ test_writeback_ratchet.py      # ENGINE (3.10+): exhaustiveness ratchet over models.Verdict
   └─ test_integration.py            # INTEGRATION (3.10+): real `ca-elevation run` over a repo-relative fixture; exit-0 AND exit-1 cases
```

The lib-only ruff/mypy config sets `target-version = "py38"` / `python_version =
"3.8"` (not the engine's `py310`), `ignore_missing_imports = true` **and
`warn_unused_ignores = true`** (mirroring `engine/pyproject.toml` in full — the
latter so stale `# type: ignore` comments around the function-local Revit imports
get flagged rather than silently accumulating). `ignore_missing_imports` keeps
mypy from failing on the unresolvable `Autodesk.Revit.DB` / `pyrevit` imports in
the three `revit_*` stubs — the function-local-import trick keeps them
runtime-importable but static analysis sees them regardless of nesting.

**Importability in CI (the load-bearing mechanism).** The lib lives at
`CaElevationReview.extension/lib/ca_elevation_revit/` — not a pip-installable
package (no pyproject for the lib, no `setuptools` pointing at the nested `lib/`).
In real pyRevit the loader puts `lib/` on `sys.path`; in CI **nothing does**
unless we say so. Concrete mechanism: `tests/pyproject.toml` declares
`[tool.pytest.ini_options] pythonpath = ["../CaElevationReview.extension/lib"]`
(pytest 7+), so pytest puts the lib dir on `sys.path` and `import
ca_elevation_revit` resolves. This is what makes "lib tests / import-smoke run in
CI" true — without it the import-smoke that enforces the floor cannot even
collect. (A `conftest.py` `sys.path` insert is an equivalent fallback.)

**`lib/` holds exactly one top-level package (`ca_elevation_revit`).** When the
CPython engine runs, pyRevit puts its own site/bin paths **and every installed
extension's `lib/`** on `sys.path` simultaneously, so top-level module names share
a flat namespace across all extensions. So: the three `script.py` files import
**through the package** (`from ca_elevation_revit import engine_runner`, not bare
`import engine_runner`), and the helpers listed below as bare filenames
(`config.py`, `writeback.py`, …) are safe **only because they live inside the
package directory** — never add a generically-named top-level module to `lib/`.

**Integration fixture source.** `test_integration.py` reaches the existing engine
fixtures (`engine/fixtures/synthetic/f01_office.{manifest,capture}.json`) by a
**repo-relative path** — *not* `importlib.resources`: pip-installing the engine
does **not** install `engine/fixtures/` (they are outside the package, not in
`package-data`, which only ships `schemas/`, `report/templates/`, `py.typed`).
The test invokes `ca-elevation run` over them and asserts `verdict_report.json`
parses.

**Schema-gating scope.** The repo's standalone validator
(`engine/tools/validate_schemas.py` + `schema-validation.yml` + the pre-commit
hook) only discovers fixtures under `engine/fixtures/`. The borrowed engine
fixture above **is** covered; any payload the pyrevit tests construct in-test
(the `manifest_builder` round-trip dict) is **not** seen by it. That is acceptable
— the lib's own `from_dict` + `_validate` is the schema gate for lib-side payloads.
Note this explicitly so the design-principle-#3 "malformed payload fails the build"
guarantee is understood to be **lib-test-local** here, not enforced by the repo
validator. (If a pyrevit-side *fixture file* is later added, point
`validate_schemas.py` at `pyrevit-extension/tests/fixtures` and add it to the
workflow + pre-commit `files` regex.)

### The seam, file by file

- **`script.py` (×3)** — thin: pull `doc`/`uidoc`/`selection` from pyRevit's
  context, call one `lib` function, show progress/result via pyRevit `forms`.
  ~15 lines each. **Engine selection — necessary but, on some releases, not
  sufficient:**
  - Put the `#! python3` shebang at the top of each script so pyRevit's loader
    selects the CPython engine. The directive is parsed per script (all three need
    it), and the loader tokenizes for it rather than demanding the literal first
    byte — but keep the shebang as the **first line** anyway (avoid a BOM or
    header above it) since that is the unambiguous form; verify against the loader
    rather than asserting a hard "first-byte-or-IronPython" rule.
  - **There is no bundle.yaml CPython-version floor.** A `version:` key under
    `engine:` is **silently ignored** — pyRevit's `engine` metadata block supports
    only `clean` / `full_frame` / `persistent` / `mainthread` (plus Dynamo keys);
    the only version-gating metadata is `min_revit_version` / `max_revit_version`,
    which gate the **Revit year**, not the bundled CPython engine. There is **no**
    metadata mechanism that refuses to run a script on a CPython older than X. So
    the **only** enforcement of the 3.8 floor is the **CI py38 lint/test matrix**
    (Section 6) — that, not bundle.yaml, is the real guard. Keep `clean` in the
    engine block only if its actual semantics are wanted (it is an IronPython
    scope-cleanup concept, largely inert under CPython). Button title/tooltip/
    author may live either in `bundle.yaml` (chosen here, single-source) or as
    top-of-script variables; `bundle.yaml` is the deliberate choice.
  - **The in-Revit floor enforcer is a code guard, not metadata.** There is a known
    **6.0.0 routing defect** (pyRevit issue #3092) where correctly-shebanged CPython
    scripts run under **IronPython anyway**. Since this plan's entire correctness
    argument rests on CPython being selected, add a **runtime guard at the top of
    each `script.py`** that checks both the implementation **and** the version
    floor: `if sys.implementation.name != 'cpython' or sys.version_info < (3, 8):
    forms.alert(...); script.exit()` — so a mis-route **or** an unexpectedly-old
    engine fails loudly instead of silently hitting stdlib/`subprocess`
    differences. This code guard, in code where it can actually run, is the
    in-Revit counterpart to the CI floor (bundle.yaml cannot do it). Pin/test
    against a pyRevit release not affected by #3092, and make this a validation
    checkpoint for Ed.
- **Floorplan data-flow (the affine hand-off).** The schema *requires* per level
  a `floorplan` with `image`, `width_px`, `height_px`, and a 6-element
  `pixel_to_model` affine — and these originate in the live export, not device
  values. The hand-off, made explicit so three modules don't hand-wave it:
  `revit_export` returns, per level, a record `(image_bytes, basename, width_px,
  height_px, pixel_to_model[6])` — in-memory **bytes** plus a **stable basename**
  (resolve the `bytes`-vs-`path` either/or to bytes+basename, so there is no
  ambiguity about who owns the file). It both **computes** the affine (from the
  exported view crop box / scale) and carries the dimensions. **One place owns the
  relative path:** `manifest_builder` takes the basenames and writes
  `floorplan.image` as exactly that relative basename; `bundle_io` is the **sole
  writer** and writes each image at exactly that relative path. The dict and the
  on-disk layout therefore cannot diverge — important because `ingest` never
  `stat`s the image, so a manifest referencing a path that does not exist surfaces
  only late, at register/render. (A device-only manifest is schema-INVALID —
  `required: levels[].floorplan` — so the round-trip test fixture must include
  floorplan records.)
- **`manifest_builder.py`** — pure. Input: a list of plain device dicts (from
  `revit_extract`) **and** the per-level floorplan records (from `revit_export`);
  it writes `floorplan.image` as the record's **relative basename** (the single
  place the relative path is decided). Output: a manifest dict matching
  `spec_manifest.schema.json`. No Revit imports.
  Stamps `default_tolerances` explicitly — **carry over the C# extractor values
  `position=0.25, mounting_height=0.083, orientation=10.0`** (these differ from
  the engine's own fallback `0.083/0.042/10.0`, applied only when a manifest
  omits them; a literal port that drops them would silently change verdict
  thresholds vs the C# front door). Pin the chosen values as a golden in the
  test. **Fully tested** — but the round-trip assertion (`SpecManifest.from_dict`
  + schema validate, with floorplan records) **imports the engine**, so it is
  gated to the **3.10+ engine jobs**, not the floor jobs (same discipline as the
  writeback ratchet).
- **`bundle_io.py`** — pure stdlib. The **sole writer** of the field-bundle
  directory: writes the manifest JSON and writes each floorplan image's bytes at
  exactly the relative basename `manifest_builder` stamped (so dict and disk cannot
  diverge), and reads back the returned capture package. **Tested.**
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
    (both locator branches). The exit-code contract is reachable end-to-end only
    via the real subprocess, so `test_integration.py` must drive **two** real
    cases: the known-good fixture (exit 0), **and** a deliberately missing/
    schema-invalid manifest that asserts the runner reports a **validation
    (exit-1) failure with stderr surfaced** — the mocked unit tests alone never
    prove the runner surfaces a real non-zero exit. **exit-2 (crash) is not
    drivable over a fixture deterministically**, so the 1-vs-2 discrimination is
    covered by a **mocked unit test** (feed `engine_runner` a subprocess returning
    `rc=2`, assert it surfaces as "crash"), **not** by the integration tier — state
    this rather than implying the exit-code contract is fully integration-covered.
- **`writeback.py`** — pure. Map verdict → override colour
  (pass→green / flag→orange / absent→red / type_mismatch→purple; **unknown →
  sentinel magenta + logged warning, never `KeyError`**), group device results by
  element id for application. **The verdict→colour and grouping cases
  import no engine and run on the 3.8/3.9 floor jobs.** The **exhaustiveness
  ratchet** — `set(MAPPING) == set(ca_elevation_engine.models.Verdict)` — imports
  the engine, so it **cannot** sit in the floor bucket: on a 3.8/3.9 job with the
  engine uninstalled it would `ModuleNotFoundError` at collection and error the
  whole module. Put it in a **separate test** (`test_writeback_ratchet.py`) gated
  by the `@pytest.mark.engine` marker / `skipif sys.version_info < (3, 10)` so it
  runs only on the 3.10+ engine jobs. **Do not** gate it with
  `pytest.importorskip('ca_elevation_engine')`: on the engine jobs the engine is a
  **hard import** (Section 6) — importorskip would silently *skip* this gate if a
  `pip install` regressed, converting an install failure into a false pass; the
  version marker is the right primitive, reserved for keeping the test off the floor
  jobs. It is the same drift-guard pattern as
  `engine/tests/test_registry.py::test_registry_verdicts_match_enum`, **but not at
  parity with it**: `test_registry` lives next to the enum and runs on every engine
  change; this lib ratchet runs only on the **pyrevit-extension** workflow's 3.10+
  jobs, and a verdict added under `engine/` triggers `engine.yml`, **not**
  `pyrevit-extension.yml` (path-filtered to `pyrevit-extension/**`) — so it can go
  stale silently until something under `pyrevit-extension/` also changes.
  **Decision (Section 6): the lib ratchet is best-effort; `test_registry` stays the
  authoritative enum-completeness gate.** Because that leaves a window where the
  lib `MAPPING` can ship stale, `writeback.py` **must be raise-safe on an unmapped
  verdict**: an unknown verdict maps to a loud **sentinel colour** (e.g. magenta)
  and logs a warning, **never** `KeyError`s — a `KeyError` here would land inside a
  Revit transaction on Ed's hardware, the worst place to discover a gap. The
  ratchet then degrades from a hard gate to a fail-soft visual signal. (Not at
  parity with `test_registry`, which lives next to the enum and runs on every
  engine change — do not imply parity.)
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
  - **Floor jobs — Python 3.8 + 3.9:** run only the **engine-free** `lib/` tests
    plus `ruff` (`target-version=py38`) + `mypy` over `lib/ca_elevation_revit`.
    These **do NOT install the engine** (the hard gate is the engine's
    `requires-python>=3.10`; `pip install ./engine` errors before dependency
    resolution). This is what makes the 3.8 syntax floor *executable* rather than
    asserted. **Pin the floor toolchain to 3.8-compatible versions** — engine's
    pins (`pytest>=7.4`, `mypy>=1.8`, `ruff>=0.4`) are floors, not ceilings, and a
    fresh resolve on a 3.8 runner can pull a pytest/ruff/mypy that itself requires
    3.9+. Ship a capped `tests/requirements-floor.txt` so the floor job's
    toolchain is reproducibly executable. **The split is per-assertion, not
    per-file**, and must be mechanical so a new engine-importing assertion cannot
    accidentally land in the floor set:
    - **Floor (3.8/3.9):** `bundle_io` round-trips; `engine_runner` locator/arg
      tests (mocked subprocess, no engine import); `writeback`'s verdict→colour
      mapping + grouping; `lib/` import-smoke — which must **import (execute) every
      `lib/` module**, since that is what catches a runtime PEP 604 re-evaluation
      (a `get_type_hints()`/`dataclasses.fields()` call on a lib dataclass with an
      `X | None` annotation) that ruff/mypy alone will not flag. Import-smoke
      **imports modules only**; it never invokes the live `revit_*` functions
      (their function-local `from Autodesk.Revit.DB import …` would `ImportError`).
    - **Engine-only (3.10+, marked `@pytest.mark.engine` / `skipif
      sys.version_info < (3,10)`):** `manifest_builder`'s `SpecManifest.from_dict`
      + schema-validate round-trip, and `writeback`'s `Verdict` exhaustiveness
      ratchet (`test_writeback_ratchet.py`). Both import `ca_elevation_engine` and
      would `ModuleNotFoundError` at collection on the floor jobs. Enforce the gate
      in `conftest.py` (e.g. auto-skip engine-marked tests below 3.10) so the
      discipline is structural.
  - **Engine jobs — match `engine.yml`'s matrix (currently 3.10/3.11/3.12):** quote
    it rather than hardcoding, so the two workflows cannot silently drift if the
    engine repins. Install the engine on **all** these jobs with pip caching (to
    keep the numpy build fast) and run the engine-importing round-trip tests +
    `test_integration.py`. The lib's **own** pytest/ruff/mypy come from the lib's
    `tests/pyproject.toml` dev deps (the lib does not need engine's `[dev]`); the
    engine is installed only for the round-trip + integration imports, so the
    command is `pip install <lib-test-deps> ./engine[report]` — the `[report]`
    extra, **not** `engine.yml`'s `-e "engine[dev,report]"`, since `[dev]` is engine
    tooling the lib doesn't reuse. **Make the engine a hard import on these jobs** —
    assert
    `import ca_elevation_engine` succeeds; do **not** use `pytest.importorskip`
    here. importorskip would turn a silent `pip install` failure (wrong
    interpreter, etc.) into a green-but-untested **skip** of the authoritative
    round-trip and verdict-ratchet tests. Reserve skip semantics
    (marker/`skipif < 3.10`) for keeping these tests *off the floor jobs* only.
    Installing `[report]` uniformly means `--format pdf` produces `report.pdf` on
    every job, so `test_integration.py` **asserts `report.pdf` exists** — no
    matrix-dependent pdf-vs-html flakiness. (If instead you want to test the HTML
    fallback, run that one case in a job *without* `[report]` and assert
    `report.html`; pin one, don't split by chance.)
  - **Verdict-ratchet ownership (decided):** the lib ratchet
    (`test_writeback_ratchet.py`) is **best-effort** — `engine/tests/test_registry.py`
    stays the authoritative enum-completeness gate. We do **not** add
    `models.py` to this workflow's path filter; instead `writeback.py` is raise-safe
    on an unmapped verdict (sentinel colour + warning, never `KeyError`), so a stale
    `MAPPING` degrades to a loud visual signal rather than crashing inside a Revit
    transaction (Section 4, `writeback.py`).
  - Unlike the dead C# job, this **actually runs** — but "**blocks**" also
    requires registering the check in **branch protection** (a GitHub setting
    outside the YAML). With a 3.8/3.9 floor matrix **plus** a 3.10/3.11/3.12 engine
    matrix there are up to five distinct check names; rather than register every
    leg, add a single `needs:`-fanin aggregator job (`pyrevit-extension / all-green`)
    and make **that** the one required check. Without that step, "blocks" is
    aspirational.
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
  fall back to." It is also the only non-copyleft commercial front door, so the
  closed-tier GPL3 question (Section 8) gates deletion too — see Open item 2. The
  verdict-colour semantics and CLI contract carry over.

## 7. Testing tiers (how the win shows up)

| Tier | Where | Runs in CI? |
|---|---|---|
| Syntax floor — pure `lib/` import-smoke + ruff(py38)/mypy, **no engine** | CPython **3.8/3.9**, ubuntu | **Yes — enforces the 3.8 floor** |
| Headless unit — `lib/` round-trip via `SpecManifest.from_dict` + schema validate | CPython **3.10+**, imports engine | **Yes — the new gain** |
| Integration — extension drives the real `ca-elevation` CLI over the engine's repo-relative fixture | CPython 3.10+, CI | Yes (engine installed; `[report]` extra if asserting PDF) |
| Live — `revit_extract` / `revit_export` / `revit_writeback` inside Revit | Ed's Windows Revit (now Claude-drivable via MCP — §11) | No — gated/manual |

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

- **Licensing — two boundaries, not one.** pyRevit is **GPL3**; our code stays
  **Apache-2.0**. The two artifacts sit on **opposite sides** of the derivative-
  work line and must not be analysed together:
  - **Engine** — **non-derivative as a standalone CLI**: a separate
    **out-of-process** process. The FSF treats a subprocess/CLI-boundary plugin as
    borderline-but-generally-non-derivative, and the engine is the easy end of that
    *in isolation*. **But for the commercial-bundle scenario this is not pre-cleared:**
    in a shipped product the only thing that invokes the engine CLI is the GPL3-hosted
    extension, and a **single installer shipping pyRevit + extension + engine venv
    together** is exactly the aggregation-vs-combined-work fact pattern (intimacy of
    communication, distributed/marketed as one program) counsel would scrutinize. So
    Open item 2's counsel scope must include **how the three artifacts are packaged
    and marketed together**, not just the extension in isolation — apply the same
    caution here as to the extension; do not pre-decide the engine for the bundle case.
  - **Extension** — the **opposite** case. Its scripts are loaded by pyRevit's
    loader **into pyRevit's CPython runtime**, share its address space, and import
    its API (`forms`/`script`/`revit`/`__revit__` — this plan relies on exactly
    that). That is the in-process-plugin-using-the-host's-API case the FSF treats
    as **likely derivative** — the boundary that protects the engine does **not**
    protect the extension. So **GPL3 exposure of the extension is an OPEN question
    for counsel**, not settled. **Do not assert "the OSS license is unaffected."**
  - **Practical mitigant for the *open-source* case:** the extension is already
    Apache-2.0, which is GPL3-compatible one-way, so distributing it **open source**
    is fine regardless. The live risk is only a future **closed/proprietary** tier
    (next bullet).
  The real cost: any **paid/commercial tier now sits on a GPL3 prerequisite** —
  and if the extension is derivative, a *closed-source* paid extension could itself
  be forced under GPL3 copyleft, which is far more than "a separately-installed
  dependency." The conscious trade against design.md's "commercial Revit product
  ships signed" rationale.
- **The "signed installer" was never built.** The current C# install story is
  *manual* (per `revit-addin/README.md`: copy `CaElevationReview.addin` into the
  `Addins/<year>\` dir, edit its `<Assembly>` path, replace the placeholder
  `<AddInId>` GUID once before release). There is no installer, no code signing,
  no produced engine venv. So we are **abandoning the design.md
  signed-standalone-installer path as a future option**, not losing a built
  capability — don't over-weight it as a regression. But state the **asymmetry**
  plainly: with C# the signed-MSI path was not merely open but **cheap and
  standard** to execute later (normal .NET packaging), whereas pyRevit-required
  **forecloses it permanently** — no amount of later effort reopens it. The real
  trade is "a low-cost standard future option" for "a path nothing reopens," not
  "the absence of a currently-built installer."
- **End-user onboarding friction (the substantive product cost, not just
  "polish").** Setup goes from "one installer" (aspirational) to "install pyRevit
  — the correct version for your Revit year, itself a multi-step install with its
  own compatibility matrix — **plus** provision the engine venv (Open item 4)
  **plus** drop in the extension." design.md's first stated reason for C# (line
  81) was exactly that paying/free users would not have to install pyRevit first.
  Be precise about the **delta** — and do **not** net out the venv step. Under C#,
  the engine venv was a *future-automatable* step: `EngineLocator` resolution step 3
  probes a venv bundled next to the add-in DLL (`./engine-venv/Scripts/...`), and
  `revit-addin/README.md` states "a packaged installer can ship a bundled engine
  venv" — i.e. the design.md signed installer would have **absorbed** venv
  provisioning and made it invisible. Under pyRevit, the extension-manager / clone-
  URL install has **no comparable hook** to silently provision a separate
  Python ≥3.10 venv, so the venv becomes a **manual, user-facing** step with no
  installer to hide it. The incremental friction is therefore **larger** than "just
  pyRevit install + per-year matching": it is that **plus** hand-provisioning the
  engine venv. This is load-bearing for **Open item 4** (settings storage / venv
  location), which is not a minor config question but the central onboarding-friction
  item.
- **Adoption-ceiling cost to the #1 stated goal.** Beyond monetization, gating on
  pyRevit narrows the **free-adoption funnel** — design.md's first-ranked objective
  ("Open source, Apache-2.0. Adoption is the goal," line 34) — from all Revit users
  to the **pyRevit-installing subset**, inheriting pyRevit's user base as the
  ceiling rather than Revit's. It also collapses a distinction design.md drew
  deliberately (lines 87–88): the standalone add-in was "a public, productized tool"
  kept **separate** from Ed's internal pyRevit toolset; the pivot puts the public
  product on the same distribution surface as the internal tooling. Accepted here
  because the testability / real-product gain (Sections 1–2) is judged worth it —
  but the trade is against design.md's *primary* goal, not only its commercial
  rationale.
- **Scope: desktop-only.** This pivot does **not** touch the iPhone capture app's
  App Store / Apple-IAP path (design.md Monetization, lines 264–293) — Revit
  add-ins ship on Windows and never go through any Apple store. The only
  monetization impact is on the desktop front door, where the paid/signed-tier
  story becomes harder.

## 9. Migration steps (when approved)

1. Scaffold `pyrevit-extension/` tree (layout above), engine untouched.
2. Implement the four real `lib` modules + their unit tests; get them green
   **locally** (CI does not exist until step 5 — avoid the chicken/egg). If you
   prefer "green in CI" literally true here, hoist a minimal `pyrevit-extension.yml`
   skeleton (the two job groups) to step 1.
3. Stub the three `revit_*` modules with `# LIVE` markers and clear TODOs.
4. Wire the three `script.py` entries + `bundle.yaml` + placeholder icons.
5. Add `pyrevit-extension.yml` (floor + engine job groups, path filter, branch-
   protection required check); update pre-commit + docs. **Keep `revit-addin/`**
   CI-gated off.
6. Hand Ed a checklist for the live-Revit validation pass — including the
   **idempotent re-import** criterion: writeback clears the **previously applied**
   override set (not the new report's ids) before reapplying, tested explicitly
   with the **drop-a-device** case (Section 2). This is new logic, not a C# port.
7. **Only after step 6 is green:** retire `revit-addin/` in a follow-up. "Delete
   C#" must not precede live sign-off (Section 6 rationale).

## 10. Rough effort

- Real lib + tests + ribbon + CI + docs: **~1 focused session** (most of it
  genuinely runnable and verified here).
- Live `revit_*` fill-in + on-Revit validation: **Ed-gated**, separate, hardware-bound.

## 11. Live development & validation via the Sterling Revit MCP server

A vendored Sterling fork of `mcp-server-for-revit-python` (pyRevit Routes + an
external CPython MCP server, localhost-only, pinned upstream SHA) gives a Claude
Code session a **live control channel into running Revit**, with **multi-version
discovery/binding across 2024–2027** (including the CoreCLR/.NET 8/10 runtimes
that 2025+ use) via `list_revit_instances` / `select_revit_instance`, plus
`execute_revit_code` and `list_dialogs` / `dismiss_dialog` for clearing modal
wedges. This is a **development & validation accelerator only**: it does **not**
change the locked architecture (Section 3) and ships to **no end user**.

How it changes the work:

- **The three live-Revit stubs become Claude-iterable, not blind hand-offs.**
  Section 2 calls `revit_extract` / `revit_export` / `revit_writeback`
  irreducibly Ed-only. With this bridge connected to a running Revit, a session
  can **run and refine them in place** — execute the `FilteredElementCollector`
  walk against real element params, test a view/floorplan export, apply
  `OverrideGraphicSettings` and visually confirm the verdict colouring — instead
  of writing them blind. **"Irreducible, Ed-only" → "Claude-iterable against a
  connected Revit; Ed still owns hardware + final sign-off."** The Section 7
  *Live* tier stays out of headless CI, but its inner loop is no longer
  manual-only.
- **Multi-version validation across the exact target range.** One session can
  confirm the extract/export/writeback calls against 2024, 2025, 2026, 2027 in
  turn. This also independently corroborates the plan's CoreCLR-on-2025+ facts
  (Section 3, the in-process-C#-compile caveat) and the `net8` TFM correction.
- **Real-model fixtures.** `execute_revit_code` against a genuine model can
  **extract a real manifest**, seeding engine fixtures — addressing design.md's
  "sample Revit model for manifest-extraction tests" need beyond synthetic-only.
- **Unattended robustness.** `list_dialogs` / `dismiss_dialog` keep a scripted
  `execute_revit_code` from wedging behind a modal.

Honest boundaries:

- **Not usable in this repo's Linux/CI env** (no Revit; not connected here) and
  **not a substitute for on-hardware sign-off** — the bridge drives a *real*
  Revit on **Ed's Windows machine**, so "live" still requires that machine; what
  changes is that Claude drives it interactively instead of Ed hand-running
  scripts. Revit is Windows-only, so this loop is **separate from the Mac/iOS
  loop**.
- **Engine-runtime independence holds.** The MCP server's *in-Revit* handlers are
  IronPython 2.7; our extension scripts are CPython (`#! python3`). Both coexist
  under `%APPDATA%\pyRevit\Extensions` as separate extensions with per-script
  engines — no conflict, and the Section 3 CPython choice is unaffected.
- **Trust scope.** `execute_revit_code` is arbitrary code execution inside Revit
  — a dev-only, localhost-only tool. Its egress channel is the LLM transcript
  (anything a tool returns becomes model context), same posture as any MCP read,
  pointed at Revit.
- **Licensing.** This bridge is a **development tool, not shipped**, so it adds
  **nothing** to the product's GPL3 exposure (Section 8); its own upstream licence
  still governs Sterling's internal use.

Net: this **relaxes, not eliminates** the live-Revit constraint — it pulls the
`revit_*` development loop forward into in-session iteration, leaving Ed's
hardware + sign-off as the remaining gate.

## Open items to confirm before building

1. **pyRevit version floor** (and therefore the bundled CPython the `lib/` code
   must support) — and which pinned pyRevit release this plan targets.
   **Resolve before building** — it sets the lint floor (there is no `bundle.yaml`
   engine-version constraint to set; pyRevit has no such key — Section 4).
   *Recommendation:* CPython 3.8 as the `lib/` syntax target
   (the oldest engine we may land on). Bundled-CPython by line: **4.8.x → 3.8;
   5.x → 3.11** (not 3.12); the **6.x** line is current — verify its engine
   version against the target release's `bin/cengines` before pinning.
2. **C# add-in: keep one cycle, then remove — gated on the closed-tier question,
   not just user validation.** *Recommendation:* keep `revit-addin/` CI-gated off;
   delete once pyRevit-as-prerequisite is validated with real users and Ed's live
   pass is green. **But add a gate before deleting:** if a future **closed/
   proprietary** Revit front-door tier is a real product option, the in-process
   GPL3 question (Section 8 licensing) must be **resolved by counsel first** —
   because C# is the **only** artifact that keeps a non-copyleft commercial front
   door open, and that ceiling (not "install-pyRevit-first" friction) is the
   load-bearing input to the retire decision. Tied to the licensing/monetization
   findings (Section 8), not merely "validated with real users."
3. **Icons** — placeholder now, real artwork later.
4. **Settings storage + engine-venv provisioning (load-bearing, not minor).**
   Where the engine path / venv location is configured (pyRevit config vs a
   repo-level settings file), **and how the user provisions the engine venv at all**
   — pyRevit's install path has no installer hook to bundle it (Section 8), so this
   is the central onboarding-friction question, not a config detail. Couples to the
   runtime-validation UX (Section 3): a mis-located engine means no validation until
   a full `run`. (Per-project write-back override state is **not** part of this item
   — Section 2 uses an in-model marker, so no separate store is needed.)
5. **Adopt the Sterling Revit MCP server for the live dev loop?** (Section 11.)
   Confirm we standardize on it for developing/validating the `revit_*` modules,
   and share `scripts/install-revit-mcp.ps1` + the exact MCP tool signatures so we
   can write a `docs/revit-mcp-dev-setup.md` and wire the live loop concretely.
   Windows-only; does not affect the shipped product or its GPL3 analysis.
