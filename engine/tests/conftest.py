"""Shared pytest fixtures: paths to the immutable seeded fixtures.

Tests READ these; they never write to the ``fixtures/`` tree (the design doc's
fixture-as-single-source-of-truth rule).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ENGINE_ROOT / "fixtures"


def _floor_and_cluster(
    *,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    elevation: float = 0.0,
    device_xy: tuple[float, float] = (8.0, 0.0),
    device_z: float = 4.0,
) -> np.ndarray:
    """A small synthetic cloud: a 5x5 floor grid plus a tiny device cluster.

    ``offset`` is added to every point so a heavy ICP test can ask the registration
    to recover the inverse offset. Deterministic; no RNG.
    """
    gx = np.arange(-2.0, 2.0 + 1.0, 1.0)
    gy = np.arange(-2.0, 2.0 + 1.0, 1.0)
    mx, my = np.meshgrid(gx, gy, indexing="ij")
    floor = np.column_stack([mx.ravel(), my.ravel(), np.full(mx.size, elevation, dtype=np.float64)])
    cluster = np.array(
        [
            [device_xy[0], device_xy[1], device_z],
            [device_xy[0] + 0.05, device_xy[1], device_z],
            [device_xy[0], device_xy[1] + 0.05, device_z],
        ],
        dtype=np.float64,
    )
    pts = np.vstack([floor, cluster])
    return pts + np.asarray(offset, dtype=np.float64)


@pytest.fixture
def make_cloud():
    """numpy factory: (N,3) floor grid + device cluster, optional applied offset."""
    return _floor_and_cluster


@pytest.fixture
def tiny_ply_path(tmp_path):
    """Write a minimal ASCII PLY into a tmp bundle dir (no heavy dep needed).

    Returns ``(ply_path, bundle_dir)``. ``ply_path`` lives at ``clouds/s.ply``
    under the bundle so path-resolution is exercised too.
    """
    pts = _floor_and_cluster()
    bundle_dir = tmp_path / "bundle"
    clouds = bundle_dir / "clouds"
    clouds.mkdir(parents=True)
    ply = clouds / "s.ply"
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
    ply.write_text("\n".join(header + body) + "\n")
    return ply, bundle_dir


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def f01_manifest_path() -> Path:
    return FIXTURES / "synthetic" / "f01_office.manifest.json"


@pytest.fixture(scope="session")
def f01_capture_path() -> Path:
    return FIXTURES / "synthetic" / "f01_office.capture.json"


@pytest.fixture(scope="session")
def f01_golden() -> dict:
    return json.loads((FIXTURES / "golden" / "f01_verdict_report.json").read_text())
