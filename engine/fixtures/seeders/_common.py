"""Shared, pure seeder helpers for the synthetic fixture corpus.

No heavy deps, no randomness, no clock. These builders emit plain dicts that the
per-scenario seeders assemble into a full manifest / capture, which the pipeline
then turns into a committed golden (see ``regen_goldens.py``).

The ``GENERATED_AT`` determinism constant lives here ONCE; both the golden
regeneration entry point and the golden tests import it from this module so there
is a single source of truth (guarded by ``test_generated_at_single_source``).
"""

from __future__ import annotations

import json
from pathlib import Path

# The fixed report timestamp the regen writer injects AND the golden tests inject.
# Defined ONCE here; regen_goldens.py and test_integration_golden.py import it.
GENERATED_AT = "2026-06-28T00:00:00Z"

# Identity ARKit pose (camera at world origin, looking down -Z, +Y up).
IDENTITY_POSE = [
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
]
INTRINSICS = {"fx": 1000.0, "fy": 1000.0, "cx": 640.0, "cy": 360.0, "width": 1280, "height": 720}
# Floorplan affine: 1 px = 0.01 ft, origin top-left. [a,b,c,d,e,f].
PIXEL_TO_MODEL = [0.01, 0.0, 0.0, 0.0, 0.01, 0.0]

SYNTHETIC_DIR = Path(__file__).resolve().parents[1] / "synthetic"
GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"


def level(level_id, name, elevation, image):
    return {
        "id": level_id,
        "name": name,
        "elevation": elevation,
        "floorplan": {
            "image": image,
            "width_px": 1000,
            "height_px": 800,
            "pixel_to_model": PIXEL_TO_MODEL,
        },
    }


def device(
    did,
    family,
    dtype,
    x,
    y,
    z,
    *,
    level_id="L1",
    facing=0.0,
    mounting_height=None,
    up_axis="up",
    tolerances=None,
    elevation_id="E-NORTH",
):
    d = {
        "id": did,
        "family": family,
        "type": dtype,
        "level_id": level_id,
        "elevation_id": elevation_id,
        "position": {"x": x, "y": y, "z": z},
        "orientation": {"facing_angle": facing, "up_axis": up_axis},
    }
    if mounting_height is not None:
        d["mounting_height"] = mounting_height
    if tolerances is not None:
        d["tolerances"] = tolerances
    return d


def shot(
    shot_id,
    level_id,
    observations,
    *,
    pin=(0.0, 0.0, 0.0, "high"),
    pose=None,
    depth=True,
    elevation_id="E-NORTH",
):
    px, py, heading, conf = pin
    s = {
        "id": shot_id,
        "level_id": level_id,
        "elevation_id": elevation_id,
        "rgb_image": f"{shot_id}.jpg",
        "intrinsics": INTRINSICS,
        "pose": pose or IDENTITY_POSE,
        "pin": {"x": px, "y": py, "heading": heading, "confidence": conf},
        "observations": observations,
    }
    if depth:
        s["depth_map"] = f"{shot_id}_depth.bin"
        s["depth_size"] = [192, 256]
    return s


def observation(
    x, y, z, *, mounting_height=None, facing=None, detected_type=None, type_confidence=None
):
    o = {"position": {"x": x, "y": y, "z": z}}
    if mounting_height is not None:
        o["mounting_height"] = mounting_height
    if facing is not None:
        o["facing_angle"] = facing
    if detected_type is not None:
        o["detected_type"] = detected_type
    if type_confidence is not None:
        o["type_confidence"] = type_confidence
    return o


def manifest(project_id, name, levels, devices):
    """Assemble a full spec manifest with the standard default tolerances."""
    return {
        "schema_version": "1.0.0",
        "project": {
            "id": project_id,
            "name": name,
            "units": "feet",
            "revit_file": f"{project_id}.rvt",
        },
        "coordinate_system": {"name": "Project", "north_angle": 0.0},
        "default_tolerances": {"position": 0.083, "mounting_height": 0.042, "orientation": 10.0},
        "levels": levels,
        "devices": devices,
    }


def capture(project_id, shots):
    """Assemble a full capture package."""
    return {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "device_model": "iPhone 15 Pro",
        "app_version": "0.1.0",
        "shots": shots,
    }


def write_payloads(slug, manifest, capture):
    """Write the manifest+capture for a scenario; return their paths."""
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    mpath = SYNTHETIC_DIR / f"{slug}.manifest.json"
    cpath = SYNTHETIC_DIR / f"{slug}.capture.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    cpath.write_text(json.dumps(capture, indent=2), encoding="utf-8")
    return mpath, cpath
