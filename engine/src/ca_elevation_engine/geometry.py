"""Pure geometry helpers for georeferencing and comparison.

All functions here are deterministic, dependency-light (numpy only), and unit
agnostic (work in whatever units the manifest declares). This is the math the
rest of the engine leans on; keep it free of IO and engine-domain types where
practical so it stays trivially testable.

Conventions
-----------
* Floorplan affine ``pixel_to_model`` is 2x3 row-major ``[a,b,c,d,e,f]`` mapping
  plan pixel ``(px,py)`` -> model ``(X,Y)`` via ``X=a*px+b*py+c``,
  ``Y=d*px+e*py+f``.
* Angles are in degrees, ``0`` along ``+X``, increasing counter-clockwise.
* ARKit pose is a 4x4 row-major camera-to-world matrix; camera looks down its
  local ``-Z`` with ``+Y`` up (ARKit convention).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

Vec3 = tuple[float, float, float]


# --------------------------------------------------------------------------- #
# Floorplan pixel <-> model
# --------------------------------------------------------------------------- #
def pixel_to_model_xy(affine: Sequence[float], px: float, py: float) -> tuple[float, float]:
    """Map a floorplan pixel to model XY using a 2x3 row-major affine."""
    a, b, c, d, e, f = affine
    return (a * px + b * py + c, d * px + e * py + f)


def model_xy_to_pixel(affine: Sequence[float], x: float, y: float) -> tuple[float, float]:
    """Inverse of :func:`pixel_to_model_xy`. Raises if the affine is singular."""
    a, b, c, d, e, f = affine
    det = a * e - b * d
    if abs(det) < 1e-12:
        raise ValueError("pixel_to_model affine is singular; cannot invert")
    dx = x - c
    dy = y - f
    px = (e * dx - b * dy) / det
    py = (-d * dx + a * dy) / det
    return (px, py)


def affine_scale(affine: Sequence[float]) -> float:
    """Approximate model-units-per-pixel of an affine (geometric mean of axes)."""
    a, b, _, d, e, _ = affine
    sx = math.hypot(a, d)
    sy = math.hypot(b, e)
    return math.sqrt(sx * sy)


# --------------------------------------------------------------------------- #
# Angles
# --------------------------------------------------------------------------- #
def normalize_angle_deg(angle: float) -> float:
    """Normalize to [0, 360)."""
    return angle % 360.0


def angle_delta_deg(a: float, b: float) -> float:
    """Smallest absolute difference between two headings, in [0, 180]."""
    diff = (a - b) % 360.0
    if diff > 180.0:
        diff = 360.0 - diff
    return abs(diff)


def heading_to_unit_vector(heading_deg: float) -> tuple[float, float]:
    """Heading in degrees -> unit (dx, dy) in the model XY plane."""
    r = math.radians(heading_deg)
    return (math.cos(r), math.sin(r))


# --------------------------------------------------------------------------- #
# Distances
# --------------------------------------------------------------------------- #
def distance3(a: Vec3, b: Vec3) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def distance2(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# --------------------------------------------------------------------------- #
# 4x4 pose helpers
# --------------------------------------------------------------------------- #
def pose_matrix(flat: Sequence[float]) -> np.ndarray:
    """16-element row-major sequence -> 4x4 numpy array."""
    m = np.asarray(flat, dtype=float).reshape(4, 4)
    return m


def camera_position(pose_flat: Sequence[float]) -> Vec3:
    """Extract camera world position (translation column) from a pose."""
    m = pose_matrix(pose_flat)
    return (float(m[0, 3]), float(m[1, 3]), float(m[2, 3]))


def camera_forward(pose_flat: Sequence[float]) -> Vec3:
    """World-space forward direction of an ARKit camera (local -Z)."""
    m = pose_matrix(pose_flat)
    fwd = -m[:3, 2]
    n = np.linalg.norm(fwd)
    if n < 1e-12:
        return (0.0, 0.0, -1.0)
    fwd = fwd / n
    return (float(fwd[0]), float(fwd[1]), float(fwd[2]))


def heading_of_pose_deg(pose_flat: Sequence[float], up_axis: str = "z") -> float:
    """Camera heading in the floorplan plane, degrees.

    ``up_axis`` names the world axis pointing up so the forward vector is
    projected onto the correct ground plane. Defaults to ``z`` (Revit-style).
    """
    fx, fy, fz = camera_forward(pose_flat)
    if up_axis == "z":
        gx, gy = fx, fy
    elif up_axis == "y":
        gx, gy = fx, fz
    else:  # x up
        gx, gy = fy, fz
    return normalize_angle_deg(math.degrees(math.atan2(gy, gx)))


def transform_direction(matrix: np.ndarray, d: Vec3) -> Vec3:
    """Apply only the rotational part of a 4x4 transform to a direction vector."""
    r = matrix[:3, :3]
    out = r @ np.asarray(d, dtype=float)
    return (float(out[0]), float(out[1]), float(out[2]))


def heading_of_pose_deg_from_matrix(
    arkit_to_model: np.ndarray, pose_flat: Sequence[float]
) -> float:
    """Camera heading in the model XY plane after applying ``arkit_to_model``."""
    fwd_arkit = camera_forward(pose_flat)
    fx, fy, _ = transform_direction(arkit_to_model, fwd_arkit)
    return normalize_angle_deg(math.degrees(math.atan2(fy, fx)))


def transform_point(matrix: np.ndarray, p: Vec3) -> Vec3:
    """Apply a 4x4 homogeneous transform to a 3D point."""
    v = np.array([p[0], p[1], p[2], 1.0])
    out = matrix @ v
    if abs(out[3]) > 1e-12:
        out = out / out[3]
    return (float(out[0]), float(out[1]), float(out[2]))


def compose(*matrices: np.ndarray) -> np.ndarray:
    """Left-to-right composition of 4x4 transforms."""
    result = np.eye(4)
    for m in matrices:
        result = result @ m
    return result


def rigid_transform_2d(tx: float, ty: float, rotation_deg: float, scale: float = 1.0) -> np.ndarray:
    """Build a 4x4 transform: rotate about Z then translate in XY (Z untouched)."""
    r = math.radians(rotation_deg)
    cos_r, sin_r = math.cos(r), math.sin(r)
    m = np.eye(4)
    m[0, 0] = scale * cos_r
    m[0, 1] = -scale * sin_r
    m[1, 0] = scale * sin_r
    m[1, 1] = scale * cos_r
    m[0, 3] = tx
    m[1, 3] = ty
    return m


# --------------------------------------------------------------------------- #
# Camera projection (pinhole)
# --------------------------------------------------------------------------- #
def world_to_camera(pose_flat: Sequence[float], p_world: Vec3) -> Vec3:
    """Transform a world point into the camera's local frame."""
    m = pose_matrix(pose_flat)
    inv = np.linalg.inv(m)
    return transform_point(inv, p_world)


def project_point(
    pose_flat: Sequence[float],
    intrinsics: tuple[float, float, float, float],
    p_world: Vec3,
) -> tuple[float, float, float]:
    """Project a world point to pixel coords for an ARKit camera (-Z forward).

    ``intrinsics`` is ``(fx, fy, cx, cy)``. Returns ``(u, v, depth)`` where
    ``depth`` is the positive distance in front of the camera (along -Z);
    ``depth <= 0`` means the point is behind the camera.
    """
    fx, fy, cx, cy = intrinsics
    pc = world_to_camera(pose_flat, p_world)
    depth = -pc[2]  # camera looks down -Z
    if abs(pc[2]) < 1e-9:
        # Point is on (or within epsilon of) the camera plane: projection is
        # undefined. Report depth 0.0 so callers' `depth > 0` frustum test treats
        # it as NOT in view, rather than a spurious visible frame-centre hit.
        return (cx, cy, 0.0)
    u = fx * (pc[0] / -pc[2]) + cx
    v = fy * (pc[1] / -pc[2]) + cy
    return (u, v, depth)


def point_in_view(
    pose_flat: Sequence[float],
    intrinsics: tuple[float, float, float, float],
    width: int,
    height: int,
    p_world: Vec3,
    margin: float = 0.0,
) -> bool:
    """Whether a world point projects in front of the camera and within frame."""
    u, v, depth = project_point(pose_flat, intrinsics, p_world)
    if depth <= 0:
        return False
    return (-margin <= u <= width + margin) and (-margin <= v <= height + margin)
