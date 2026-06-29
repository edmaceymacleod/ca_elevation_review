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
| `EngineRunner.cs`, `EngineLocator.cs` | ~1 small real Python module: locate + `subprocess` the `ca-elevation` CLI. Unit-tested in CI. |
| Ribbon assembly + `.addin` + signed installer | Real pyRevit `bundle.yaml` + folder layout. Complete, not stubbed. |
| Command orchestration (3 commands) | Real Python orchestration; testable except the live API calls. |
| Manifest *assembly* (raw values → manifest) | Real, CI-tested dict builders that round-trip through `SpecManifest` and validate against the schema. |
| Verdict→colour mapping, which-elements logic | Real, CI-tested pure functions. |

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
    match whatever CPython pyRevit bundles). Avoid 3.10-only syntax here.
  - The engine (its own venv): stays **3.10+**, unchanged.
  - *Open item:* confirm the exact CPython version in the targeted pyRevit
    release (pyRevit 4.8 → 3.7/3.8; pyRevit 5 → newer). Pin a pyRevit floor.
- **In-Revit footprint is stdlib + pythonnet + Revit API only.** Manifest
  *assembly* builds plain dicts; validation is delegated to the CLI
  (`ca-elevation validate`). The engine package is imported **only in tests**
  (which run in normal CI CPython, where numpy is fine) to assert the dict
  builders produce schema-valid, round-trippable payloads.

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
   ├─ conftest.py
   ├─ test_manifest_builder.py       # builds a manifest, asserts SpecManifest.from_dict + schema-valid
   ├─ test_bundle_io.py              # field-bundle write / capture read round-trips
   ├─ test_engine_runner.py          # arg-building + locator order (mock subprocess)
   └─ test_writeback.py              # verdict→colour mapping, grouping
```

### The seam, file by file

- **`script.py` (×3)** — thin: parse pyRevit UI selection, call one `lib`
  function, show progress/result via pyRevit `forms`. ~15 lines each.
- **`manifest_builder.py`** — pure. Input: a list of plain dicts of extracted
  device values (from `revit_extract`). Output: a manifest dict matching
  `spec_manifest.schema.json`. No Revit imports. **Fully tested.**
- **`bundle_io.py`** — pure stdlib. Assemble the field-bundle directory (manifest
  JSON + floorplan images), and read back the returned capture package. **Tested.**
- **`engine_runner.py`** — locate the `ca-elevation` CLI (explicit path → env var
  → bundled venv → PATH, ported from the C# `EngineLocator` order), build the
  `run --manifest … --capture … --out … --format pdf` argv, `subprocess.run`,
  parse `verdict_report.json`. **Tested** with a mocked subprocess.
- **`writeback.py`** — pure. Map verdict → override colour
  (pass→green / flag→orange / absent→red / type_mismatch→purple), group device
  results by element id for application. **Tested.**
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

`run` already writes `DIR/verdict_report.json` + `DIR/report.pdf`. `engine_runner`
just orchestrates it and reads the JSON back for write-back.

## 6. CI, pre-commit, docs changes

- **New workflow `pyrevit-extension.yml`** — runs `pytest` over
  `pyrevit-extension/tests/` on **ubuntu**, Python 3.10/3.11/3.12, installing the
  engine so tests can import it for round-trip assertions. Unlike the C# job,
  this **actually runs and blocks** — a real coverage gain. Also `ruff` + `mypy`
  over `lib/ca_elevation_revit`.
- **Pre-commit** — extend ruff/mypy/pytest scope to the new lib; drop the
  `dotnet format` hook (or keep, gated, only if the C# tree is retained).
- **Docs** — update `docs/architecture.md` and root `README.md`: front door is a
  pyRevit extension; note pyRevit becomes a **user prerequisite** and the
  monetization/distribution implication (no signed standalone installer); live
  Revit tests stay gated/manual.
- **Retire `revit-addin/`** — remove (or keep alongside for one cycle, per your
  earlier preference). The verdict-colour semantics and CLI contract carry over.

## 7. Testing tiers (how the win shows up)

| Tier | Where | Runs in CI? |
|---|---|---|
| Headless unit — `lib/` minus `revit_*` | normal CPython, imports engine | **Yes — the new gain** |
| Integration — extension drives the real `ca-elevation` CLI over a fixture bundle | CI | Yes (engine installed) |
| Live — `revit_extract` / `revit_export` / `revit_writeback` inside Revit | Ed's Revit install | No — gated/manual |

## 8. Distribution / product note (the trade-off to accept)

The design doc deliberately chose standalone C# so users would **not** need
pyRevit first, and because "a signed .NET add-in with a real installer is how a
commercial Revit product ships." This pivot makes **pyRevit a prerequisite** and
changes the distribution story to "install via pyRevit's extension manager /
clone URL / drop into the extensions dir." Worth a conscious sign-off, as it
softens the polished-commercial / paid-tier path.

## 9. Migration steps (when approved)

1. Scaffold `pyrevit-extension/` tree (layout above), engine untouched.
2. Implement the four real `lib` modules + their unit tests; get them green in CI.
3. Stub the three `revit_*` modules with `# LIVE` markers and clear TODOs.
4. Wire the three `script.py` entries + `bundle.yaml` + placeholder icons.
5. Add `pyrevit-extension.yml`; update pre-commit + docs; decide C# retire/keep.
6. Hand Ed a checklist for the live-Revit validation pass.

## 10. Rough effort

- Real lib + tests + ribbon + CI + docs: **~1 focused session** (most of it
  genuinely runnable and verified here).
- Live `revit_*` fill-in + on-Revit validation: **Ed-gated**, separate, hardware-bound.

## Open items to confirm before building

1. **pyRevit version floor** (and therefore the bundled CPython version the
   `lib/` code must support).
2. **C# add-in: remove or keep** for one cycle.
3. **Icons** — placeholder now, real artwork later.
4. **Settings storage** — where the engine path / venv location is configured
   (pyRevit config vs a repo-level settings file).
