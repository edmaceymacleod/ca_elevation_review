"""Unit tests for the pure geometry helpers."""

from __future__ import annotations

import numpy as np
import pytest

from ca_elevation_engine import geometry as geo

pytestmark = pytest.mark.unit


def test_pixel_model_roundtrip():
    affine = [0.01, 0.0, 5.0, 0.0, 0.01, -2.0]
    x, y = geo.pixel_to_model_xy(affine, 100, 200)
    assert x == pytest.approx(6.0)
    assert y == pytest.approx(0.0)
    px, py = geo.model_xy_to_pixel(affine, x, y)
    assert px == pytest.approx(100)
    assert py == pytest.approx(200)


def test_model_to_pixel_singular_raises():
    with pytest.raises(ValueError):
        geo.model_xy_to_pixel([0, 0, 0, 0, 0, 0], 1, 1)


def test_affine_scale():
    assert geo.affine_scale([0.01, 0, 0, 0, 0.01, 0]) == pytest.approx(0.01)


@pytest.mark.parametrize(
    "a,b,expected",
    [(10, 350, 20), (0, 0, 0), (0, 180, 180), (350, 10, 20), (90, 270, 180)],
)
def test_angle_delta(a, b, expected):
    assert geo.angle_delta_deg(a, b) == pytest.approx(expected)


def test_normalize_angle():
    assert geo.normalize_angle_deg(370) == pytest.approx(10)
    assert geo.normalize_angle_deg(-10) == pytest.approx(350)


def test_heading_unit_vector():
    dx, dy = geo.heading_to_unit_vector(0)
    assert (dx, dy) == pytest.approx((1.0, 0.0))
    dx, dy = geo.heading_to_unit_vector(90)
    assert (dx, dy) == pytest.approx((0.0, 1.0), abs=1e-9)


def test_distance_helpers():
    assert geo.distance3((0, 0, 0), (3, 4, 0)) == pytest.approx(5.0)
    assert geo.distance2((0, 0), (3, 4)) == pytest.approx(5.0)


def test_camera_position_and_forward_identity():
    pose = np.eye(4).flatten().tolist()
    assert geo.camera_position(pose) == pytest.approx((0, 0, 0))
    # ARKit camera looks down local -Z.
    assert geo.camera_forward(pose) == pytest.approx((0, 0, -1))


def test_project_point_in_front():
    pose = np.eye(4).flatten().tolist()
    # Point straight ahead at z=-5 (5 in front), centered.
    u, v, depth = geo.project_point(pose, (1000, 1000, 640, 360), (0, 0, -5))
    assert depth == pytest.approx(5.0)
    assert (u, v) == pytest.approx((640, 360))


def test_project_point_behind_camera_negative_depth():
    pose = np.eye(4).flatten().tolist()
    _, _, depth = geo.project_point(pose, (1000, 1000, 640, 360), (0, 0, 5))
    assert depth < 0


def test_point_in_view():
    pose = np.eye(4).flatten().tolist()
    intr = (1000, 1000, 640, 360)
    assert geo.point_in_view(pose, intr, 1280, 720, (0, 0, -5))
    assert not geo.point_in_view(pose, intr, 1280, 720, (0, 0, 5))


def test_transform_direction_ignores_translation():
    m = geo.rigid_transform_2d(100, 200, 0)
    assert geo.transform_direction(m, (1, 0, 0)) == pytest.approx((1, 0, 0))


def test_rigid_transform_2d_rotation():
    m = geo.rigid_transform_2d(0, 0, 90)
    out = geo.transform_point(m, (1, 0, 0))
    assert out == pytest.approx((0, 1, 0), abs=1e-9)


def test_heading_of_pose_from_matrix():
    pose = np.eye(4).flatten().tolist()
    # No rotation: forward -Z maps to model via identity -> heading along -Z's xy.
    m = np.eye(4)
    # forward (0,0,-1) rotated by identity -> xy (0,0) -> atan2(0,0)=0
    h = geo.heading_of_pose_deg_from_matrix(m, pose)
    assert 0 <= h < 360
