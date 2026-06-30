"""Optional point-cloud ingest for the heavy registration path.

Resolves and loads the binary point cloud a shot references (``shot.point_cloud``,
a path relative to the capture bundle) into an (N,3) float64 numpy array in the
capture's ARKit world frame. E57 is read via pye57; PLY/PCD/XYZ/PTS via Open3D.
Both are OPTIONAL [heavy] backends, imported lazily; absence is reported, never
fatal.

Pure helpers (downsampling, the model-surface target) are numpy-only so they are
unit-testable headlessly with no heavy backend installed.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .models import SpecManifest


class PointCloudBackendMissing(RuntimeError):
    """Raised when a cloud is present but no heavy backend can read it."""


class PointCloudPathError(ValueError):
    """Resolution/containment failure for a bundle-relative cloud path.

    A ValueError subclass so callers that already degrade on ValueError catch it,
    while still letting tests assert the precise security signal by type.
    """


SUPPORTED_SUFFIXES = (".e57", ".ply", ".pcd", ".xyz", ".pts")


def resolve_cloud_path(rel_path: str | None, bundle_dir: str | None) -> Path | None:
    """Resolve a bundle-relative cloud path, guarding against traversal.

    The candidate is fully resolved (``Path.resolve``) before the containment
    check, so symlinks anywhere in the joined path are followed to their real
    target. This rejects both ``../`` traversal and an in-bundle symlink that
    points outside the bundle (the capture bundle is untrusted iOS-supplied
    content). Returns ``None`` when there is nothing to resolve (no ``rel_path``
    or no ``bundle_dir``). Raises :class:`PointCloudPathError` (a ``ValueError``)
    when the path is absolute or escapes the bundle. The returned ``Path`` may or
    may not exist; existence is the loader's concern (see
    :func:`load_point_cloud`).
    """
    if not rel_path or bundle_dir is None:
        return None
    base = Path(bundle_dir).resolve()  # real path of the bundle root
    # Reject absolute rel_path outright (would escape the bundle by construction).
    if Path(rel_path).is_absolute():
        raise PointCloudPathError("point_cloud path must be bundle-relative")
    # Resolve the FULL joined path (strict=False: the file need not exist yet).
    # .resolve() follows symlinks, so an in-bundle symlink that points outside
    # the bundle resolves to its real out-of-bundle target and is rejected by the
    # containment check below -- unlike a purely lexical os.path.normpath, which
    # would leave the symlink lexically inside `base`. An in-tree
    # `clouds/../clouds/s.ply` still normalizes back inside the bundle.
    cand = (base / rel_path).resolve()
    if cand != base and base not in cand.parents:
        raise PointCloudPathError("point_cloud path escapes bundle")
    return cand  # may or may not exist; the loader decides existence


def load_point_cloud(
    rel_path: str | None, bundle_dir: str | None, *, max_points: int = 200_000
) -> np.ndarray:
    """Load a bundle-relative point cloud into an (N,3) float64 numpy array.

    Raises on any failure (the caller in :mod:`register` degrades on these):

    - ``ValueError`` when there is no cloud / no bundle dir, an unsupported
      suffix, or an empty cloud after the NaN/Inf filter.
    - :class:`PointCloudPathError` (a ``ValueError``) when the path escapes the
      bundle.
    - ``FileNotFoundError`` when the resolved file is absent.
    - :class:`PointCloudBackendMissing` when the heavy reader is not installed.
    """
    path = resolve_cloud_path(rel_path, bundle_dir)
    if path is None:
        raise ValueError("no point_cloud / no bundle_dir")
    if not path.exists():
        raise FileNotFoundError(str(path))

    suffix = path.suffix.lower()
    if suffix == ".e57":
        pts = _load_e57(path)
    elif suffix in (".ply", ".pcd", ".xyz", ".pts"):
        pts = _load_o3d(path)
    else:
        raise ValueError(f"unsupported point-cloud format: {suffix}")

    pts = np.asarray(pts, dtype=np.float64)
    pts = pts[np.isfinite(pts).all(axis=1)]
    if len(pts) == 0:
        raise ValueError("empty point cloud after NaN/Inf filter")
    if len(pts) > max_points:
        # Deterministic uniform stride -- no RNG, so heavy tests reproduce.
        stride = math.ceil(len(pts) / max_points)
        pts = pts[::stride]
    return np.ascontiguousarray(pts, dtype=np.float64)


def _load_e57(path: Path) -> np.ndarray:  # pragma: no cover - heavy
    """Read ALL scans of an E57 file via pye57 (lazy import).

    E57 scans share a common coordinate frame, so every scan is read and
    vstacked rather than silently dropping all but scan 0 (a terrestrial-scanner
    survey commonly carries multiple scans).

    PROVISIONAL: the pye57 API varies across 0.x releases. Verified against the
    pye57 dict-returning ``read_scan`` API (keys ``cartesianX/Y/Z``). Re-pin and
    re-verify against the resolved pye57 version before relying on E57 ingest in
    production -- this path has no automated CI coverage (see spec sec 3.3).
    """
    try:
        import pye57
    except Exception as exc:
        raise PointCloudBackendMissing("pye57 not installed; cannot read E57") from exc
    e57 = pye57.E57(str(path))
    if e57.scan_count < 1:
        raise ValueError(f"E57 has no scans: {path}")
    scans = []
    for scan_index in range(e57.scan_count):
        data = e57.read_scan(scan_index, ignore_missing_fields=True)
        scans.append(np.column_stack([data["cartesianX"], data["cartesianY"], data["cartesianZ"]]))
    xyz = np.vstack(scans) if len(scans) > 1 else scans[0]
    return np.ascontiguousarray(xyz, dtype=np.float64)


def _load_o3d(path: Path) -> np.ndarray:  # pragma: no cover - heavy
    """Read PLY/PCD/XYZ/PTS via Open3D (lazy import)."""
    try:
        import open3d as o3d
    except Exception as exc:
        raise PointCloudBackendMissing("open3d not installed; cannot read this cloud") from exc
    pcd = o3d.io.read_point_cloud(str(path))
    pts = np.asarray(pcd.points, dtype=np.float64)
    if pts.size == 0:
        raise ValueError(f"empty point cloud: {path}")
    return pts


def model_surface_target(
    manifest: SpecManifest,
    level_id: str,
    *,
    spacing: float = 0.5,
    floor_pad: float = 3.0,
    device_cluster_pts: int = 1,
) -> np.ndarray | None:
    """Build a sparse model-surface target for ICP on the given level.

    The engine inputs carry no model mesh, only device positions and the level
    elevation. The target is built from two parts, weighted toward the
    hypothesis-free floor plane:

    - **Floor plane patch (primary):** a dense grid at ``z = level.elevation``
      spanning the XY bounding box of the level's devices, padded by ``floor_pad``
      and sampled at ``spacing``. This dominates the point count and is
      independent of whether any device is actually installed.
    - **Device clusters (secondary, weak cue):** ``device_cluster_pts`` points at
      each device position. Intentionally tiny so a missing-on-site device does
      not meaningfully pull the rigid fit.

    Returns ``None`` when the level has no devices (nothing anchors the extent).
    Deterministic: grid generation uses ``np.arange``/``np.meshgrid`` only, no RNG.
    """
    devices = [d for d in manifest.devices if d.level_id == level_id]
    if not devices:
        return None
    level = manifest.level_by_id(level_id)
    elevation = level.elevation if level is not None else 0.0

    xs = np.array([d.position.x for d in devices], dtype=np.float64)
    ys = np.array([d.position.y for d in devices], dtype=np.float64)
    x_min, x_max = float(xs.min()) - floor_pad, float(xs.max()) + floor_pad
    y_min, y_max = float(ys.min()) - floor_pad, float(ys.max()) + floor_pad

    # +spacing on the stop so a single-device level still yields a real grid.
    gx = np.arange(x_min, x_max + spacing, spacing)
    gy = np.arange(y_min, y_max + spacing, spacing)
    mx, my = np.meshgrid(gx, gy, indexing="ij")
    floor = np.column_stack([mx.ravel(), my.ravel(), np.full(mx.size, elevation, dtype=np.float64)])

    n_cluster = max(0, device_cluster_pts)
    clusters = np.array(
        [[d.position.x, d.position.y, d.position.z] for d in devices for _ in range(n_cluster)],
        dtype=np.float64,
    ).reshape(-1, 3)

    if clusters.size:
        target = np.vstack([floor, clusters])
    else:
        target = floor
    return np.ascontiguousarray(target, dtype=np.float64)


def _downsample(pts: np.ndarray, voxel: float) -> np.ndarray:
    """Voxel-grid downsample returning real original input points.

    Returns the first original point per occupied voxel, ordered by first
    appearance in the input. Deterministic; pure numpy (no Open3D).
    """
    if voxel <= 0:
        raise ValueError("voxel must be > 0")
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) == 0:
        return pts
    keys = np.floor(pts / voxel).astype(np.int64)  # integer voxel coords
    # `return_index` gives the index of the first occurrence of each unique key in
    # SORTED order; sort those indices ascending to recover original (input) order,
    # then index back into `pts` so we return ACTUAL input points.
    _, idx = np.unique(keys, axis=0, return_index=True)
    idx = np.sort(idx)
    return pts[idx]
