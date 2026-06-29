"""LIVE: export per-level floorplans and compute the pixel->model affine.

The second Revit-touching module. Produces the :class:`FloorplanExport` records
the rest of the lib needs (image bytes + stable basename + dims + the 6-element
``pixel_to_model`` affine). The affine is computed from the exported view's crop
box / scale -- this is the trickiest live surface and is validated on hardware.
"""

from __future__ import annotations

import glob
import os
import struct
from typing import List, Sequence

from .manifest_builder import FloorplanExport

# Larger image edge, in pixels. The export budget is spent along the longer crop
# edge (see _native_fit) so the shorter edge follows the crop aspect.
_PIXEL_SIZE = 2400

# PNG 8-byte signature; the IHDR width/height live at byte offsets 16/20.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def export_floorplans(doc, level_ids: Sequence[str]) -> List[FloorplanExport]:  # noqa: ANN001
    """Export a floorplan image per level and compute its affine. LIVE.

    Returns one :class:`FloorplanExport` per level: the rendered plan image as
    **bytes**, a stable **basename** (the relative path the manifest will
    reference and ``bundle_io`` will write), the pixel dimensions, and the
    ``pixel_to_model`` 2x3 row-major affine derived from the view crop box +
    scale so plan pixels map to model XY.

    ``level_ids`` is a sequence of level_id STRINGS (``str(eid_value(level.Id))``).
    When empty, every level that already owns a plan view is exported. One bad
    level is skipped (and counted), never aborting the rest.
    """
    # LIVE: requires Revit. Kept function-local so the module imports under CPython.
    from Autodesk.Revit.DB import (  # noqa: F401  # type: ignore
        BoundingBoxXYZ,  # noqa: F401  (documents the crop-box type we read)
        ImageExportOptions,  # noqa: F401
        Transaction,
        ViewPlan,  # noqa: F401
    )

    from ._compat import eid_value, element_name

    level_map = _level_map(doc)  # level_id str -> Level

    if level_ids:
        requested = list(level_ids)
        create_if_missing = True
    else:
        # Default: only levels that already have a plan view (do not create).
        requested = _levels_with_plan(doc, level_map)
        create_if_missing = False

    tmp_dir = _export_tmp_dir()
    file_stub = os.path.join(tmp_dir, "snap")

    exports: List[FloorplanExport] = []
    skipped = 0

    for level_id in requested:
        level = level_map.get(str(level_id))
        if level is None:
            skipped += 1
            print("ca_elevation_export: no level for id {0!r}; skipped".format(level_id))
            continue

        try:
            view = _find_plan_view(doc, level)
            need_create = view is None
            if need_create and not create_if_missing:
                skipped += 1
                continue

            # Clear stale exports BEFORE the txn so the produced PNG is picked
            # purely by "did not exist before" (mirror vision_render's guard).
            pre_existing = _clear_snap_dir(tmp_dir)

            txn = Transaction(doc, "CA Elevation floorplan export (temp)")
            txn.Start()
            try:
                if need_create:
                    view = _create_plan_view(doc, level)
                    if view is None:
                        raise RuntimeError(
                            "no FloorPlan ViewFamilyType / ViewPlan.Create failed"
                        )
                # CropBoxActive=True makes ExportImage frame the crop extent (not
                # the full view extent), which is what the affine below assumes.
                view.CropBoxActive = True
                view.CropBoxVisible = False
                doc.Regenerate()

                # Read the crop AFTER Regenerate, then capture every value we need
                # as plain floats while the txn is open (the managed XYZ/Transform
                # snapshots are not relied on after RollBack).
                crop = view.CropBox
                tr = crop.Transform
                origin, bx, by = tr.Origin, tr.BasisX, tr.BasisY
                cmin, cmax = crop.Min, crop.Max
                o_x, o_y = float(origin.X), float(origin.Y)
                bx_x, bx_y = float(bx.X), float(bx.Y)
                by_x, by_y = float(by.X), float(by.Y)
                cmin_x, cmax_x = float(cmin.X), float(cmax.X)
                cmin_y, cmax_y = float(cmin.Y), float(cmax.Y)

                width_ft = cmax_x - cmin_x
                height_ft = cmax_y - cmin_y
                fit = _native_fit(width_ft, height_ft, _PIXEL_SIZE)

                opts = _build_export_options(
                    view, file_stub, fit["pixel_size"], fit["fit_horizontal"]
                )
                doc.ExportImage(opts)  # writes the PNG to disk NOW, pre-rollback
            finally:
                txn.RollBack()  # model untouched (crop + any created view undone)

            produced = _newest_png(tmp_dir, exclude=pre_existing)
            if produced is None:
                raise RuntimeError("ExportImage produced no new PNG in " + tmp_dir)

            with open(produced, "rb") as fh:
                image_bytes = fh.read()
            width_px, height_px = _png_dims(image_bytes)

            # AFFINE pixel(px,py top-left, +py DOWN) -> model XY.
            #   u(px) = cmin_x + (px/W)*(cmax_x-cmin_x)
            #   v(py) = cmax_y - (py/H)*(cmax_y-cmin_y)   (y flips: image top = max v)
            #   X = O.X + u*bx.X + v*by.X ;  Y = O.Y + u*bx.Y + v*by.Y
            # collected into X=a*px+b*py+c, Y=d*px+e*py+f. Derived from the ACTUAL
            # PNG W/H (not the requested budget) so a letterboxed export is exact
            # along whichever axis filled. For an un-rotated plan bx=(1,0), by=(0,1):
            # a=(cmax_x-cmin_x)/W, b=0, c=cmin_x, d=0, e=-(cmax_y-cmin_y)/H, f=cmax_y.
            su = width_ft / width_px
            sv = -(height_ft) / height_px
            a = su * bx_x
            b = sv * by_x
            c = o_x + cmin_x * bx_x + cmax_y * by_x
            d = su * bx_y
            e = sv * by_y
            f = o_y + cmin_x * bx_y + cmax_y * by_y

            # CORRECTNESS CAVEAT: the affine assumes the export fills the image
            # with the crop extent at a matching aspect ratio. _native_fit drives
            # the pixel budget down the longer crop edge, so the aspects should
            # match; if they diverge >1% the export letterboxed and one axis of
            # the affine is off (live validation confirms which).
            if width_ft > 0 and height_ft > 0 and width_px > 0 and height_px > 0:
                crop_aspect = width_ft / height_ft
                img_aspect = float(width_px) / float(height_px)
                if abs(crop_aspect - img_aspect) / crop_aspect > 0.01:
                    print(
                        "ca_elevation_export: WARNING level {0} aspect mismatch "
                        "(crop {1:.4f} vs image {2:.4f}); export may be "
                        "letterboxed".format(level_id, crop_aspect, img_aspect)
                    )

            lid = str(eid_value(level.Id))
            exports.append(
                FloorplanExport(
                    level_id=lid,
                    level_name=element_name(level),
                    elevation=level.Elevation,
                    image_bytes=image_bytes,
                    basename="floorplans/level_{0}.png".format(lid),
                    width_px=width_px,
                    height_px=height_px,
                    pixel_to_model=[a, b, c, d, e, f],
                )
            )
        except Exception as exc:  # one bad level must not abort the rest
            skipped += 1
            print(
                "ca_elevation_export: level {0!r} export failed ({1}); "
                "skipped".format(level_id, exc)
            )
            continue

    if skipped:
        print(
            "ca_elevation_export: exported {0} level(s), skipped {1}".format(
                len(exports), skipped
            )
        )
    return exports


# --------------------------------------------------------------------------- #
# Revit lookups (all Revit imports stay function-local).
# --------------------------------------------------------------------------- #


def _level_map(doc):  # noqa: ANN001
    """Map ``str(eid_value(level.Id))`` -> ``Level`` for every level in ``doc``."""
    from Autodesk.Revit.DB import FilteredElementCollector, Level

    from ._compat import eid_value

    out = {}
    for lvl in FilteredElementCollector(doc).OfClass(Level):
        try:
            out[str(eid_value(lvl.Id))] = lvl
        except Exception:
            continue
    return out


def _levels_with_plan(doc, level_map) -> List[str]:  # noqa: ANN001
    """Return level_id strings that own at least one non-template plan view."""
    from Autodesk.Revit.DB import FilteredElementCollector, ViewPlan

    from ._compat import eid_value

    ordered: List[str] = []
    seen = set()
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        try:
            if v.IsTemplate:
                continue
            gen = v.GenLevel
            if gen is None:
                continue
            lid = str(eid_value(gen.Id))
            if lid in level_map and lid not in seen:
                seen.add(lid)
                ordered.append(lid)
        except Exception:
            continue
    return ordered


def _find_plan_view(doc, level):  # noqa: ANN001
    """Find a non-template ViewPlan whose GenLevel is ``level``.

    Prefers a candidate whose name contains the level's name; else the first.
    Returns ``None`` when the level has no plan view.
    """
    from Autodesk.Revit.DB import FilteredElementCollector, ViewPlan

    from ._compat import eid_value, element_name

    target = eid_value(level.Id)
    lvl_name = (element_name(level) or "").strip().lower()

    candidates = []
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        try:
            if v.IsTemplate:
                continue
            gen = v.GenLevel
            if gen is None:
                continue
            if eid_value(gen.Id) == target:
                candidates.append(v)
        except Exception:
            continue

    if not candidates:
        return None
    if lvl_name:
        for v in candidates:
            try:
                if lvl_name in (element_name(v) or "").strip().lower():
                    return v
            except Exception:
                continue
    return candidates[0]


def _floor_plan_vft_id(doc):  # noqa: ANN001
    """ElementId of a FloorPlan ViewFamilyType (for ViewPlan.Create), or None."""
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        ViewFamily,
        ViewFamilyType,
    )

    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if vft.ViewFamily == ViewFamily.FloorPlan:
                return vft.Id
        except Exception:
            continue
    return None


def _create_plan_view(doc, level):  # noqa: ANN001
    """Create a ViewPlan for ``level`` (caller must hold an open transaction)."""
    from Autodesk.Revit.DB import ViewPlan

    vft_id = _floor_plan_vft_id(doc)
    if vft_id is None:
        return None
    return ViewPlan.Create(doc, vft_id, level.Id)


# --------------------------------------------------------------------------- #
# Export mechanics (vendored minimal logic from Sterling vision_render.py;
# Sterling is NOT importable at runtime here -- different sys.path).
# --------------------------------------------------------------------------- #


def _build_export_options(view, file_stub, pixel_size, fit_horizontal):  # noqa: ANN001
    """Construct ``ImageExportOptions`` for a single view -> PNG.

    The fit direction follows the longer crop edge so ``PixelSize`` is spent on
    that edge; the shorter edge then follows the crop aspect.
    """
    from Autodesk.Revit.DB import (
        ExportRange,
        FitDirectionType,
        ImageExportOptions,
        ImageFileType,
        ImageResolution,
        ZoomFitType,
    )
    from System.Collections.Generic import List as NetList

    opts = ImageExportOptions()
    opts.FilePath = file_stub
    opts.ExportRange = ExportRange.SetOfViews
    views = NetList[type(view.Id)]()
    views.Add(view.Id)
    opts.SetViewsAndSheets(views)
    opts.ImageResolution = ImageResolution.DPI_150
    opts.ZoomType = ZoomFitType.FitToPage
    opts.PixelSize = int(pixel_size)
    opts.FitDirection = (
        FitDirectionType.Horizontal if fit_horizontal else FitDirectionType.Vertical
    )
    opts.HLRandWFViewsFileType = ImageFileType.PNG
    # Pre-2026 ImageExportOptions may lack ShadingViewsFileType; plans are
    # hidden-line so it only matters for shaded 3D views.
    if hasattr(opts, "ShadingViewsFileType"):
        opts.ShadingViewsFileType = ImageFileType.PNG
    return opts


def _native_fit(width, height, pixel_size):
    """Pick (fit_horizontal, pixel_size) so the budget rides the longer edge.

    Raises ``ValueError`` on non-positive extents (an inactive or collapsed crop
    box -- the caller skips that level rather than exporting a degenerate frame).
    """
    if width <= 0 or height <= 0:
        raise ValueError(
            "crop extents must be positive, got {0!r} x {1!r} "
            "(inactive or collapsed crop box?)".format(width, height)
        )
    return {"fit_horizontal": width >= height, "pixel_size": int(pixel_size)}


def _export_tmp_dir():
    """Return (creating if needed) ``%LOCALAPPDATA%\\ca_elevation_export\\render_tmp``."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "ca_elevation_export", "render_tmp")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _clear_snap_dir(tmp_dir):
    """Remove prior ``snap*`` exports, then return surviving PNGs.

    The produced PNG is later picked from files that did NOT exist before the
    export, so a locked leftover can never be served as the current render.
    """
    for old in glob.glob(os.path.join(tmp_dir, "snap*")):
        try:
            os.remove(old)
        except Exception:
            pass  # locked/gone; the new-file diff excludes it anyway
    return set(glob.glob(os.path.join(tmp_dir, "*.png")))


def _newest_png(folder, exclude=None):
    """Most recently modified PNG in ``folder`` not in ``exclude``, or None."""
    skip = exclude or set()
    pngs = [p for p in glob.glob(os.path.join(folder, "*.png")) if p not in skip]
    if not pngs:
        return None
    return max(pngs, key=os.path.getmtime)


def _png_dims(data):
    """Parse (width, height) from a PNG IHDR header without PIL.

    Signature is 8 bytes; the IHDR chunk's width is a big-endian uint32 at byte
    offset 16 and height at offset 20.
    """
    if len(data) < 24 or data[:8] != _PNG_SIGNATURE:
        raise ValueError("not a PNG (bad signature)")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)
