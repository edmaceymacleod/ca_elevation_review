# Handoff — CA Elevation Review (live Revit work)

The LIVE-stub work from branch `claude/ca-elevation-live-revit-stubs` is merged into `main`. The write-back solid-fill fix is merged (#15). **All remaining to-do items (1–3, 5) are now live-validated against a real workshared production model on Revit 2025** (read-only extract + rolled-back write-back + the real `lib`/engine on the PC; model never saved/synced, left `IsModified == false`). Full sanitized evidence: `docs/live-validation-2026-06-29.md` (Part 2). pyRevit pin resolved in `docs/pyrevit-migration-plan.md` (Open item 1).

## What's done
- The 5 `NotImplementedError` LIVE stubs are implemented + adversarially reviewed (all `py_compile` clean): `revit_extract` (`extract_project`, `extract_devices`), `revit_export` (`export_floorplans` + `pixel_to_model` affine), `revit_writeback` (`apply_verdicts`, `clear_prior_overrides`).
- `ExportBundle` pushbutton: real `forms.SelectFromList` level picker + `level_lookup`.
- New `lib/ca_elevation_revit/_compat.py`: vendored ElementId shims (`eid_value`/`make_eid`) from Sterling, for Revit 2025/2026 safety.
- **Validated live (PASS):** `extract_project`; floorplan export pipeline; the affine (asymmetric crop → 1200×720, no letterbox, corners round-trip exact). Confirms Revit 2025 `ExportImage` preserves crop aspect when `FitDirection` follows the longer edge, so the simple affine is exact.
- **Write-back fill gap fixed and validated** (merged #15): `revit_writeback._build_override` resolves a solid `FillPatternElement` from the doc (`_solid_fill_pattern_id`, resolved once per apply) and sets it as the surface + cut foreground pattern id, so verdict colours render as filled surfaces in 3D/section — not just plan-line colour. Prefers a drafting-target solid fill; falls back to any solid; tests `IsSolidFill` (not the localised `"<Solid fill>"` name). Fail-soft: a model with no solid pattern warns and keeps the colour-only override. **Live-validated at the API level (2026-06-29):** on real overridable elements in a `View3D`, the readback `SurfaceForegroundPatternId` equals the resolved solid pattern with `IsSurfaceForegroundPatternVisible == True` (6/6). A committable visual screenshot on a lightweight fixture is the only remaining bit.

## To do next

Items 1–3 and 5 are **DONE** — live-validated 2026-06-29 against a real
production model (sanitized evidence in `docs/live-validation-2026-06-29.md`
Part 2). Summary:

1. ~~`extract_devices` against real devices~~ **DONE** — 2,658 devices;
   **UniqueId round-trip 2,658/2,658**; level fallback exercised hard (2,128 via
   `SCHEDULE_LEVEL_PARAM`); position point+bbox; orientation 2,658/2,658.
2. ~~`revit_writeback` idempotency~~ **DONE (API-level)** — apply / clear-by-marker /
   **drop-a-device** / rollback all confirmed on real elements; solid surface fill
   confirmed (`SurfaceForegroundPatternId == solid`, visible). Visual screenshot →
   item A below.
3. ~~Full `ExportBundle` end-to-end~~ **DONE** — real `lib`
   `build_manifest`/`write_field_bundle` over 60 real devices → real engine run
   (rc 0) → `writeback` mapping (all 4 verdicts, 0 sentinel, ids = real UniqueIds).
5. ~~pyRevit pin / CPython floor~~ **DONE** — pin ≥ **6.1.0** (machine on
   6.1.0.26047); #3092 fixed from 6.1.0 (PR #3098); bundled CPython **3.12.3**;
   `lib/` 3.8 lint floor kept. See migration plan Open item 1.

**Still open (small / acceptable):**

- **A. Committable solid-fill screenshot** on a lightweight, client-data-free
  seeded fixture — the visual eyeball for item 2 (API-confirmed already). Needs a
  free Revit instance (the production session held port 48884 during validation).
  A reusable device-seeding helper can build that fixture from any base model.
- **B. Minor caveats** (acceptable, documented): curve/line-based devices fall
  back to bbox-centre z (skews derived mounting height by half the extent), 2 seen
  in the real model; `up_axis` hardcoded `'up'`.

## How to bring the environment up (MCP deadlock gotcha)
`revit_mcp` discovery probes `GET /revit_mcp/status/`, which **503s when no document is open** — so every MCP tool (incl. `open_document`) fails discovery on a freshly launched, empty Revit. Break the deadlock by POSTing straight to the Routes server (port is open even with no doc):
```
POST http://127.0.0.1:48884/revit_mcp/open_document/   body: {"file_path": "C:\\...\\model.rvt"}
```
Once a doc is open, `/status/` flips to `active` and the normal MCP tools work. Run model-mutating validation inside a `Transaction` you **roll back** (the export pattern) to keep the fixture clean.
