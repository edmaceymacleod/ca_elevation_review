"""End-to-end heavy integration: posed point cloud -> ICP -> verdict report.

Drives the full production pipeline (``register_capture`` + ``run_pipeline``)
over a genuine, in-memory-built posed point cloud written to a real bundle, with
Open3D actually running ICP. Asserts two things the skip-path could never prove:

1. ICP *improved* the alignment -- the refined camera is materially closer to the
   known-true pose than the coarse estimate.
2. The ICP residual note is *surfaced all the way to the rendered report*
   (``DeviceResult.notes`` and the HTML/JSON output), via the compare seam.

This module sets NO module-level ``pytestmark``; its tests are marked only
``heavy`` and SKIP cleanly when Open3D is absent.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ca_elevation_engine import pointcloud as pc
from ca_elevation_engine.geometry import camera_position, distance3, transform_point
from ca_elevation_engine.models import (
    CapturePackage,
    Device,
    Floorplan,
    Intrinsics,
    Level,
    Observation,
    Pin,
    Point3,
    Project,
    Shot,
    SpecManifest,
)
from ca_elevation_engine.pipeline import run_pipeline
from ca_elevation_engine.register import coarse_register, register_capture
from ca_elevation_engine.report import render_html, render_json


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


def _scene():
    level = Level(
        id="L1",
        name="Level 1",
        elevation=0.0,
        floorplan=Floorplan("p.png", 1000, 1000, [0.01, 0, 0, 0, 0.01, 0]),
    )
    device = Device(
        id="d1", family="Fire Alarm", type="Strobe", level_id="L1", position=Point3(8.0, 0.0, 4.0)
    )
    manifest = SpecManifest(
        schema_version="1.0.0",
        project=Project(id="proj-x", name="Proj X", units="feet"),
        levels=[level],
        devices=[device],
    )
    shot = Shot(
        id="s1",
        level_id="L1",
        rgb_image="r.jpg",
        intrinsics=Intrinsics(1000, 1000, 640, 360, 1280, 720),
        pose=np.eye(4).flatten().tolist(),
        pin=Pin(x=0.0, y=0.0, heading=0.0),
        point_cloud="clouds/s1.ply",
        # An observation right at the device so the device MATCHES and the matched
        # shot's registration (ICP) notes propagate into its DeviceResult.
        observations=[Observation(position=Point3(8.0, 0.0, 4.0))],
    )
    capture = CapturePackage(schema_version="1.0.0", project_id="proj-x", shots=[shot])
    return manifest, level, shot, capture


@pytest.mark.heavy
def test_posed_cloud_refines_and_surfaces_residual_in_report(tmp_path):
    pytest.importorskip("open3d")
    manifest, level, shot, capture = _scene()

    # Coarse baseline (the "before"). register_capture mutates its own reg in
    # place, so build an independent coarse for the comparison.
    coarse = coarse_register(shot, level, units="feet")
    coarse_cam = coarse.camera_model_position

    # Ground truth: coarse is off by a known small model-space offset. The cloud is
    # the model-surface target seen through the TRUE transform, so under coarse it
    # lands offset and ICP has to pull it back.
    offset = np.array([0.18, -0.06, 0.07])
    true_transform = np.eye(4)
    true_transform[:3, 3] = offset
    true_transform = true_transform @ coarse.arkit_to_model
    target = pc.model_surface_target(manifest, "L1")
    inv_true = np.linalg.inv(true_transform)
    arkit_pts = (inv_true[:3, :3] @ target.T).T + inv_true[:3, 3]

    bundle = tmp_path / "bundle"
    (bundle / "clouds").mkdir(parents=True)
    _write_ply(bundle / "clouds" / "s1.ply", arkit_pts)

    # --- ICP genuinely improved alignment -------------------------------------
    regs = register_capture(manifest, capture, bundle_dir=str(bundle))
    reg = regs["s1"]
    assert reg.refined is True
    assert reg.residual is not None and reg.residual < 0.5 * 0.1

    true_cam = transform_point(true_transform, camera_position(shot.pose))
    coarse_err = distance3(coarse_cam, true_cam)
    refined_err = distance3(reg.camera_model_position, true_cam)
    assert coarse_err == pytest.approx(float(np.linalg.norm(offset)), abs=1e-9)
    assert refined_err < coarse_err  # ICP moved the camera toward truth
    assert refined_err < 0.05  # recovered to well within the offset

    # --- The residual note reaches the rendered verdict report -----------------
    result = run_pipeline(
        manifest, capture, bundle_dir=str(bundle), generated_at="2026-06-29T00:00:00Z"
    )
    report = result.report
    (dr,) = report.device_results
    assert dr.device_id == "d1"
    assert dr.verdict.value == "pass"  # observation sits exactly on the device

    icp_notes = [n for n in dr.notes if "ICP refinement applied" in n]
    assert icp_notes, f"ICP residual note missing from DeviceResult.notes: {dr.notes}"
    assert icp_notes[0].startswith("registration: ")
    assert "rmse=" in icp_notes[0]

    # Rendered outputs carry it too (HTML shows notes for all devices; JSON always).
    html = render_html(report, manifest, capture)
    assert "ICP refinement applied" in html
    payload = json.loads(render_json(report))
    notes_json = payload["device_results"][0]["notes"]
    assert any("ICP refinement applied" in n for n in notes_json)
