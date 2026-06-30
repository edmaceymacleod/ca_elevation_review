"""Georeference each shot into model coordinates.

The floorplan pin is the georeferencing primitive (see design.md): the operator
drops a pin for where they stood and an arrow for which way the camera faced.
From that plus the level's ``pixel_to_model`` affine and the ARKit pose we build
a coarse ``arkit_to_model`` transform that drops the capture's arbitrary world
frame into the building's coordinate system.

Pipeline shape: coarse human anchor -> sensors -> (optional) fine registration.
The coarse step here is fully deterministic and dependency-light. Fine
registration (ICP of a point cloud against model surfaces) is an optional
refinement implemented behind :func:`refine_registration`, which no-ops unless a
heavy backend and point-cloud data are present -- so the headless path stays
real and testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import geometry as geo
from .models import Level, Shot, SpecManifest

# Assumed eye/camera height above the finished floor when the pin gives no
# vertical datum, project units. ~1.5 m expressed in feet; overridden when depth
# provides a real floor line. Used only to seat the coarse transform vertically.
DEFAULT_CAMERA_HEIGHT_FT = 4.9
DEFAULT_CAMERA_HEIGHT_M = 1.5


@dataclass
class ShotRegistration:
    """Result of georeferencing one shot."""

    shot_id: str
    level_id: str
    arkit_to_model: np.ndarray  # 4x4
    camera_model_position: tuple[float, float, float]
    camera_model_heading: float  # degrees
    refined: bool = False
    residual: float | None = None  # registration residual if refined
    confidence: float = 0.5
    notes: list[str] = field(default_factory=list)

    def transform_point(self, p: tuple[float, float, float]) -> tuple[float, float, float]:
        return geo.transform_point(self.arkit_to_model, p)


def _axis_fix() -> np.ndarray:
    """ARKit world frame (X right, Y up, Z toward viewer) -> model frame (Z up).

    Maps ARKit (x, y, z) -> model_local (x, -z, y): horizontal plane preserved,
    ARKit's +Y (gravity up) becomes model +Z.
    """
    m = np.zeros((4, 4))
    m[0, 0] = 1.0  # model_x = arkit_x
    m[1, 2] = -1.0  # model_y = -arkit_z
    m[2, 1] = 1.0  # model_z = arkit_y
    m[3, 3] = 1.0
    return m


def _camera_height(units: str) -> float:
    return DEFAULT_CAMERA_HEIGHT_M if units == "meters" else DEFAULT_CAMERA_HEIGHT_FT


def coarse_register(shot: Shot, level: Level, units: str = "feet") -> ShotRegistration:
    """Build the coarse ``arkit_to_model`` transform for one shot.

    Strategy: bring the ARKit pose into a gravity-aligned, Z-up local frame
    (``axis_fix``), then apply a rigid 2D transform (rotation about Z +
    translation) chosen so the camera's local position maps to the pin's model
    position and the camera heading maps to the pin heading. Vertical seat: the
    camera maps to ``level.elevation + assumed eye height``.
    """
    axis = _axis_fix()

    # Camera position and heading in the gravity-aligned local frame.
    cam_local = geo.transform_point(axis, geo.camera_position(shot.pose))
    fwd_local = geo.transform_point(
        axis, geo.camera_forward(shot.pose)
    )  # direction; translation cancels below
    # Subtract the mapped origin so fwd stays a direction after the affine.
    origin_local = geo.transform_point(axis, (0.0, 0.0, 0.0))
    dir_local = (
        fwd_local[0] - origin_local[0],
        fwd_local[1] - origin_local[1],
        fwd_local[2] - origin_local[2],
    )
    heading_local = geo.normalize_angle_deg(math.degrees(math.atan2(dir_local[1], dir_local[0])))

    # Pin -> model XY and the desired heading.
    pin_x, pin_y = geo.pixel_to_model_xy(level.floorplan.pixel_to_model, shot.pin.x, shot.pin.y)
    desired_heading = geo.normalize_angle_deg(shot.pin.heading)

    # Rotation about Z to align local heading to pin heading.
    theta = desired_heading - heading_local
    rot = geo.rigid_transform_2d(0.0, 0.0, theta)

    # After rotation, where does the camera's local XY land? Translate so it
    # coincides with the pin.
    cam_rot = geo.transform_point(rot, cam_local)
    tx = pin_x - cam_rot[0]
    ty = pin_y - cam_rot[1]
    tz = (level.elevation + _camera_height(units)) - cam_rot[2]
    translate = np.eye(4)
    translate[0, 3] = tx
    translate[1, 3] = ty
    translate[2, 3] = tz

    # Applied to a point as translate(rot(axis(p))), i.e. translate @ rot @ axis.
    arkit_to_model = translate @ rot @ axis

    cam_model = geo.transform_point(arkit_to_model, geo.camera_position(shot.pose))
    cam_heading = geo.heading_of_pose_deg_from_matrix(arkit_to_model, shot.pose)

    conf = {"low": 0.35, "medium": 0.55, "high": 0.75}.get(shot.pin.confidence, 0.5)
    notes = []
    if shot.depth_map is None and shot.point_cloud is None:
        notes.append("no depth/point-cloud: geometry from pose+pin only (approximate)")

    return ShotRegistration(
        shot_id=shot.id,
        level_id=shot.level_id,
        arkit_to_model=arkit_to_model,
        camera_model_position=cam_model,
        camera_model_heading=cam_heading,
        refined=False,
        confidence=conf,
        notes=notes,
    )


# Default residual threshold (project units): at/above this an ICP refinement is
# treated as uncertain -- confidence is NOT raised and a "high residual" note is
# emitted. Tunable per call via refine_registration(high_residual_ft=...).
HIGH_RESIDUAL_FT = 0.25


def refine_registration(
    reg: ShotRegistration,
    shot: Shot,
    manifest: SpecManifest,
    bundle_dir: str | None = None,
    *,
    high_residual_ft: float = HIGH_RESIDUAL_FT,
) -> ShotRegistration:
    """Optional fine registration via ICP against model surfaces.

    Local rigid (no-scale) point-to-point ICP of the shot's point cloud (brought
    into the model frame by the coarse transform) against a sparse, floor-weighted
    model-surface target. Folds the correction into ``reg.arkit_to_model`` and sets
    ``reg.refined`` / ``reg.residual``.

    Degrades on ANY failure (never raises out of this function): a missing
    ``bundle_dir``, a missing/unreadable cloud file, an absent heavy backend, or an
    ICP error all leave the coarse transform untouched and append an explanatory
    note. With no ``point_cloud`` it is a silent no-op.

    Honesty: this corrects small floor-height and planar drift in an already-good
    coarse transform; it is rigid (no scale), local (won't fix a wrong pin), and
    blind behind walls. Part of the target is seeded from EXPECTED device positions,
    so refinement must not be read as evidence a device is present.
    """
    if shot.point_cloud is None:
        return reg

    from . import pointcloud as pc

    try:
        pts = pc.load_point_cloud(shot.point_cloud, bundle_dir)
    except pc.PointCloudBackendMissing as exc:
        reg.notes.append(f"point cloud present but backend missing: {exc}; skipped ICP")
        return reg
    except (FileNotFoundError, ValueError) as exc:  # incl. PointCloudPathError
        reg.notes.append(f"point cloud not loadable ({exc}); skipped ICP refinement")
        return reg

    target = pc.model_surface_target(manifest, shot.level_id)
    if target is None:
        reg.notes.append("no model surfaces to align to on this level; skipped ICP")
        return reg

    try:
        correction, rmse = _icp_refine(reg, pts, target)
    except pc.PointCloudBackendMissing as exc:
        reg.notes.append(f"point cloud present but backend missing: {exc}; skipped ICP")
        return reg
    except (np.linalg.LinAlgError, ValueError, RuntimeError) as exc:
        # Expected numeric/convergence failures (singular matrices, shape/value
        # errors out of the backend) degrade to the coarse transform. Programming
        # errors (TypeError, AttributeError, ...) are deliberately NOT caught so a
        # systematically broken ICP path fails loudly instead of silently never
        # refining.
        reg.notes.append(f"ICP failed ({exc}); kept coarse registration")
        return reg

    reg.arkit_to_model = correction @ reg.arkit_to_model
    reg.refined = True
    reg.residual = rmse
    reg.camera_model_position = geo.transform_point(
        reg.arkit_to_model, geo.camera_position(shot.pose)
    )
    reg.camera_model_heading = geo.heading_of_pose_deg_from_matrix(reg.arkit_to_model, shot.pose)

    if rmse < high_residual_ft:
        reg.confidence = min(0.9, reg.confidence + 0.15)
    else:
        reg.notes.append(f"high ICP residual (rmse={rmse:.4f}); refinement uncertain")

    units = manifest.project.units
    n_pts = len(pts)
    reg.notes.append(
        f"ICP refinement applied: rmse={rmse:.4f} {units}, {n_pts} pts (rigid, no scale; "
        "aligned to sparse floor+device surfaces)"
    )
    return reg


def _icp_refine(
    reg: ShotRegistration,
    source_pts: np.ndarray,
    target_pts: np.ndarray,
    *,
    max_corr: float = 0.5,
    max_iter: int = 50,
) -> tuple[np.ndarray, float]:  # pragma: no cover - heavy
    """Lazy Open3D point-to-point rigid ICP.

    Returns ``(correction_4x4, rmse)`` where ``correction`` is a model->model rigid
    transform to LEFT-multiply onto ``arkit_to_model``. The source cloud is brought
    into model space by the coarse transform (vectorized, no per-point loop).
    """
    try:
        import open3d as o3d  # lazy
    except Exception as exc:
        from . import pointcloud as pc

        raise pc.PointCloudBackendMissing("open3d not installed; cannot run ICP") from exc
    from . import pointcloud as pc

    R = reg.arkit_to_model[:3, :3]
    t = reg.arkit_to_model[:3, 3]
    src_model = (R @ source_pts.T).T + t  # vectorized, (N,3)
    src_model = pc._downsample(src_model, voxel=0.1)

    src = o3d.geometry.PointCloud()
    src.points = o3d.utility.Vector3dVector(src_model)
    tgt = o3d.geometry.PointCloud()
    tgt.points = o3d.utility.Vector3dVector(target_pts)

    result = o3d.pipelines.registration.registration_icp(
        src,
        tgt,
        max_corr,
        np.eye(4),
        o3d.pipelines.registration.TransformationEstimationPointToPoint(with_scaling=False),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iter),
    )
    correction = np.asarray(result.transformation, dtype=np.float64)
    return correction, float(result.inlier_rmse)


def register_capture(
    manifest: SpecManifest,
    capture,
    bundle_dir: str | None = None,
    *,
    high_residual_ft: float = HIGH_RESIDUAL_FT,
):
    """Register every shot. Returns ``dict[shot_id -> ShotRegistration]``."""
    units = manifest.project.units
    out = {}
    for shot in capture.shots:
        level = manifest.level_by_id(shot.level_id)
        if level is None:  # pragma: no cover - guarded earlier by ingest checks
            continue
        reg = coarse_register(shot, level, units=units)
        reg = refine_registration(
            reg, shot, manifest, bundle_dir=bundle_dir, high_residual_ft=high_residual_ft
        )
        out[shot.id] = reg
    return out
