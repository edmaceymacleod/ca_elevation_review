# CA Elevation Review

[![CI](https://github.com/edmaceymacleod/ca_elevation_review/actions/workflows/ci.yml/badge.svg)](https://github.com/edmaceymacleod/ca_elevation_review/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](engine/pyproject.toml)
[![Status: Phase 0](https://img.shields.io/badge/status-Phase%200%20%C2%B7%20in%20progress-orange.svg)](#build-phasing)

**An as-built elevation verification tool: compare the devices a Revit model
*expects* against the site reality a phone *captured*, and emit per-device
verdicts plus an issuable report.**

Low-voltage, electronic-security, and AV devices (card readers, cameras,
speakers, panels, outlets, screens) get installed on site against a designed
Revit elevation. Verifying that what was *installed* matches what was *drawn* is
today a manual, subjective walk-the-site exercise that leaves no durable record.

Commodity tools already solve *capture* (iPhone Pro LiDAR + SiteScape / Polycam
export posed point clouds) and SaaS platforms solve *register-to-plan*. The gap
nobody has filled, and the thing that is open-sourceable, is **the verification
layer**: given the expected devices (from the Revit model) and a captured
reality, produce a per-device correct/incorrect verdict and an issuable report.
That is what this repo builds.

- **License:** Apache-2.0
- **Local-first:** no SaaS, no hosted middleware, no cloud processing. Everything
  runs on the user's own machine; project data moves by local file exchange.
- **Status:** Phase 0 (engine + fixtures + CI) -- **in progress.**

## Contents

- [Architecture](#architecture-three-components-three-languages-one-repo)
- [Repository layout](#repository-layout)
- [Quickstart (the engine)](#quickstart-the-engine)
- [What v1 can honestly verify](#what-v1-can-honestly-verify)
- [Build phasing](#build-phasing)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Architecture: three components, three languages, one repo

```
+--------------------+        local file        +-----------------------+
|  iPhone capture    |  ----- field bundle --->  |  pyRevit extension    |
|  app (Swift/ARKit) |  <---- capture pkg ------  |  (Python, Windows)    |
|  ios-app/          |                            |  pyrevit-extension/   |
+--------------------+                            +-----------+-----------+
                                                              | invokes (out-of-process)
                                                              v
                                                  +-----------------------+
                                                  |  CPython engine       |
                                                  |  (the OSS core)       |
                                                  |  engine/              |
                                                  +-----------------------+
```

- **`engine/`** -- CPython package (Python 3.10+), the OSS core where the value
  lives. Ingests two payloads, registers the capture into model coordinates,
  compares each expected device against reality, emits verdicts + a report.
  pip-installable and headlessly testable; heavy native backends are optional
  extras loaded lazily. Build target: **Linux**.
- **`pyrevit-extension/`** -- the Revit front door, written in Python and run by
  pyRevit's CPython runtime. It extracts the spec manifest from the live model,
  exports floorplans, invokes the engine out-of-process, writes verdicts back into
  the model, and opens the report. Moving the front door off C# turns the
  manifest-assembly / bundle-IO / engine-invocation / verdict-mapping logic into
  real, CI-tested CPython that reuses the engine's own models and schemas; the
  live Revit-API-touching pieces stay validated on hardware. Build target:
  **Windows**. See [`docs/pyrevit-migration-plan.md`](docs/pyrevit-migration-plan.md).
- **`revit-addin/`** -- the original C# .NET add-in front door, now **retained
  legacy**: kept one cycle, CI-gated off, pending live validation of the pyRevit
  extension. Build target: **Windows**. Supported Revit years: **2024-2027** (2024
  on `net48`; 2025/2026/2027 on `net8.0-windows`).
- **`ios-app/`** -- Swift / SwiftUI / ARKit field client + the pure
  `CaElevationKit` SwiftPM library. Deliberately thin: pin a location + heading,
  capture RGB + LiDAR depth + ARKit pose, package, export. No analysis logic.
  Build target: **macOS** (kit builds headlessly anywhere).

### The internal seam (two payloads)

The engine only ever sees two documented JSON payloads -- which is exactly what
makes it unit-testable with no live Revit session and no device:

| Payload | Produced by | Contents |
|---|---|---|
| **Spec manifest** | Revit front door | expected devices (id, family/type, position, mounting height, orientation, tolerances), levels, floorplans + the plan-pixel-to-model affine |
| **Capture package** | iPhone app | per shot: RGB, depth/point-cloud, ARKit intrinsics + pose, and the operator's floorplan pin (x,y) + heading |

The engine emits a third payload, the **verdict report**, consumed by the Revit
front door for write-back and by the report renderer. All three are defined by JSON Schema
under [`engine/src/ca_elevation_engine/schemas/`](engine/src/ca_elevation_engine/schemas/)
and documented in [`docs/schemas.md`](docs/schemas.md).

### Repository layout

```
ca_elevation_review/
├── engine/              # CPython OSS core: ingest → register → compare → report
│   ├── src/             #   ca_elevation_engine package (incl. schemas/)
│   ├── fixtures/        #   golden manifest + capture + verdict fixtures
│   └── tests/           #   headless unit/integration tests
├── pyrevit-extension/   # Revit front door (pyRevit CPython runtime, Windows)
├── revit-addin/         # Original C# .NET add-in — retained legacy, CI-gated off
├── ios-app/             # Swift/SwiftUI/ARKit capture client + CaElevationKit
├── docs/                # Design, architecture, schemas, testing, migration plan
├── tools/               # Repo-level dev hooks (e.g. the README freshness guard)
├── CONTRIBUTING.md      # Per-component dev setup + tiered testing model
└── README.md
```

---

## Quickstart (the engine)

The engine is independently runnable -- you can hack the brain without owning
Revit or an iPhone.

```bash
# From the repo root. Install the engine with dev + report extras.
pip install -e "engine[dev,report]"

# Run the verification pipeline over a manifest + capture package.
# --out is a directory: it receives verdict_report.json plus a rendered report.
ca-elevation run \
    --manifest path/to/spec.manifest.json \
    --capture  path/to/site.capture.json \
    --out      path/to/output_dir
# Primary deliverable is a PDF (report.pdf). Use --format html|json to switch;
# PDF needs the optional 'reportlab' backend (included in the [report] extra)
# and falls back to a self-contained HTML report if it is unavailable.
```

Heavy native backends (Open3D / pye57 / OpenCV) are an optional extra -- install
them only when you need point-cloud registration:

```bash
pip install -e "engine[dev,report,heavy]"
```

Run the tests and linters the way CI does:

```bash
ruff check engine
ruff format --check engine
cd engine && pytest -q -m "not heavy" --cov=ca_elevation_engine
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full per-component dev setup and
the tiered testing model.

---

## What v1 can honestly verify

The tool is honest about the limits of a single surface capture. It never claims
sub-inch accuracy.

| Check | v1 | Notes |
|---|---|---|
| Presence | **yes** | robust, needs no scale |
| Position | **yes** | metric via LiDAR; approximate without it |
| Mounting height | **yes** | needs a vertical datum (floor line / depth) |
| Orientation | **yes** | up/down, facing |
| Device type | opportunistic | only if legible in frame; vision-assisted, human-confirmed |
| Exact SKU identity | **no** | out of scope for v1 |
| Behind-wall (cable, backbox) | **no** | not observable from a surface capture |

---

## Build phasing

Each phase is independently demoable; phasing finds out early whether the core is
trustworthy before more effort rides on it.

- **Phase 0 -- Engine + fixtures + CI** -- *in progress.* Prove the CPython engine
  emits verdicts worth staking a report on, fed by off-the-shelf scanner exports
  (SiteScape / Polycam E57 + posed images). No custom app, no add-in needed.
- **Phase 1 -- Revit front door (pyRevit extension)** -- *planned.* Manifest
  extraction, floorplan / bundle export, engine invocation, verdict write-back,
  report generation, built as a pyRevit CPython extension
  ([`docs/pyrevit-migration-plan.md`](docs/pyrevit-migration-plan.md)). The
  original C# add-in (`revit-addin/`) is retained legacy, CI-gated off, pending
  live validation.
- **Phase 2 -- iPhone capture app** -- *planned.* Pin + heading + depth + pose
  capture, bundle round-trip. Removes the last friction and delivers the
  integrated product.

---

## Documentation

- [`docs/design.md`](docs/design.md) -- the product + architecture design sketch (source of intent).
- [`docs/architecture.md`](docs/architecture.md) -- the three components, the seam, the payloads, the pipeline.
- [`docs/pyrevit-migration-plan.md`](docs/pyrevit-migration-plan.md) -- the front-door pivot from the C# add-in to the pyRevit extension, with rationale and file layout.
- [`docs/testing.md`](docs/testing.md) -- the tiered testing model and fixture / registry / ratchet discipline.
- [`docs/ci.md`](docs/ci.md) -- the single-gate CI design and the one required `all-green` check.
- [`docs/schemas.md`](docs/schemas.md) -- the three payload schemas, field by field, and the affine / pose conventions.
- [`docs/ui-conventions.md`](docs/ui-conventions.md) -- the iPhone app's look-and-feel policy (native-default), color/typography semantics, and branding assets.
- [`docs/sessions/`](docs/sessions/README.md) -- the cross-session record format: dated, durable notes for multi-step or risky changes (what changed, how verified, how to undo).

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev
setup, the testing tiers, and the pre-commit / fixture discipline. The repo's
tests + CI are the project's memory: keep them green and keep them honest.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
