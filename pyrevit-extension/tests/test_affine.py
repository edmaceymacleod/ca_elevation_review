"""affine: pure pixel->model assembly (FLOOR) + engine geometry round-trip (ENGINE).

The pure builder/raise tests need no engine and run everywhere. The geometry
round-trip tests import ``ca_elevation_engine`` *inside the function* and are
marked ``engine`` (numpy + 3.10+ syntax in geometry.py).
"""

from __future__ import annotations

import pytest
from ca_elevation_revit.affine import build_pixel_to_model


# --- FLOOR (no engine) --------------------------------------------------- #
def test_identity_unrotated_plan():
    affine = build_pixel_to_model(
        origin_x=0.0,
        origin_y=0.0,
        basis_x=(1.0, 0.0),
        basis_y=(0.0, 1.0),
        crop_min_x=0.0,
        crop_max_x=10.0,
        crop_min_y=0.0,
        crop_max_y=8.0,
        width_px=1000,
        height_px=800,
    )
    a, b, c, d, e, f = affine
    assert a == 0.01
    assert b == 0.0
    assert c == 0.0
    assert d == 0.0
    assert e == -0.01
    assert f == 8.0


def _forward(affine, px, py):
    a, b, c, d, e, f = affine
    return (a * px + b * py + c, d * px + e * py + f)


def test_y_axis_is_flipped():
    affine = build_pixel_to_model(
        origin_x=0.0,
        origin_y=0.0,
        basis_x=(1.0, 0.0),
        basis_y=(0.0, 1.0),
        crop_min_x=0.0,
        crop_max_x=10.0,
        crop_min_y=0.0,
        crop_max_y=8.0,
        width_px=1000,
        height_px=800,
    )
    # top-left pixel -> model y == crop_max_y
    _, y_top = _forward(affine, 0, 0)
    assert abs(y_top - 8.0) < 1e-9
    # bottom-left pixel -> model y == crop_min_y
    _, y_bot = _forward(affine, 0, 800)
    assert abs(y_bot - 0.0) < 1e-9


def test_nonpositive_extent_raises():
    with pytest.raises(ValueError):
        build_pixel_to_model(
            origin_x=0.0,
            origin_y=0.0,
            basis_x=(1.0, 0.0),
            basis_y=(0.0, 1.0),
            crop_min_x=5.0,
            crop_max_x=5.0,
            crop_min_y=0.0,
            crop_max_y=8.0,
            width_px=1000,
            height_px=800,
        )


def test_nonpositive_pixels_raises():
    with pytest.raises(ValueError):
        build_pixel_to_model(
            origin_x=0.0,
            origin_y=0.0,
            basis_x=(1.0, 0.0),
            basis_y=(0.0, 1.0),
            crop_min_x=0.0,
            crop_max_x=10.0,
            crop_min_y=0.0,
            crop_max_y=8.0,
            width_px=0,
            height_px=800,
        )


def test_nonfinite_input_raises():
    with pytest.raises(ValueError):
        build_pixel_to_model(
            origin_x=float("nan"),
            origin_y=0.0,
            basis_x=(1.0, 0.0),
            basis_y=(0.0, 1.0),
            crop_min_x=0.0,
            crop_max_x=10.0,
            crop_min_y=0.0,
            crop_max_y=8.0,
            width_px=1000,
            height_px=800,
        )


def test_matches_legacy_inline_math():
    # Rotated basis (90 deg) + non-zero origin + non-trivial crop.
    o_x, o_y = 3.0, -2.0
    bx_x, bx_y = 0.0, 1.0
    by_x, by_y = -1.0, 0.0
    cmin_x, cmax_x = 1.0, 13.0
    cmin_y, cmax_y = 2.0, 9.0
    width_px, height_px = 1200, 700

    # EXACT legacy expressions copied from revit_export.py:136-143.
    width_ft = cmax_x - cmin_x
    height_ft = cmax_y - cmin_y
    su = width_ft / width_px
    sv = -(height_ft) / height_px
    a = su * bx_x
    b = sv * by_x
    c = o_x + cmin_x * bx_x + cmax_y * by_x
    d = su * bx_y
    e = sv * by_y
    f = o_y + cmin_x * bx_y + cmax_y * by_y

    affine = build_pixel_to_model(
        origin_x=o_x,
        origin_y=o_y,
        basis_x=(bx_x, bx_y),
        basis_y=(by_x, by_y),
        crop_min_x=cmin_x,
        crop_max_x=cmax_x,
        crop_min_y=cmin_y,
        crop_max_y=cmax_y,
        width_px=width_px,
        height_px=height_px,
    )
    assert affine == [a, b, c, d, e, f]


# --- ENGINE round-trip (3.10+, geometry) --------------------------------- #
@pytest.mark.engine
def test_affine_round_trips_through_engine_geometry():
    from ca_elevation_engine import geometry

    affine = build_pixel_to_model(
        origin_x=3.0,
        origin_y=-2.0,
        basis_x=(0.0, 1.0),
        basis_y=(-1.0, 0.0),
        crop_min_x=1.0,
        crop_max_x=13.0,
        crop_min_y=2.0,
        crop_max_y=9.0,
        width_px=1200,
        height_px=700,
    )
    for px, py in [(0, 0), (600, 350), (1200, 700), (123, 456)]:
        x, y = geometry.pixel_to_model_xy(affine, px, py)
        rpx, rpy = geometry.model_xy_to_pixel(affine, x, y)
        assert abs(rpx - px) < 1e-6
        assert abs(rpy - py) < 1e-6


@pytest.mark.engine
def test_affine_scale_is_units_per_pixel():
    from ca_elevation_engine import geometry

    affine = build_pixel_to_model(
        origin_x=0.0,
        origin_y=0.0,
        basis_x=(1.0, 0.0),
        basis_y=(0.0, 1.0),
        crop_min_x=0.0,
        crop_max_x=10.0,
        crop_min_y=0.0,
        crop_max_y=8.0,
        width_px=1000,
        height_px=800,
    )
    assert abs(geometry.affine_scale(affine) - 0.01) < 1e-9


@pytest.mark.engine
def test_built_affine_validates_in_full_manifest():
    from ca_elevation_engine import ingest
    from ca_elevation_revit import manifest_builder
    from ca_elevation_revit.manifest_builder import FloorplanExport

    affine = build_pixel_to_model(
        origin_x=0.0,
        origin_y=0.0,
        basis_x=(1.0, 0.0),
        basis_y=(0.0, 1.0),
        crop_min_x=0.0,
        crop_max_x=10.0,
        crop_min_y=0.0,
        crop_max_y=8.0,
        width_px=1000,
        height_px=800,
    )
    fp = FloorplanExport(
        level_id="L1",
        level_name="Level 1",
        elevation=0.0,
        image_bytes=b"png",
        basename="plan_L1.png",
        width_px=1000,
        height_px=800,
        pixel_to_model=affine,
    )
    device = manifest_builder.device_dict(
        "uid-1", "Card Reader", "HID-R10", "L1", {"x": 5.0, "y": 4.0, "z": 4.0}
    )
    manifest = manifest_builder.build_manifest(
        {"id": "p", "name": "P", "units": "feet"}, [fp], [device]
    )
    parsed = ingest.parse_manifest(manifest, validate=True)
    assert parsed.levels[0].floorplan.pixel_to_model == affine
