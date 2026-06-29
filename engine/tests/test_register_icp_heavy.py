"""Heavy ICP refinement test (Open3D). SKIPs cleanly when the backend is absent.

This module deliberately sets NO module-level ``pytestmark`` so its single test
is marked ONLY ``heavy`` -- ``pytest -m unit`` will not select it, and
``pytest -m "not heavy"`` deselects it.
"""

from __future__ import annotations

import numpy as np
import pytest

from ca_elevation_engine.geometry import distance3
from ca_elevation_engine.models import (
    Device,
    Floorplan,
    Intrinsics,
    Level,
    Pin,
    Point3,
    Project,
    Shot,
    SpecManifest,
)
from ca_elevation_engine.register import coarse_register, refine_registration


def _write_ply(path, pts):
    header = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(pts)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    body = [f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in pts]
    path.write_text("\n".join(header + body) + "\n")


@pytest.mark.heavy
def test_icp_refines_known_offset(tmp_path, make_cloud):
    """ICP pulls a known-offset cloud back toward the model-surface truth.

    NOTE: only exercises the PLY/Open3D path. E57 read (pye57) has no automated
    coverage here -- it must be hand smoke-tested against a real export.
    """
    pytest.importorskip("open3d")

    level = Level(
        id="L1",
        name="L1",
        elevation=0.0,
        floorplan=Floorplan("p.png", 1000, 1000, [0.01, 0, 0, 0, 0.01, 0]),
    )
    device = Device(id="d1", family="F", type="T", level_id="L1", position=Point3(8.0, 0.0, 4.0))
    manifest = SpecManifest(
        schema_version="1.0.0",
        project=Project(id="p", name="P", units="feet"),
        levels=[level],
        devices=[device],
    )
    intr = Intrinsics(1000, 1000, 640, 360, 1280, 720)
    shot = Shot(
        id="s",
        level_id="L1",
        rgb_image="r.jpg",
        intrinsics=intr,
        pose=np.eye(4).flatten().tolist(),
        pin=Pin(x=0.0, y=0.0, heading=0.0),
        point_cloud="clouds/s.ply",
    )

    coarse = coarse_register(shot, level, units="feet")
    # The cloud, expressed in the ARKit frame, is the model-truth surfaces pushed
    # back through the inverse coarse transform, then given a small known offset.
    truth = make_cloud(elevation=level.elevation, device_xy=(8.0, 0.0), device_z=4.0)
    inv = np.linalg.inv(coarse.arkit_to_model)
    R, t = inv[:3, :3], inv[:3, 3]
    arkit_pts = (R @ truth.T).T + t
    offset = np.array([0.2, 0.0, 0.05])
    arkit_pts = arkit_pts + (inv[:3, :3] @ offset)  # known model-space offset

    bundle = tmp_path / "bundle"
    (bundle / "clouds").mkdir(parents=True)
    _write_ply(bundle / "clouds" / "s.ply", arkit_pts)

    coarse_cam = coarse.camera_model_position
    reg2 = refine_registration(coarse, shot, manifest, bundle_dir=str(bundle))

    assert reg2.refined is True
    assert reg2.residual is not None
    # Tolerance tied to alignment geometry (< 0.5 * voxel == < max_corr), not magic.
    assert reg2.residual < 0.5 * 0.1
    # Composition pulled the camera closer to known-true than the coarse estimate.
    true_cam = (0.0, 0.0, 4.9)  # pin at origin, default eye height
    assert distance3(reg2.camera_model_position, true_cam) <= distance3(coarse_cam, true_cam) + 1e-9
