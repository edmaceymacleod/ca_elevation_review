"""Pure point-cloud helpers + path resolution (no heavy backend)."""

from __future__ import annotations

import importlib

import numpy as np
import pytest

from ca_elevation_engine import pointcloud as pc
from ca_elevation_engine.models import (
    Device,
    Floorplan,
    Level,
    Point3,
    Project,
    SpecManifest,
)

pytestmark = pytest.mark.unit


def _manifest(devices):
    return SpecManifest(
        schema_version="1.0.0",
        project=Project(id="p", name="P", units="feet"),
        levels=[
            Level(
                id="L1",
                name="L1",
                elevation=2.5,
                floorplan=Floorplan("p.png", 100, 100, [0.01, 0, 0, 0, 0.01, 0]),
            )
        ],
        devices=devices,
    )


def _device(did, x, y, z):
    return Device(id=did, family="F", type="T", level_id="L1", position=Point3(x, y, z))


# --- import laziness -------------------------------------------------------- #
def test_pointcloud_imports_without_heavy():
    mod = importlib.import_module("ca_elevation_engine.pointcloud")
    assert hasattr(mod, "load_point_cloud")


# --- path resolution -------------------------------------------------------- #
def test_resolve_cloud_path_joins(tmp_path):
    out = pc.resolve_cloud_path("clouds/s.ply", str(tmp_path))
    assert out == (tmp_path / "clouds" / "s.ply")
    assert tmp_path.resolve() in out.parents


def test_resolve_cloud_path_none_without_bundle(tmp_path):
    assert pc.resolve_cloud_path("clouds/s.ply", None) is None
    assert pc.resolve_cloud_path("", str(tmp_path)) is None
    assert pc.resolve_cloud_path(None, str(tmp_path)) is None


def test_resolve_cloud_path_accepts_in_tree_dotdot(tmp_path):
    out = pc.resolve_cloud_path("clouds/../clouds/s.ply", str(tmp_path))
    assert out == (tmp_path / "clouds" / "s.ply")


def test_resolve_cloud_path_rejects_traversal(tmp_path):
    with pytest.raises(pc.PointCloudPathError):
        pc.resolve_cloud_path("../../etc/passwd", str(tmp_path))
    # PointCloudPathError is a ValueError so the register degrade-path catches it.
    assert issubclass(pc.PointCloudPathError, ValueError)


def test_resolve_cloud_path_rejects_absolute(tmp_path):
    with pytest.raises(pc.PointCloudPathError):
        pc.resolve_cloud_path("/etc/passwd", str(tmp_path))


# --- load dispatch / degradation -------------------------------------------- #
def test_load_point_cloud_missing_bundle_raises():
    with pytest.raises(ValueError):
        pc.load_point_cloud("x.ply", None)


def test_load_point_cloud_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pc.load_point_cloud("clouds/nope.ply", str(tmp_path))


def test_load_point_cloud_unsupported_suffix(tmp_path):
    bad = tmp_path / "x.foo"
    bad.write_text("nope")
    with pytest.raises(ValueError):
        pc.load_point_cloud("x.foo", str(tmp_path))


# --- downsample ------------------------------------------------------------- #
def test_downsample_collapses_voxel():
    pts = np.array(
        [
            [0.00, 0.00, 0.00],
            [0.01, 0.01, 0.01],  # same voxel as row 0 at voxel=1.0
            [5.00, 5.00, 5.00],
            [5.02, 5.00, 5.00],  # same voxel as row 2
            [9.00, 0.00, 0.00],
        ],
        dtype=np.float64,
    )
    out = pc._downsample(pts, voxel=1.0)
    assert len(out) == 3  # three occupied voxels
    # Output points are a subset of the ORIGINAL input points (real points).
    for row in out:
        assert any(np.allclose(row, p) for p in pts)
    # First representative per voxel, in input order.
    assert np.allclose(out[0], pts[0])
    assert np.allclose(out[1], pts[2])
    assert np.allclose(out[2], pts[4])


def test_downsample_empty_and_bad_voxel():
    empty = pc._downsample(np.empty((0, 3)), voxel=1.0)
    assert empty.shape == (0, 3)
    with pytest.raises(ValueError):
        pc._downsample(np.zeros((3, 3)), voxel=0.0)


# --- model-surface target --------------------------------------------------- #
def test_model_surface_target_has_floor_and_devices():
    manifest = _manifest([_device("d1", 8.0, 0.0, 4.0), _device("d2", -3.0, 2.0, 4.0)])
    target = pc.model_surface_target(manifest, "L1", spacing=0.5, floor_pad=3.0)
    assert target is not None
    # Floor z at level elevation present.
    assert np.any(np.isclose(target[:, 2], 2.5))
    # A point near each device position present.
    for dx, dy, dz in ((8.0, 0.0, 4.0), (-3.0, 2.0, 4.0)):
        assert np.any(np.all(np.isclose(target, [dx, dy, dz]), axis=1))
    # Floor grid dominates the device cluster count (F9 weighting).
    floor_pts = int(np.sum(np.isclose(target[:, 2], 2.5)))
    device_pts = len(target) - floor_pts
    assert floor_pts > device_pts
    # Deterministic shape across calls.
    again = pc.model_surface_target(manifest, "L1", spacing=0.5, floor_pad=3.0)
    assert target.shape == again.shape
    assert np.array_equal(target, again)


def test_model_surface_target_empty_level_returns_none():
    manifest = _manifest([])
    assert pc.model_surface_target(manifest, "L1") is None
