"""LIVE: export per-level floorplans and compute the pixel->model affine.

The second Revit-touching module. Produces the :class:`FloorplanExport` records
the rest of the lib needs (image bytes + stable basename + dims + the 6-element
``pixel_to_model`` affine). The affine is computed from the exported view's crop
box / scale -- this is the trickiest live surface and is validated on hardware.
"""

from __future__ import annotations

from typing import List, Sequence

from .manifest_builder import FloorplanExport


def export_floorplans(doc, level_ids: Sequence[str]) -> List[FloorplanExport]:  # noqa: ANN001
    """Export a floorplan image per level and compute its affine. LIVE.

    Returns one :class:`FloorplanExport` per level: the rendered plan image as
    **bytes**, a stable **basename** (the relative path the manifest will
    reference and ``bundle_io`` will write), the pixel dimensions, and the
    ``pixel_to_model`` 2x3 row-major affine derived from the view crop box +
    scale so plan pixels map to model XY.
    """
    # LIVE: requires Revit.
    from Autodesk.Revit.DB import (  # noqa: F401  # type: ignore
        ImageExportOptions,
        ViewPlan,
    )

    raise NotImplementedError(
        "LIVE: for each level, find/duplicate a ViewPlan, ImageExportOptions -> PNG "
        "bytes, read crop box + scale to build pixel_to_model [a,b,c,d,e,f] mapping "
        "plan pixel -> model XY, and return FloorplanExport(level_id, level_name, "
        "elevation, image_bytes, basename, width_px, height_px, pixel_to_model). "
        "Validate the affine on Ed's hardware (this is the trickiest live surface)."
    )
