# As-Built Elevation Verification Tool -- design sketch

**Status:** Draft -- last updated 2026-06-29. Architecture and UX sketch for this repo
(working name **PlumbAR**, TBD). The repo is now scaffolded and this document lives in its `docs/`.
Phase 0 (engine + fixtures + CI) is in progress -- see [`../README.md`](../README.md) for the
current build state.

**Scope of this document:** capture the product shape, the three-component architecture, the field
and desktop UX, the verification pipeline, the testing/CI discipline ported from the Sterling repo,
the build phasing, and the human-vs-Claude responsibility split. It is a sketch to argue from, not a
final contract; open questions are listed at the end.

---

## Problem

Low-voltage / electronic-security / AV devices get installed on site against a designed Revit
elevation -- card readers, cameras, speakers, panels, outlets, screens -- each at a specified
location, mounting height, and orientation. Verifying that what got installed matches what was
drawn is today a manual exercise: walk the site, eyeball each wall against a printed elevation,
hand-write a punch list. It is slow, subjective, and produces no durable record.

The capture half of this problem is already solved by commodity tools (iPhone Pro LiDAR + apps like
SiteScape / Polycam that export E57/PLY point clouds with pose). The SaaS reality-capture platforms
(OpenSpace, Matterport) solve register-to-plan and progress tracking. **What nobody has built, and
what is open-sourceable, is the verification layer:** given what *should* be installed (from the
Revit model) and what *is* installed (a captured reality), produce a per-device correct/incorrect
verdict and an issuable report. That is the wedge.

---

## Product vision and constraints

- **Open source, Apache-2.0.** Adoption is the goal. A permissive license maximizes use.
- **Bound to Revit.** Revit is the de facto construction authoring tool; binding to it is meeting
  the audience where they are, and it is what makes the spec manifest *free and authoritative*
  (read families, types, mounting heights, positions, orientations straight from the model -- the
  thing standalone scanners cannot do).
- **Local-first, NO hosted middleware.** Decided 2026-06-28: there is no SaaS, no cloud processing,
  no Ed-operated service. All processing runs on the user's own machine. Project data moves between
  phone and desktop by local file exchange (AirDrop / iCloud Drive / Files / cable). This removes
  the data-processor liability and the operational burden entirely.
- **Quality must not cost more than doing it by hand.** Capture friction is the hard budget: the
  field step must be no slower than the manual QA it replaces, or the tool is not worth using.
- **Honest about what a capture can verify.** Presence, gross position, mounting height, orientation,
  and obvious device-type mismatch -- yes. Sub-inch metrology, anything behind the wall (cable,
  backboxes), and automatic SKU identification -- no, not in v1.

---

## Architecture: three components, three languages, one repo

```
+--------------------+        local file        +-----------------------+
|  iPhone capture    |  ----- field bundle --->  |  pyRevit extension    |
|  app (Swift/ARKit) |  <---- capture pkg ------  |  (Python, Windows)    |
+--------------------+                            +-----------+-----------+
                                                              | invokes (out-of-process)
                                                              v
                                                  +-----------------------+
                                                  |  CPython engine       |
                                                  |  (the OSS core)       |
                                                  +-----------------------+
```

1. **iPhone capture app (Swift / SwiftUI / ARKit) -- the field client.**
   Deliberately *thin*: load Revit-exported floorplans, let the user pin location + heading,
   capture RGB + LiDAR depth + ARKit pose, package and export. No analysis logic lives here. It is
   a sensor client, nothing more. (Native iOS is required, not chosen: ARKit `sceneDepth` /
   LiDAR is unavailable to web or Android. Metric depth forces native.)

2. **CPython engine -- the OSS core, where the value lives.**
   A pip-installable, headlessly-testable package: ingest manifest + capture package, register the
   capture to model geometry, compare each expected device against reality, classify verdicts,
   emit a report. Heavy native deps (Open3D / PDAL / pye57 / OpenCV / a CoreML-or-desktop vision
   model) live here, which is exactly why this is CPython and runs out-of-process from Revit (those
   wheels are fragile to load inside Revit's process). It is independently runnable, so contributors
   can hack the brain without owning Revit or an iPhone.

3. **Revit front door (pyRevit extension, Python) -- spec source, engine invoker, result sink.**
   Written in Python and run by pyRevit's CPython runtime. It extracts the spec manifest from the
   live model, exports floorplans (with their coordinate transforms) into the field bundle, invokes
   the CPython engine out-of-process on returned captures, renders verdicts back into the model
   (color devices by pass/fail), and opens the report. Moving the front door off C# turns the
   manifest-assembly / bundle-IO / engine-invocation / verdict-mapping logic into real, CI-tested
   CPython that reuses the engine's own models and schemas; only the live Revit-API-touching pieces
   stay validated on hardware. See [`pyrevit-migration-plan.md`](pyrevit-migration-plan.md).

   The original **C# .NET add-in** (`revit-addin/`) was the first front door and is now **retained
   legacy** -- kept one cycle, CI-gated off, pending live validation of the pyRevit extension. It is
   the only artifact preserving the signed-installer / closed-tier commercial option (the path that
   originally argued for C#).

This is a separate product from the Sterling pyRevit extension that stays Ed's internal toolset;
this is the public, productized tool. The two now share the pyRevit distribution surface but remain
distinct extensions.

### The internal seam

The contract between Revit extraction and the engine is two documented payloads:

- **Spec manifest** -- expected devices: stable id, family/type, expected 3D position, mounting
  height, orientation, per-device tolerances, and which elevation/level they belong to. Plus the
  floorplan images and the plan-pixel-to-model-coordinate transform for each level.
- **Capture package** -- per shot: RGB image, depth map (or derived E57/PLY point cloud), ARKit
  camera intrinsics + pose, and the user's floorplan pin (x,y) + heading.

The engine only ever sees these two payloads. Justification for keeping the seam is no longer
multi-BIM portability (dropped) -- it is (a) the out-of-process boundary needs a defined wire format
anyway, and (b) it is what makes the engine unit-testable with no live Revit session.

---

## Capture localization: the floorplan pin as georeference anchor

The user, after taking a shot, drops a pin on the floorplan for *where they stood* and an arrow for
*which way the camera faced*. This is not just a photo label -- it is the **georeferencing
primitive**: the one piece of hard-to-automate input only a person can supply quickly, and it is
what drops the capture into the building's coordinate system.

Every idea explored during design has a defined job in the pipeline:

- **Coarse pin + heading** -> global anchor (which wall, roughly where and facing). The arrow is
  pre-filled from the device compass so the user confirms/nudges rather than guesses, killing most
  coarse-heading error.
- **ARKit pose** -> full relative 6DOF; the pin georeferences ARKit's arbitrary world frame into
  Revit coordinates, so one good pin can anchor a whole multi-shot session.
- **LiDAR depth** -> metric per-pixel 3D in the building frame.
- **Registration to the rendered elevation** -> the *refinement* step, seeded by the coarse pin,
  that snaps the capture to model geometry and recovers the accuracy the coarse pin alone cannot.

Pipeline shape: coarse human anchor -> sensors -> fine registration -> compare -> report.

**Known v1 limitation:** a single viewpoint carries occlusion shadows (anything hidden is not
captured) and LiDAR is coarse (~256x192 depth, reliable to ~5 m). For a flat device wall shot
roughly straight-on at 2-3 m this is fine; a short sweep can fill gaps later. The report must label
geometry from protruding devices as approximate.

---

## UX sketch

### Field flow (iPhone app)

1. **Open project.** Load a field bundle (floorplans + expected devices) received by AirDrop /
   Files / iCloud.
2. **Pick level / floorplan.** Thumbnail list; tap to open the plan.
3. **Capture.** Live camera with LiDAR active. Frame the wall, one wall per shot, shoot.
4. **Place it.** Post-capture review screen: confirm the shot, then drop the location pin on the
   plan and confirm the heading arrow (pre-filled from compass). Optionally tag the target
   elevation if the app cannot infer it.
5. **See it land.** The capture appears on the plan as a placed camera icon with its heading; a
   running list shows captured vs still-expected walls for the level.
6. **Repeat / export.** When the walk is done, export the capture package bundle back to the
   desktop.

Design intent: steps 3-4 are the entire per-shot burden -- shoot, glance, tap, confirm. That is the
"no slower than manual" budget.

### Desktop flow (Revit front door)

1. **Export field bundle.** Select level(s) / scope box -> the front door extracts the spec manifest
   and floorplans -> writes a bundle file to hand to the phone.
2. *(field capture happens)*
3. **Import captures.** Point the front door at the returned capture package -> it invokes the
   CPython engine out-of-process and shows progress.
4. **Review verdicts.** A per-device table (pass / flag / absent / type-mismatch, with confidence),
   a side-by-side of rendered elevation vs registered capture for any flagged item, and a 3D overlay
   in the model coloring devices by verdict. Ambiguous device *identities* are surfaced here for
   human confirmation (v1 does not auto-resolve SKU identity).
5. **Generate report.** Issue a PDF/HTML report: elevation thumbnail + capture side-by-side,
   per-device verdict table, quantified-but-approximate deviations, and a summary punch list.

---

## Engine pipeline (the OSS core)

1. **Ingest** manifest + capture package; validate both against their JSON schemas.
2. **Coarse georeference** from pin + heading -> initial transform into model coordinates.
3. **Refine** by registering the capture to model geometry near the targeted wall (ICP of the point
   cloud against model surfaces, and/or 2D registration of the photo to the rendered elevation),
   seeded by step 2.
4. **Locate** each expected device in view: geometry candidate detection + vision-assisted typing.
5. **Compare**: compute position delta, height delta, orientation delta; assess presence and
   opportunistic device-type match.
6. **Verdict**: apply the per-device tolerance ruleset -> pass / flag / absent / type-mismatch, each
   with a confidence. Identity stays human-confirmable.
7. **Emit**: structured results (for Revit write-back) + the issuable report.

### Verification scope, v1

| Check | v1 | Notes |
|---|---|---|
| Presence | yes | robust, needs no scale |
| Position | yes | metric via LiDAR; approximate without it |
| Mounting height | yes | needs a vertical datum (floor line / depth) |
| Orientation | yes | up/down, facing |
| Device type | opportunistic | only if legible in frame; vision-assisted, human-confirmed |
| Exact SKU identity | no | out of scope for v1 |
| Behind-wall (cable, backbox) | no | not observable from a surface capture |

Tolerances are per-device, defaulted in the manifest, configurable. The report never claims
sub-inch accuracy.

---

## Porting the testing / CI / fixture discipline

The hard-won discipline from the Sterling pyRevit repo transfers as *principles*, not IronPython
specifics. This repo recreates each, adapted to a three-language stack.

1. **Fixture as immutable single source of truth, built by seeders.**
   The Sterling repo enumerates fixture contents as `PROJECT_INVARIANTS` (each an `F-NN` id + title +
   verifier) and builds them with deterministic, version-gated `fNN_<slug>.py` seeders; ad-hoc
   fixture mutation is forbidden. Port: this repo needs (a) a sample Revit model for
   manifest-extraction tests, (b) synthetic + at least one real capture package (E57 + posed
   images + pins), and (c) golden expected reports. Each fixture property gets an invariant id +
   verifier; seeders build them deterministically; tests read, never write.

2. **Registry as single source of truth + coverage ratchets.**
   The Sterling repo's `REGISTRY` declares every tool with its contracts, and `test_testing_registry.py`
   enforces one-way coverage ratchets (every tool folder registered or explicitly waived; new
   smoke-only entries capped at zero; allowlists purged of stale entries). Port: a registry of
   engine checks and capture scenarios, with ratchet tests that fail when a new check or supported
   device family ships without fixture coverage and a golden case.

3. **Schema / structure validation in CI.**
   `validate_bundle.py` validates structure, metadata, encoding, and JSON/YAML validity fail-closed
   under `--strict`. Port: JSON-Schema validation of the manifest and capture-package formats, run
   in CI, so a malformed payload fails the build rather than the field.

4. **Tiered tests: cheap local -> CI -> live.**
   - *Headless unit* (engine pure math + IO, no Revit, no device) -- the bulk, run everywhere.
   - *Integration* (engine over fixture capture packages -> golden reports; snapshot/golden-file
     comparison for determinism).
   - *Live* (the Revit front door against a real Revit install; iOS app on a real LiDAR device) --
     gated and largely manual, attested by immutable per-SHA commit status, never blocking the unit CI.

5. **Pre-commit mirrors CI, per language.** Python -- engine + pyRevit extension -- (ruff + mypy +
   pytest), Swift (swiftlint + `swift build`/test), plus gitleaks secret scanning. The retained-legacy
   C# add-in's `dotnet format` + build hook stays gated. Keep the local suite fast; expensive/live
   checks stay opt-in (pre-push), with documented escape hatches.

6. **CI matrix across components.** The engine (Python) on Linux, the pyRevit extension (Python) on
   Linux with its live Revit-API pieces gated to manual Windows validation, the Swift app on macOS;
   the legacy C# add-in is CI-gated off. Each component independently buildable and testable so a
   break is localized.

7. **Separation of pure logic from platform-coupled code** (the testability rule), applied to all
   three: engine math vs IO; front-door logic vs Revit API; app logic vs ARKit.

8. **Fail-closed gates keyed to immutable commit state**, kill-switch label to decouple code review
   from CI lock, release flow separate from PR flow -- recreated as-is.

---

## Build phasing (de-risking the commitment)

This is genuinely three components across three languages. Phasing finds out early whether the
core is trustworthy before effort rides on it. Each phase is independently demoable.

- **Phase 0 -- Engine + fixtures + CI.** Build the CPython engine and prove it emits verdicts worth
  staking a report on, fed by *off-the-shelf* scanner exports (SiteScape/Polycam E57 + posed
  images). No custom app, no Revit front door yet. This validates the brain cheaply.
- **Phase 1 -- Revit front door (pyRevit extension).** Manifest extraction, floorplan/bundle export,
  engine invocation, verdict write-back, report generation, built as a pyRevit CPython extension
  ([`pyrevit-migration-plan.md`](pyrevit-migration-plan.md)). Now it is a usable desktop tool for
  anyone who can produce a scan. The original C# add-in (`revit-addin/`) is retained legacy,
  CI-gated off, pending live validation.
- **Phase 2 -- iPhone capture app.** Pin + heading + depth + pose capture, bundle round-trip. This
  removes the last friction and delivers the integrated product.

---

## Responsibility split (Claude vs Ed)

Stated plainly because it drives planning. Claude's coding throughput is not the bottleneck; the
bottleneck is everything requiring a persistent, accountable, hardware-holding human.

**Claude (in-session, episodic):** all code across the three components, tests, CI, schemas, docs,
in-session debugging, chasing SDK/API changes, golden-file maintenance. Treat Claude as an extremely
fast episodic builder invoked per task -- not an always-on daemon that wakes when iOS ships a
breaking change. The repo's tests + CI are the memory that lets the next session catch what the last
missed.

**Ed (continuous, accountable):** the Apple Developer account, signing certs / provisioning, App
Store submission and review responses, IAP setup if a paid tier ships, on-device LiDAR testing (the
simulator has no LiDAR), the Revit license/install for live tests, providing and refreshing fixtures
(the Revit model + real captures), product decisions, and being the continuous thread across
sessions.

---

## Monetization (lightweight, no hosting)

Hosted middleware is dropped. Remaining options, kept minimal:

- **Donations** (Buy Me a Coffee / GitHub Sponsors). Honest expectation: donation conversion is well
  under 1-2%, usually a fraction of that -- coffee money, not a business. A pure external donation
  link is generally App-Store-compatible.
- A **paid app tier** is possible later but must use Apple IAP (15% small-business / 30%) for any
  feature unlock. Not a v1 concern.

The license stays Apache-2.0 regardless.

---

## Open questions

1. **Name.** Working name PlumbAR; alternatives welcome.
2. **Bundle transfer mechanism.** AirDrop vs iCloud Drive vs Files vs cable -- pick the default
   round-trip UX (local-only, no sync server).
3. **Revit version targets.** Which years does the Revit front door support at launch? The legacy
   C# add-in targets 2024-2027; the pyRevit version floor is still open (see
   [`pyrevit-migration-plan.md`](pyrevit-migration-plan.md)).
4. **Minimum iPhone.** Confirm iPhone Pro w/ LiDAR; which generation floor.
5. **Vision model for device typing.** On-device CoreML in the app vs desktop-side in the engine;
   which model; how much it is leaned on given identity stays human-confirmed in v1.
6. **Report format.** PDF vs HTML as the primary deliverable.
7. **Manifest + capture-package schema.** Lock the field list and JSON-Schema before Phase 0 tests.

---

*Working name: PlumbAR (TBD). Last updated: 2026-06-29.*
