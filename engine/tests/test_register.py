"""Georeferencing tests: the pin + pose -> model transform."""

from __future__ import annotations

import numpy as np
import pytest

from ca_elevation_engine import geometry as geo
from ca_elevation_engine import ingest, register
from ca_elevation_engine import pointcloud as pc
from ca_elevation_engine.register import (
    coarse_register,
    refine_registration,
    register_capture,
)

pytestmark = pytest.mark.unit


def test_identity_pose_places_camera_at_pin(f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    level = manifest.level_by_id("L1")
    shot = capture.shots[0]

    reg = coarse_register(shot, level, units="feet")
    # Pin at model (0,0); camera should land there in XY, at eye height in Z.
    cx, cy, cz = reg.camera_model_position
    assert (cx, cy) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert cz == pytest.approx(4.9, abs=1e-6)  # DEFAULT_CAMERA_HEIGHT_FT
    # Pin heading 0 -> camera faces +X in model.
    assert geo.angle_delta_deg(reg.camera_model_heading, 0.0) == pytest.approx(0.0, abs=1e-6)


def test_high_pin_confidence_raises_confidence(f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    reg = coarse_register(capture.shots[0], manifest.level_by_id("L1"))
    assert reg.confidence == pytest.approx(0.75)  # "high"


def test_register_capture_covers_all_shots(f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    regs = register_capture(manifest, capture)
    assert set(regs) == {s.id for s in capture.shots}


def test_device_in_front_projects_with_positive_depth(f01_manifest_path, f01_capture_path):
    """A device 8 ft ahead of the pinned camera must project in front of it."""
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    reg = register_capture(manifest, capture)["S1"]
    shot = capture.shots[0]
    device = next(d for d in manifest.devices if d.id == "D-PASS")

    model_to_arkit = np.linalg.inv(reg.arkit_to_model)
    p_arkit = geo.transform_point(model_to_arkit, device.position.as_tuple())
    intr = (shot.intrinsics.fx, shot.intrinsics.fy, shot.intrinsics.cx, shot.intrinsics.cy)
    _, _, depth = geo.project_point(shot.pose, intr, p_arkit)
    assert depth == pytest.approx(8.0, abs=1e-6)


def test_pin_offset_translates_camera():
    """Moving the pin to a different plan pixel moves the camera in model XY."""
    from ca_elevation_engine.models import (
        Floorplan,
        Intrinsics,
        Level,
        Pin,
        Shot,
    )

    level = Level(
        id="L1",
        name="L1",
        elevation=0.0,
        floorplan=Floorplan("p.png", 1000, 1000, [0.01, 0, 0, 0, 0.01, 0]),
    )
    pose = np.eye(4).flatten().tolist()
    intr = Intrinsics(1000, 1000, 640, 360, 1280, 720)
    shot = Shot(
        id="s",
        level_id="L1",
        rgb_image="r.jpg",
        intrinsics=intr,
        pose=pose,
        pin=Pin(x=500, y=300, heading=90),
    )
    reg = coarse_register(shot, level, units="feet")
    # pixel (500,300) -> model (5.0, 3.0).
    assert reg.camera_model_position[0] == pytest.approx(5.0, abs=1e-6)
    assert reg.camera_model_position[1] == pytest.approx(3.0, abs=1e-6)
    assert geo.angle_delta_deg(reg.camera_model_heading, 90) == pytest.approx(0, abs=1e-6)


# --- refine_registration graceful degradation (headless, no heavy deps) ----- #
def _shot_with_cloud(f01_capture_path, cloud_ref):
    capture = ingest.load_capture(f01_capture_path)
    shot = capture.shots[0]
    shot.point_cloud = cloud_ref
    return shot


def test_refine_noop_without_point_cloud(f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    shot = capture.shots[0]
    shot.point_cloud = None
    reg = coarse_register(shot, manifest.level_by_id("L1"))
    notes_before = list(reg.notes)
    out = refine_registration(reg, shot, manifest, bundle_dir=None)
    assert out.refined is False
    assert out.notes == notes_before  # no new note


def test_refine_degrades_without_bundle_dir(monkeypatch, f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    shot = _shot_with_cloud(f01_capture_path, "clouds/s.ply")
    reg = coarse_register(shot, manifest.level_by_id("L1"))

    # Guard the "no heavy import attempted" promise: importing open3d/pye57 fails hard.
    import builtins

    real_import = builtins.__import__

    def _no_heavy(name, *args, **kwargs):
        if name in ("open3d", "pye57"):
            raise AssertionError(f"heavy backend imported: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_heavy)

    out = refine_registration(reg, shot, manifest, bundle_dir=None)
    assert out.refined is False
    assert any("skipped ICP" in n for n in out.notes)


def test_refine_degrades_when_file_missing(tmp_path, f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    shot = _shot_with_cloud(f01_capture_path, "clouds/nope.ply")
    reg = coarse_register(shot, manifest.level_by_id("L1"))
    out = refine_registration(reg, shot, manifest, bundle_dir=str(tmp_path))
    assert out.refined is False
    assert any("not loadable" in n for n in out.notes)


def test_register_capture_still_covers_all_shots_with_cloud_refs(
    f01_manifest_path, f01_capture_path
):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    for shot in capture.shots:
        shot.point_cloud = "clouds/s.ply"
    regs = register_capture(manifest, capture)  # bundle_dir=None
    assert set(regs) == {s.id for s in capture.shots}
    assert all(r.refined is False for r in regs.values())


def test_refine_backend_missing_note_via_monkeypatch(
    monkeypatch, f01_manifest_path, f01_capture_path
):
    manifest = ingest.load_manifest(f01_manifest_path)
    shot = _shot_with_cloud(f01_capture_path, "clouds/s.ply")
    reg = coarse_register(shot, manifest.level_by_id("L1"))

    def _raise(*args, **kwargs):
        raise pc.PointCloudBackendMissing("open3d not installed; cannot read this cloud")

    monkeypatch.setattr(pc, "load_point_cloud", _raise)
    out = refine_registration(reg, shot, manifest, bundle_dir="/whatever")
    assert out.refined is False
    assert any("backend missing" in n for n in out.notes)


# --- high_residual_ft is a tunable threshold (default 0.25) ----------------- #
def _force_icp(monkeypatch, rmse: float) -> None:
    """Make refine_registration reach the residual branch deterministically.

    Stubs the cloud loader (so no real .ply is needed) and the heavy ICP (so no
    open3d), returning an identity correction with a fixed rmse. The f01 manifest
    has devices on L1, so the real model_surface_target returns a non-None target
    and the refinement proceeds.
    """
    monkeypatch.setattr(pc, "load_point_cloud", lambda *a, **k: np.zeros((4, 3), dtype=np.float64))
    monkeypatch.setattr(register, "_icp_refine", lambda *a, **k: (np.eye(4), rmse))


def _fresh_reg(manifest, f01_capture_path):
    """A fresh coarse registration (+ its shot) carrying a cloud ref.

    refine_registration mutates its `reg`, so every assertion needs a clean one.
    """
    shot = _shot_with_cloud(f01_capture_path, "clouds/s.ply")
    return shot, coarse_register(shot, manifest.level_by_id("L1"))


def test_refine_default_threshold_pins_025(monkeypatch, f01_manifest_path, f01_capture_path):
    # The default threshold IS the module constant, and it IS 0.25. This is the
    # one acceptance criterion of the refactor ("default behavior identical"), so
    # pin both the value and the 0.25 boundary with NO override.
    assert register.HIGH_RESIDUAL_FT == 0.25
    manifest = ingest.load_manifest(f01_manifest_path)

    # Just below 0.25 -> good: confidence raised, no high-residual note.
    shot, reg = _fresh_reg(manifest, f01_capture_path)
    base_conf = reg.confidence  # 0.75 for the "high" pin in f01
    _force_icp(monkeypatch, rmse=0.24)
    good = refine_registration(reg, shot, manifest, bundle_dir="/whatever")
    assert good.refined is True
    assert good.residual == pytest.approx(0.24)
    assert good.confidence > base_conf
    assert not any("high ICP residual" in n for n in good.notes)

    # Just above 0.25 -> high: note emitted, confidence NOT raised. If the default
    # were widened (e.g. to 0.50) this branch would flip and the test would fail.
    shot2, reg2 = _fresh_reg(manifest, f01_capture_path)
    base_conf2 = reg2.confidence
    _force_icp(monkeypatch, rmse=0.26)
    high = refine_registration(reg2, shot2, manifest, bundle_dir="/whatever")
    assert high.refined is True
    assert high.residual == pytest.approx(0.26)
    assert high.confidence == pytest.approx(base_conf2)
    assert any("high ICP residual" in n for n in high.notes)


def test_refine_residual_equal_to_threshold_is_high(
    monkeypatch, f01_manifest_path, f01_capture_path
):
    # Comparison is strict `rmse < threshold` (register.py:203): at EQUALITY the
    # refinement is HIGH. Guards a silent `<` -> `<=` refactor at the boundary.
    manifest = ingest.load_manifest(f01_manifest_path)
    shot, reg = _fresh_reg(manifest, f01_capture_path)
    base_conf = reg.confidence
    _force_icp(monkeypatch, rmse=0.20)
    out = refine_registration(reg, shot, manifest, bundle_dir="/whatever", high_residual_ft=0.20)
    assert out.refined is True
    assert out.confidence == pytest.approx(base_conf)  # equality is NOT below threshold
    assert any("high ICP residual" in n for n in out.notes)


def test_refine_override_lowers_threshold_so_same_residual_is_high(
    monkeypatch, f01_manifest_path, f01_capture_path
):
    manifest = ingest.load_manifest(f01_manifest_path)
    shot, reg = _fresh_reg(manifest, f01_capture_path)
    base_conf = reg.confidence
    _force_icp(monkeypatch, rmse=0.20)  # same residual...
    # ...but override the threshold below it: now 0.20 >= 0.10 -> "high residual".
    out = refine_registration(reg, shot, manifest, bundle_dir="/whatever", high_residual_ft=0.10)
    assert out.refined is True
    assert out.residual == pytest.approx(0.20)
    assert out.confidence == pytest.approx(base_conf)  # NOT raised
    assert any("high ICP residual" in n for n in out.notes)


def test_refine_override_raises_threshold_so_high_residual_is_good(
    monkeypatch, f01_manifest_path, f01_capture_path
):
    # Symmetric proof: the override can also RAISE the bar (good branch via the
    # param), so a residual above the default 0.25 is accepted as good.
    manifest = ingest.load_manifest(f01_manifest_path)
    shot, reg = _fresh_reg(manifest, f01_capture_path)
    base_conf = reg.confidence
    _force_icp(monkeypatch, rmse=0.30)  # above default 0.25...
    # ...but raise the threshold above it: 0.30 < 0.40 -> good branch.
    out = refine_registration(reg, shot, manifest, bundle_dir="/whatever", high_residual_ft=0.40)
    assert out.refined is True
    assert out.residual == pytest.approx(0.30)
    assert out.confidence > base_conf
    assert not any("high ICP residual" in n for n in out.notes)


def test_register_capture_forwards_high_residual_ft(
    monkeypatch, f01_manifest_path, f01_capture_path
):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    for shot in capture.shots:
        shot.point_cloud = "clouds/s.ply"
    _force_icp(monkeypatch, rmse=0.20)

    regs = register_capture(manifest, capture, high_residual_ft=0.10)
    # Override propagated: 0.20 >= 0.10 -> every refined shot flagged high-residual.
    assert regs  # non-empty
    assert all(r.refined for r in regs.values())
    assert all(any("high ICP residual" in n for n in r.notes) for r in regs.values())
