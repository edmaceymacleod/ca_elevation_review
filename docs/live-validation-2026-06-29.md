# Live validation on Revit 2025 — 2026-06-29

First validation of the LIVE `revit_*` surfaces on real hardware (Windows + Revit
2025 + pyRevit Routes/`revit_mcp`). Until now these were stubbed because the dev
environment was Linux with no Revit. Driven via the pyRevit Routes API on
`localhost:48884` (Sterling `revit_mcp` extension).

## Environment
- Revit **2025** (`Autodesk Revit 2025`), API year 2025, .NET 8.
- Model: `sterlingrevittools/tests/fixtures/FIXTEST_AVX_R25.rvt` (a Sterling
  view/filter fixture — 7 levels, 62 views, **no placed building geometry or
  low-voltage devices**). Good enough for the export/affine/project surfaces;
  device extraction + write-back need a populated model (production model pending).
- MCP execution context is IronPython 2.7 (`/revit_mcp/execute_code/`); the
  production extension targets pyRevit CPython 3.8. API surface is the same.

## Gotcha found & fixed: MCP discovery deadlock (no open document)
`revit_mcp` discovery probes `GET /revit_mcp/status/`, which returns **503**
unless an active document is open (`status.py`: `if doc:` → else 503). With Revit
launched to the home screen (no doc), every MCP tool — including `open_document`
— failed discovery (`instance_registry.parse_status` drops any instance whose
`status != "active"`). Chicken-and-egg.

**Break the deadlock** by POSTing straight to the Routes server (the port is open
even with no doc), to the `/open_document/` route, which uses
`revit.HOST_APP.uiapp` and is explicitly written for the `uidoc is None` case:

```
POST http://127.0.0.1:48884/revit_mcp/open_document/
{"file_path": "C:\\...\\model.rvt"}
```

Once a document is open, `/status/` flips to `"active"` and normal MCP tools work.

## Results

### `extract_project(doc)` — PASS
```
{'id': '651f74a4-...-00008bf0',   # doc.ProjectInformation.UniqueId
 'name': 'Project Name',          # ProjectInformation.Name (fallback doc.Title)
 'units': 'feet',                 # internal units; we emit raw internal-feet coords
 'revit_file': 'C:\\...\\FIXTEST_AVX_R25.rvt'}
```
Decision confirmed: do **not** touch `DisplayUnitType` (legacy) — Revit internal
units are always feet, and we emit internal-feet coordinates, so `units="feet"`
is correct by construction.

### Floorplan export + `pixel_to_model` affine — PASS (the trickiest surface)
Method: on a real `ViewPlan`, inside a `Transaction` that is **rolled back**, set
an asymmetric crop, `Regenerate()`, `doc.ExportImage(opts)` (PNG persists on disk
during the open txn), then roll back so the model is untouched (Sterling
`vision_render` pattern). PNG dims read from the IHDR header (`struct.unpack('>II',
data[16:24])`) — no PIL dependency.

- Crop: local x ∈ [-50, 50], y ∈ [-30, 30] ft (asymmetric, to catch an axis swap).
- `ImageExportOptions`: `ZoomFitType.FitToPage`, `PixelSize=1200`,
  `FitDirection=Horizontal` (longer edge), `HLRandWFViewsFileType=PNG`.
- **Exported PNG: 1200 × 720.**  crop_aspect 1.6667 == img_aspect 1.6667 →
  **no letterbox.**

Affine `[a,b,c,d,e,f]` with `X=a*px+b*py+c, Y=d*px+e*py+f`
(px,py top-left origin, +py down):
```
[0.08333, 0.0, -50.0,  0.0, -0.08333, 30.0]
  a = (cmax.X-cmin.X)/W   b = 0   c = cmin.X
  d = 0   e = -(cmax.Y-cmin.Y)/H   f = cmax.Y
px(0,0)     -> (-50.0,  30.0)   ✓
px(W,H)     -> ( 50.0, -30.0)   ✓
px(W/2,H/2) -> (  0.0,   0.0)   ✓
```

**Key finding:** Revit 2025 `ExportImage` with `FitDirection` following the longer
crop edge fills the image with the crop extent at matching aspect ratio (no
letterbox), so the simple axis-aligned affine derivation is exact. For a rotated
plan (project-north / rotated scope box) use the full `CropBox.Transform` basis
form (already specified in `revit_export.py`); this fixture's basis is identity.

### `extract_devices(doc, level_lookup)` — collector runs clean, 0 devices here
Walked `OST_SecurityDevices, OST_CommunicationDevices, OST_ElectricalFixtures,
OST_AudioVisualDevices, OST_DataDevices, OST_NurseCallDevices,
OST_FireAlarmDevices, OST_TelephoneDevices` — all categories resolve on R2025, **0
instances** in this fixture (it has none placed). Path executes without error.
**Needs a populated production model to validate UniqueId / family / type / level
/ position / orientation extraction.**

### `revit_writeback` (apply/clear idempotency) — NOT yet validated live
Needs real overridable elements (this fixture has no geometry). Pending the
production model.

## ElementId on Revit 2025 (confirmed)
`ElementId.Value` (Int64) is present and is the right accessor on 2025;
`int(eid.Value)` works. Vendored `lib/ca_elevation_revit/_compat.py`
(`eid_value` / `make_eid`) mirrors Sterling `revit_compat` for 2025/2026 safety.

## Still to do (needs production model)
- [ ] `extract_devices` against real low-voltage devices (UniqueId identity invariant).
- [ ] `revit_writeback.apply_verdicts` + `clear_prior_overrides` idempotency incl.
      the drop-a-device case (resolve by `doc.GetElement(UniqueId)`, OverrideGraphicSettings,
      marker via Comments sentinel).
- [ ] Full `ExportBundle` end-to-end (level picker → manifest → bundle) on a real model.
