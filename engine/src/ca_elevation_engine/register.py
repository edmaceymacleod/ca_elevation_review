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


def refine_registration(
    reg: ShotRegistration, shot: Shot, manifest: SpecManifest, bundle_dir: str | None = None
) -> ShotRegistration:
    """Optional fine registration via ICP against model geometry.

    No-ops (returns ``reg`` unchanged) unless a point cloud is present and the
    optional heavy backend (Open3D) is importable. This keeps the headless unit
    path real while leaving a documented seam for the metric refinement.
    """
    if shot.point_cloud is None:
        return reg
    try:  # pragma: no cover - exercised only with heavy extras installed
        import open3d  # noqa: F401
    except Exception:
        reg.notes.append("point cloud present but Open3D not installed: skipped ICP refinement")
        return reg
    # pragma: no cover - real ICP needs model surfaces + the heavy backend.
    reg.notes.append("ICP refinement hook reached (not yet implemented in v1)")
    return reg


def register_capture(manifest: SpecManifest, capture, bundle_dir: str | None = None):
    """Register every shot. Returns ``dict[shot_id -> ShotRegistration]``."""
    units = manifest.project.units
    out = {}
    for shot in capture.shots:
        level = manifest.level_by_id(shot.level_id)
        if level is None:  # pragma: no cover - guarded earlier by ingest checks
            continue
        reg = coarse_register(shot, level, units=units)
        reg = refine_registration(reg, shot, manifest, bundle_dir=bundle_dir)
        out[shot.id] = reg
    return out
