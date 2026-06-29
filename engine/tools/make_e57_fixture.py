"""Generate the committed, genuine E57 scanner fixture used by the heavy E57 test.

This writes a REAL E57 container (ASTM E2807) via ``pye57`` -- not a stub -- that
mimics a single-scan SiteScape/Polycam-style export: a posed point cloud whose
*global* (pose-applied) coordinates are the model-surface points of a tiny
synthetic project, seen through the inverse of a deliberately-perturbed "true"
camera transform. Reading it back through the production loader
(:func:`ca_elevation_engine.pointcloud.load_point_cloud`, which calls
``read_scan(transform=True)``) must reproduce those global coordinates, proving
the loader honours the E57 pose/coordinate/scaling conventions -- not just the
identity-pose happy path.

The geometry constants here are mirrored verbatim by ``tests/test_e57_heavy.py``;
the test recomputes the expected cloud live and asserts the loaded cloud matches,
so any drift between this generator and the test fails loudly.

Run (needs the [heavy] extra for pye57):

    python -m tools.make_e57_fixture

It is committed output -- E57 containers embed GUIDs/timestamps, so the bytes are
not reproducible; regenerate only when the geometry contract changes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ca_elevation_engine import pointcloud as pc
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
from ca_elevation_engine.register import coarse_register

# --- Geometry contract (MUST match tests/test_e57_heavy.py) ----------------- #
DEVICE_POS = (8.0, 0.0, 4.0)
LEVEL_ELEVATION = 0.0
COARSE_OFFSET = np.array([0.2, 0.0, 0.05])  # how far the coarse transform is "off"
# E57 scan pose: a non-trivial rotation+translation so the test proves the loader
# applies it (global != local). 90 deg about +Z, translated well away from origin.
E57_ROTATION_DEG = 90.0
E57_TRANSLATION = np.array([10.0, 20.0, 30.0])

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "scanner" / "f08_posed_scan.e57"


def build_manifest() -> SpecManifest:
    level = Level(
        id="L1",
        name="L1",
        elevation=LEVEL_ELEVATION,
        floorplan=Floorplan("p.png", 1000, 1000, [0.01, 0, 0, 0, 0.01, 0]),
    )
    device = Device(id="d1", family="F", type="T", level_id="L1", position=Point3(*DEVICE_POS))
    return SpecManifest(
        schema_version="1.0.0",
        project=Project(id="p", name="P", units="feet"),
        levels=[level],
        devices=[device],
    )


def build_shot() -> Shot:
    return Shot(
        id="s",
        level_id="L1",
        rgb_image="r.jpg",
        intrinsics=Intrinsics(1000, 1000, 640, 360, 1280, 720),
        pose=np.eye(4).flatten().tolist(),
        pin=Pin(x=0.0, y=0.0, heading=0.0),
        # Path is relative to the bundle dir = engine/fixtures/, where the test
        # points bundle_dir; this is the committed fixture's actual location.
        point_cloud="scanner/f08_posed_scan.e57",
    )


def arkit_frame_cloud() -> np.ndarray:
    """The cloud the scanner "captured", in the capture's ARKit world frame.

    It is the model-surface target seen through the inverse of the TRUE camera
    transform (coarse perturbed by COARSE_OFFSET). Under the coarse transform the
    cloud lands COARSE_OFFSET away from the model surfaces, so ICP has real work.
    """
    manifest = build_manifest()
    coarse = coarse_register(build_shot(), manifest.level_by_id("L1"), units="feet")
    target = pc.model_surface_target(manifest, "L1")
    true_transform = np.eye(4)
    true_transform[:3, 3] = COARSE_OFFSET
    true_transform = true_transform @ coarse.arkit_to_model
    inv_true = np.linalg.inv(true_transform)
    return (inv_true[:3, :3] @ target.T).T + inv_true[:3, 3]


def main() -> None:
    import pye57
    from pyquaternion import Quaternion

    global_pts = arkit_frame_cloud()  # what read_scan(transform=True) must reproduce
    q = Quaternion(axis=[0, 0, 1], degrees=E57_ROTATION_DEG)
    rot = q.rotation_matrix
    # Store LOCAL points so that rot @ local + t == global. The E57 pose carries
    # the rest, exactly as a real scanner export stores it.
    local = (rot.T @ (global_pts - E57_TRANSLATION).T).T

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if FIXTURE.exists():
        FIXTURE.unlink()
    e57 = pye57.E57(str(FIXTURE), mode="w")
    data = {
        "cartesianX": np.ascontiguousarray(local[:, 0]),
        "cartesianY": np.ascontiguousarray(local[:, 1]),
        "cartesianZ": np.ascontiguousarray(local[:, 2]),
    }
    e57.write_scan_raw(
        data, name="f08_posed_scan", rotation=q.elements, translation=E57_TRANSLATION
    )
    e57.close()
    print(f"wrote {FIXTURE} ({FIXTURE.stat().st_size} bytes, {len(global_pts)} points)")


if __name__ == "__main__":
    main()
