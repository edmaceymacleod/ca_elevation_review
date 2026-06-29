"""Pure pixel->model affine assembly (extracted from revit_export).

Given the plain float crop-box values revit_export already snapshots while a
Revit transaction is open, build the 6-element [a,b,c,d,e,f] row-major affine
the spec-manifest schema wants. No Revit import -- fully headless-testable.
"""

from __future__ import annotations

import math
from typing import List, Tuple


def build_pixel_to_model(
    *,
    origin_x,  # noqa: ANN001
    origin_y,  # noqa: ANN001
    basis_x: Tuple[float, float],  # crop BasisX (x, y)
    basis_y: Tuple[float, float],  # crop BasisY (x, y)
    crop_min_x,  # noqa: ANN001
    crop_max_x,  # noqa: ANN001
    crop_min_y,  # noqa: ANN001
    crop_max_y,  # noqa: ANN001
    width_px,  # noqa: ANN001
    height_px,  # noqa: ANN001
) -> List[float]:
    """Return [a,b,c,d,e,f] mapping pixel (px,py top-left, +py DOWN) -> model XY.

    Mirrors the math currently inlined in revit_export.export_floorplans
    (revit_export.py:136-143), operand-for-operand and in the same order::

        su = (crop_max_x - crop_min_x) / width_px
        sv = -(crop_max_y - crop_min_y) / height_px   # image top = max v (y flip)
        a = su * bx_x ; b = sv * by_x ; c = origin_x + crop_min_x*bx_x + crop_max_y*by_x
        d = su * bx_y ; e = sv * by_y ; f = origin_y + crop_min_x*bx_y + crop_max_y*by_y

    Raises ``ValueError`` on non-positive extents/pixels or non-finite inputs.
    """
    bx_x, bx_y = basis_x
    by_x, by_y = basis_y

    for value, what in (
        (origin_x, "origin_x"),
        (origin_y, "origin_y"),
        (bx_x, "basis_x[0]"),
        (bx_y, "basis_x[1]"),
        (by_x, "basis_y[0]"),
        (by_y, "basis_y[1]"),
        (crop_min_x, "crop_min_x"),
        (crop_max_x, "crop_max_x"),
        (crop_min_y, "crop_min_y"),
        (crop_max_y, "crop_max_y"),
        (width_px, "width_px"),
        (height_px, "height_px"),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{what} must be a finite number, got {value!r}")

    if width_px <= 0:
        raise ValueError(f"width_px must be positive, got {width_px!r}")
    if height_px <= 0:
        raise ValueError(f"height_px must be positive, got {height_px!r}")
    if crop_max_x <= crop_min_x:
        raise ValueError(
            f"crop extent x must be positive, got min={crop_min_x!r} max={crop_max_x!r}"
        )
    if crop_max_y <= crop_min_y:
        raise ValueError(
            f"crop extent y must be positive, got min={crop_min_y!r} max={crop_max_y!r}"
        )

    su = (crop_max_x - crop_min_x) / width_px
    sv = -(crop_max_y - crop_min_y) / height_px
    a = su * bx_x
    b = sv * by_x
    c = origin_x + crop_min_x * bx_x + crop_max_y * by_x
    d = su * bx_y
    e = sv * by_y
    f = origin_y + crop_min_x * bx_y + crop_max_y * by_y
    return [a, b, c, d, e, f]
