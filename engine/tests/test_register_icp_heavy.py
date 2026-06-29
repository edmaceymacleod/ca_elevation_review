"""Heavy ICP refinement test (Open3D). SKIPs cleanly when the backend is absent.

This module deliberately sets NO module-level ``pytestmark`` so its single test
is marked ONLY ``heavy`` -- ``pytest -m unit`` will not select it, and
``pytest -m "not heavy"`` deselects it.
"""

from __future__ import annotations

import numpy as np
import pytest

from ca_elevation_engine import pointcloud as pc
from ca_elevation_engine.geometry import camera_position, distance3, transform_point
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
def test_icp_refines_known_offset(tmp_path):
    """ICP pulls an off-by-a-known-offset coarse transform back toward truth.

    Geometry (the load-bearing part -- the earlier version had it backwards):
    the COARSE transform is treated as slightly *wrong*. The ground-truth
    transform differs from coarse by a small known model-space translation, so
    the camera's true model position is ``coarse_cam + offset``. The point cloud
    is the model-surface target seen through the TRUE transform; under the (wrong)
    coarse transform it lands offset from the target, and ICP must pull it back.
    A correct refinement therefore moves the camera *closer* to true, not away.

    NOTE: only exercises the PLY/Open3D path. The E57 (pye57) read path is
    covered separately by test_e57_heavy.py against a real E57 container.
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

    # The ground-truth transform: coarse is wrong by this known model-space offset.
    offset = np.array([0.2, 0.0, 0.05])
    true_transform = np.eye(4)
    true_transform[:3, 3] = offset
    true_transform = true_transform @ coarse.arkit_to_model

    # The cloud IS the model-surface target the engine will align against, pushed
    # into the ARKit frame through the TRUE transform. So the true transform maps
    # the cloud exactly onto the target; the coarse one lands it offset by -offset.
    target = pc.model_surface_target(manifest, "L1")
    inv_true = np.linalg.inv(true_transform)
    arkit_pts = (inv_true[:3, :3] @ target.T).T + inv_true[:3, 3]

    bundle = tmp_path / "bundle"
    (bundle / "clouds").mkdir(parents=True)
    _write_ply(bundle / "clouds" / "s.ply", arkit_pts)

    coarse_cam = coarse.camera_model_position
    true_cam = transform_point(true_transform, camera_position(shot.pose))
    # Sanity: the coarse camera really is off from truth by |offset| before ICP.
    assert distance3(coarse_cam, true_cam) == pytest.approx(float(np.linalg.norm(offset)), abs=1e-9)

    reg2 = refine_registration(coarse, shot, manifest, bundle_dir=str(bundle))

    assert reg2.refined is True
    assert reg2.residual is not None
    # Tolerance tied to alignment geometry (< 0.5 * voxel == < max_corr), not magic.
    assert reg2.residual < 0.5 * 0.1
    # ICP recovered the offset: the refined camera is much closer to true than coarse.
    refined_err = distance3(reg2.camera_model_position, true_cam)
    coarse_err = distance3(coarse_cam, true_cam)
    assert refined_err < coarse_err
    assert refined_err < 0.05  # recovered to well within the 0.2-ft offset
    # The residual note is on the registration for the report seam to pick up.
    assert any("ICP refinement applied" in n for n in reg2.notes)
