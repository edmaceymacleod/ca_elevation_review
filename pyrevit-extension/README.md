# CA Elevation Review — pyRevit extension

The Revit **front door** for CA Elevation Review, as a pyRevit extension running
on pyRevit's **CPython** engine. It extracts the spec manifest + floorplans from
the live model, writes a field bundle for the iPhone app, invokes the
verification **engine out-of-process** on returned captures, and colours the
model's devices by verdict.

> This is the pivot from the standalone C# add-in (`../revit-addin/`, kept one
> cycle, CI-gated off until live validation). See
> [`../docs/pyrevit-migration-plan.md`](../docs/pyrevit-migration-plan.md) for the
> full design, trade-offs, and live-validation acceptance criteria.

## Layout

```
CaElevationReview.extension/
  CaElevationReview.tab/Verify.panel/
    ExportBundle.pushbutton/   {bundle.yaml, script.py}
    ImportCaptures.pushbutton/ {bundle.yaml, script.py}
    OpenReport.pushbutton/     {bundle.yaml, script.py}
  lib/ca_elevation_revit/      # the real, CI-tested library
    config, manifest_builder, bundle_io, engine_runner, writeback   # PURE (stdlib)
    revit_extract, revit_export, revit_writeback                    # LIVE (Revit API)
tests/                         # run in plain CPython CI — no Revit, no pyRevit
```

The `lib/` split is the whole point: the **pure** modules (manifest assembly,
bundle IO, engine invocation, verdict→colour mapping) are stdlib-only and fully
unit-tested in CI; the three `revit_*` modules are the only ones that touch the
Revit API (function-local imports) and are validated on Ed's hardware.

## Requirements

- **pyRevit** with its **CPython** engine (the scripts use `#! python3`). Each
  script also has a runtime guard that aborts loudly if it is routed to
  IronPython or an unexpectedly old CPython (guards against pyRevit 6.0.0 issue
  #3092). Pin a pyRevit release unaffected by #3092 — see Open item 1 in the plan.
- The **engine** installed in its own Python ≥3.10 venv, providing the
  `ca-elevation` CLI. The extension finds it via (1) an explicit path, (2) the
  `CA_ELEVATION_ENGINE` env var, (3) a bundled `engine-venv/` next to the
  extension, or (4) `ca-elevation` on `PATH`.

## Install

**From a cloned repo (dev).** Register the folder that *contains* the
`.extension` — pyRevit scans each search path **one level deep** for `*.extension`
folders, so point it at `pyrevit-extension/`, not the repo root:

```powershell
pyrevit extensions paths add "<repo>\pyrevit-extension"
```

Then **start (or restart) Revit** — the path is scanned at pyRevit startup. A
mid-session *Reload* does **not** reliably pick up a *newly* added search path
(the running session can write its older config back over it); if you must load
without a restart, add the path to the in-session config (`user_config.core.
userextensions` + `save_changes()`) *before* reloading. On load you get the
**CaElevationReview** ribbon tab → **Verify** panel → *Export Field Bundle* /
*Import Captures* / *Open Report*. (Verified on Revit 2025 + pyRevit 6.1.0.)

**Standalone.** Drop `CaElevationReview.extension/` into
`%APPDATA%\pyRevit\Extensions\` and reload.

Either way, provision the engine venv and confirm `ca-elevation --version` resolves.

## Develop / test

```bash
cd pyrevit-extension/tests
pip install -r requirements-floor.txt          # floor toolchain (no engine)
pytest -q -m "not engine"                       # engine-free lib tests (3.8+)

pip install pytest "../../engine[report]"        # engine, for the round-trip/integration tier
pytest -q                                        # full suite (3.10+)
```

Lint/type the lib at the **py38 floor** (the in-Revit runtime is older than the
engine's 3.10):

```bash
cd pyrevit-extension
ruff check  --config tests/pyproject.toml CaElevationReview.extension/lib tests
mypy        --config-file tests/pyproject.toml CaElevationReview.extension/lib
```

CI (`.github/workflows/ci.yml`) runs the `pyrevit floor` jobs (3.8/3.9 matrix,
engine-free) plus the `pyrevit engine` jobs (3.10/3.11/3.12 engine matrix), gated
by the single `CI / all-green` required check (see docs/ci.md).

## What is validated where

| Layer | Tested |
|---|---|
| `manifest_builder`, `bundle_io`, `engine_runner`, `writeback` | Headless CI (the real gain) |
| Engine round-trip + real-CLI integration | CI 3.10+ (engine installed) |
| `revit_extract` / `revit_export` / `revit_writeback` | **Live, on Ed's Revit** — incl. UniqueId identity + idempotent re-import |

Icons are intentionally omitted for now (pyRevit falls back to a default); real
artwork is a follow-up.
