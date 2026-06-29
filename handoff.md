# Handoff — CA Elevation Review (live Revit work)

Branch: `claude/ca-elevation-live-revit-stubs`. Last validated on Revit 2025 (Windows + pyRevit Routes/`revit_mcp`) on 2026-06-29. Full evidence: `docs/live-validation-2026-06-29.md`.

## What's done
- The 5 `NotImplementedError` LIVE stubs are implemented + adversarially reviewed (all `py_compile` clean): `revit_extract` (`extract_project`, `extract_devices`), `revit_export` (`export_floorplans` + `pixel_to_model` affine), `revit_writeback` (`apply_verdicts`, `clear_prior_overrides`).
- `ExportBundle` pushbutton: real `forms.SelectFromList` level picker + `level_lookup`.
- New `lib/ca_elevation_revit/_compat.py`: vendored ElementId shims (`eid_value`/`make_eid`) from Sterling, for Revit 2025/2026 safety.
- **Validated live (PASS):** `extract_project`; floorplan export pipeline; the affine (asymmetric crop → 1200×720, no letterbox, corners round-trip exact). Confirms Revit 2025 `ExportImage` preserves crop aspect when `FitDirection` follows the longer edge, so the simple affine is exact.

## To do next (needs a populated production model)
1. **`extract_devices` against real devices** — confirm UniqueId / family / type / level / position / orientation, and the level-parameter fallbacks. The test fixture (`FIXTEST_AVX_R25`) has 0 placed devices, so this path ran clean but extracted nothing.
2. **`revit_writeback` idempotency** — `apply_verdicts` + `clear_prior_overrides` on real overridable elements, incl. the **drop-a-device** case (device removed from the new report must lose its colour).
3. **Fix minor write-back gap** (review-flagged): `_build_override` sets surface pattern *visible + color* but no solid `FillPatternId`, so surface fill won't render in 3D/section (plan line colour is fine). Needs a live `doc` to resolve a solid `FillPatternElement` id.
4. **Full `ExportBundle` end-to-end** on a real model: level picker → `build_manifest` → `bundle_io.write_field_bundle`, then run the engine over the bundle.
5. Minor caveats (acceptable, documented): curve/line-based devices fall back to bbox-centre z (skews derived mounting height by half the extent); `up_axis` hardcoded `'up'`.
6. Open migration item: pin a pyRevit release unaffected by issue #3092 (6.0.0 routing defect) and confirm the CPython 3.8 floor.

## How to bring the environment up (MCP deadlock gotcha)
`revit_mcp` discovery probes `GET /revit_mcp/status/`, which **503s when no document is open** — so every MCP tool (incl. `open_document`) fails discovery on a freshly launched, empty Revit. Break the deadlock by POSTing straight to the Routes server (port is open even with no doc):
```
POST http://127.0.0.1:48884/revit_mcp/open_document/   body: {"file_path": "C:\\...\\model.rvt"}
```
Once a doc is open, `/status/` flips to `active` and the normal MCP tools work. Run model-mutating validation inside a `Transaction` you **roll back** (the export pattern) to keep the fixture clean.
