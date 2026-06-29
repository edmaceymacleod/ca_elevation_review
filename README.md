# CA Elevation Review

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

---

## Architecture: three components, three languages, one repo

```
+--------------------+        local file        +-----------------------+
|  iPhone capture    |  ----- field bundle --->  |  Revit C# add-in      |
|  app (Swift/ARKit) |  <---- capture pkg ------  |  (.NET, Windows)      |
|  ios-app/          |                            |  revit-addin/         |
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
- **`revit-addin/`** -- C# .NET add-in. The desktop front door: extracts the spec
  manifest from the live model, exports floorplans, invokes the engine
  out-of-process, writes verdicts back into the model, opens the report. Build
  target: **Windows**. Supported Revit years: **2024-2027** (2024 on `net48`;
  2025/2026/2027 on `net8.0-windows`).
- **`ios-app/`** -- Swift / SwiftUI / ARKit field client + the pure
  `CaElevationKit` SwiftPM library. Deliberately thin: pin a location + heading,
  capture RGB + LiDAR depth + ARKit pose, package, export. No analysis logic.
  Build target: **macOS** (kit builds headlessly anywhere).

### The internal seam (two payloads)

The engine only ever sees two documented JSON payloads -- which is exactly what
makes it unit-testable with no live Revit session and no device:

| Payload | Produced by | Contents |
|---|---|---|
| **Spec manifest** | Revit add-in | expected devices (id, family/type, position, mounting height, orientation, tolerances), levels, floorplans + the plan-pixel-to-model affine |
| **Capture package** | iPhone app | per shot: RGB, depth/point-cloud, ARKit intrinsics + pose, and the operator's floorplan pin (x,y) + heading |

The engine emits a third payload, the **verdict report**, consumed by the add-in
for write-back and by the report renderer. All three are defined by JSON Schema
under [`engine/src/ca_elevation_engine/schemas/`](engine/src/ca_elevation_engine/schemas/)
and documented in [`docs/schemas.md`](docs/schemas.md).

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
- **Phase 1 -- Revit C# add-in** -- *planned.* Manifest extraction, floorplan /
  bundle export, engine invocation, verdict write-back, report generation.
- **Phase 2 -- iPhone capture app** -- *planned.* Pin + heading + depth + pose
  capture, bundle round-trip. Removes the last friction and delivers the
  integrated product.

---

## Documentation

- [`docs/design.md`](docs/design.md) -- the product + architecture design sketch (source of intent).
- [`docs/architecture.md`](docs/architecture.md) -- the three components, the seam, the payloads, the pipeline.
- [`docs/testing.md`](docs/testing.md) -- the tiered testing model and fixture / registry / ratchet discipline.
- [`docs/schemas.md`](docs/schemas.md) -- the three payload schemas, field by field, and the affine / pose conventions.

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev
setup, the testing tiers, and the pre-commit / fixture discipline. The repo's
tests + CI are the project's memory: keep them green and keep them honest.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
