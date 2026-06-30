# todo.md — Pre-Mac backlog (CA Elevation Review)

Prioritized, **Mac-independent** work to bank on the Windows PC before the next
Mac/device session. Source: 6-surface read-only inventory (2026-06-30). Each item
is a discrete unit — **request planning before implementing** (one at a time).

**Legend:** effort `S`/`M`/`L` · value `high`/`med`/`low` · 🔒 = firewall-sensitive
(disposable **Sterling fixture only — never a production model**; mutate-then-rollback;
sanitize any committed evidence) · ⚙️ = touches `.github/workflows/` (needs `workflow`
scope to merge: `gh auth refresh -h github.com -s workflow`, or web UI).

---

## ✅ Status — 2026-06-30 (this PC session)

**Shipped (merged to `main`):**
- **T1.1** Swift kit data-contract hardening — #41
- **T1.2** engine-not-found guard in pushbuttons — #40
- **T1.4 + T3.5** device-type heuristic + empty-string guard — #42
- **T3.4** curve/line device-location fallback — #43
- **T3.6** ICP high-residual threshold → config — #44
- **T3.1** `docs/sessions/` record template — #39
- **T2.2 / T2.3 / T2.4** Tier-2 design decisions resolved — #45
  (product-taste forks marked **"RECOMMENDATION (pending owner sign-off)"**)
- **T1.3** 🔒 write-back disk-persistence idempotency cycle — **validated PASS** (this PR;
  evidence in `docs/sessions/2026-06-30-writeback-disk-persistence-cycle.md`)

**Remaining (⚙️ workflow-scope — won't auto-merge without `workflow` token scope; manual merge):**
- **T3.2** CI job exercising the PDF→HTML fallback
- CI follow-ups: promote the Windows kit leg to gating · pin the SwiftLint version

**Awaiting owner sign-off (trivially reversible doc decisions in `design.md` / ADRs):** Revit-2024
best-effort grade (T2.4) · bundle-transfer default + PDF-primary (T2.2) · defer the pyRevit settings
GUI (T2.3 §6).

**Frozen / deferred:** **T2.1** (C# stub freeze — GPL3 gate) · **T3.3** (icons — C# half frozen,
pyRevit half needs assets). Mac-gated items unchanged.

---

## Tier 1 — Do before the Mac (high leverage)

### ☐ T1.1 — Kit data-contract hardening ⟨M · high · no Mac⟩
The Swift kit is the data contract the iOS app builds on; lock it now so the Mac
session is pure app/capture work, not chasing decode bugs.
- **Files:** `ios-app/Sources/CaElevationKit/{CapturePackage,FieldBundle,Affine,BundleIO}.swift`;
  `ios-app/Tests/CaElevationKitTests/{CapturePackageTests,FieldBundleTests,JSONValueTests,AffineTests}.swift`
- **Subtasks:**
  - [ ] **Fix silent default-value divergence (real latent bug).** Schema defaults
    `Pin.confidence="medium"` (`CapturePackage.swift:168` / engine `models.py:333`) and
    `Orientation.upAxis="up"` (`FieldBundle.swift:247` / engine `models.py:97`) are applied
    by the *engine* on decode but the Swift kit leaves them optional with no explicit
    default. Works today only by coincidence; drift/round-trip → silent mismatch the
    `xlang_schema` CI check can't catch (it validates structure, not default semantics).
    Make the kit apply the defaults explicitly to match the engine.
  - [ ] **Adversarial decode tests:** pose array length ≠16; intrinsics `fx/fy ≤ 0`;
    `depth_size` bounds (`[h,w]`, exactly 2, `>0`); empty `shots` (`minItems:1`);
    `Pin.Confidence` bad enum; `schema_version` semver pattern; ID `minLength:1`
    (`project_id`/`shot.id`/`level.id`/`device.id`); `depth_map`→`depth_size` dependency
    (kit currently doesn't enforce); minimal round-trips (`CapturePackage`/`SpecManifest`
    with all optionals nil); `JSONValue` encode→decode round-trip; `Affine` det≈`1e-12`
    boundary.
- **Acceptance:** `swift test` green; `pwsh -File ios-app/scripts/win-swiftlint.ps1` clean;
  malformed payloads rejected (add runtime validation where Codable can't enforce, e.g. the
  depth dependency / minLength).

### ☐ T1.2 — Engine-not-found guard in the pyRevit pushbuttons ⟨S (~1–2h) · high · no Mac⟩
Today a mis-located engine venv makes the buttons silently return "success" with no
colours — a user burns an hour on a config problem. Load-bearing onboarding fix.
- **Files:** `pyrevit-extension/CaElevationReview.extension/.../ExportBundle.pushbutton/script.py`,
  `.../ImportCaptures.pushbutton/script.py`, `.../lib/.../engine_runner.py`
- **Subtasks:**
  - [ ] Extract a reusable `engine_runner.can_locate_engine()` (or `locate_engine()`)
    check (fallback order: explicit path → `CA_ELEVATION_ENGINE` env → bundled
    `engine-venv` → PATH).
  - [ ] Pre-flight it in both `script.py` entry points *before* writing the bundle /
    running the engine; on failure `forms.alert(...)` with a remediation hint + early exit.
- **Acceptance:** misconfigured/absent engine → clear alert + early exit (not silent
  no-colours); engine-free lib tests still pass. (This is the *code* half of T2.3.)

### ☐ T1.3 — Writeback disk-persistence idempotency cycle 🔒 ⟨M · high · no Mac⟩
The last real Phase-1 ship gap. API-level writeback (apply / clear-by-marker / drop-a-device
/ re-import) is validated, but only via a **rolled-back** transaction. The true
disk-persistence cycle is unproven.
- **Files:** `pyrevit-extension/.../lib/ca_elevation_revit/revit_writeback.py`;
  acceptance criteria in `docs/live-validation-2026-06-29.md:141-166`
- **Cycle:** open fixture → import #1 → **save** → close → reopen → import #2 (modified
  report) → verify no stale overrides/markers.
- **🔒 Firewall:** the *save* step is exactly why this MUST run on a disposable Sterling
  fixture, never a production model. Sanitize any committed evidence. Drive via `revitmcp`
  + Revit 2025.

### ☐ T1.4 — Device-type detection heuristic ⟨S–M · high · no Mac⟩
The `TYPE_MISMATCH` verdict path is fully wired but never fires (no backend populates
`detected_type`). A simple heuristic validates the dormant pipeline end-to-end now.
- **Files:** `engine/src/ca_elevation_engine/verdict.py:34-95`, `models.py:359-381`
- **Do:** plug a family-substring (or similar) heuristic returning `detected_type` +
  `type_confidence` so `TYPE_MISMATCH` can fire; add a fixture/scenario that exercises it.
  (The full vision backend — CoreML/YOLO/API — is `L` and partly Mac-gated; **out of scope**
  here.)

---

## Tier 2 — Decisions / freezes (cheap; prevent wasted work)

### ☐ T2.1 — FREEZE C# `revit-addin/` stub work until the retirement gate resolves ⟨decision⟩
Retirement is gated on **GPL3 counsel sign-off** (is the in-process pyRevit extension a
derivative work of the GPLv3 host? is a closed-source commercial Revit front-door viable?).
Until that's answered, do **not** complete the C# stubs (file dialogs, manifest extraction,
verdict writeback) — they may be deleted. Refs: `docs/pyrevit-migration-plan.md:720-729`,
`docs/design.md` Section 8.

### ☐ T2.2 — Resolve the two device-free product questions ⟨decision · no Mac⟩
- [ ] Bundle-transfer UX default (AirDrop / iCloud / Files / cable) — `docs/design.md` open #1
- [ ] Report format: PDF primary vs HTML — `docs/design.md` open #5

### ☐ T2.3 — Settle settings storage + engine-venv provisioning (design) ⟨M · high · no Mac⟩
"The central onboarding-friction question" — where the engine path/venv is configured
(pyRevit config vs repo settings file) and how users provision the venv.
`docs/pyrevit-migration-plan.md:731-738`. (T1.2 is the code guard; this is the design call.)

### ☐ T2.4 — Resolve Revit version-target floor ⟨M · no Mac⟩
Which Revit years (2024–2027) the extension must support at Phase-1 launch; couples to the
CI matrix. `docs/design.md:315-316` + migration plan.

---

## Tier 3 — Hygiene quick wins (no Mac)

- ☐ **T3.1** Create the missing `docs/sessions/README.md` template (referenced by
  `ios-app/CLAUDE.md:50`, absent) — the formal cross-session record format. `S`
- ☐ **T3.2** ⚙️ Add a CI job that omits the `[report]` extra so the PDF→HTML fallback
  (`engine/src/ca_elevation_engine/report/pdf.py:38-45`) is actually exercised. `S`
- ☐ **T3.3** Real button icons: pyRevit 3× pushbuttons + C# ribbon (`revit-addin/.../App.cs:85`). `S`
- ☐ **T3.4** Curve/line device-location fallback (currently bbox-centre for 0.07% of
  devices) — specialize or document in metadata. `revit_extract.py:150-165`. `S`, data quality.
- ☐ **T3.5** Explicit empty-string `detected_type` guard + document the `None`=absent /
  `""`=failed / `str`=detected semantics. `verdict.py:78-95`. `S`
- ☐ **T3.6** (optional) Root `CLAUDE.md` orientation guide; move ICP `HIGH_RESIDUAL_FT`
  (hardcoded `0.25`) to config (`engine/.../register.py:137-205`).

**Known CI follow-ups (already in `handoff.md`, ⚙️ workflow-scope merges):**
- ☐ Promote the informational Windows kit CI leg to gating once stable over several runs.
- ☐ Pin the SwiftLint version in CI (`brew install` floats) for true local↔CI parity.

---

## Save for the Mac (do NOT start on Windows)

- ☐ iOS ARFrame/LiDAR capture — 3 device-only TODOs: `ARCaptureSession.swift:83,236`
  (sceneDepth setup, live RGB pixel-buffer grab) + `CaptureView.swift:103` (ARView render).
  Needs a real LiDAR iPhone; simulator has no depth.
- ☐ iPhone-generation floor — `docs/design.md` open #3 (needs device).
- ☐ On-device CoreML vision placement — `docs/design.md` open #4 (needs device).

---

## Already done (context — no action)

- **Engine core:** all 5 pipeline stages, CLI, reports (PDF/HTML/JSON), point-cloud
  registration + ICP — 7 fixtures, zero skipped tests.
- **Live-Revit LIVE tier:** extract / export-floorplans / writeback all *API*-validated on
  the 2026-06-30 run (rolled-back on a production model; the disk-persistence cycle remains
  → **T1.3**).
- **This session:** root `.gitattributes` (LF) + `win-swiftlint.ps1` parity (#35);
  Dependabot `github-script` v7→v9 (#29, validated by #35's auto-merge).
