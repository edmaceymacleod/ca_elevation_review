"""Seeder F-01: a fully synthetic single-level office capture.

Deterministic. Builds a spec manifest + capture package engineered so the
pipeline produces one device of every verdict class:

    D-PASS   -- observed within tolerance.
    D-FLAG   -- observed but position out of tolerance (still within match gate).
    D-ABSENT -- expected in a captured view, but nothing observed there.
    D-TYPE   -- observed, but a confident vision guess disagrees on device type.
    D-GAP    -- expected outside any captured view (coverage-gap absence).

This is the fixture-as-single-source-of-truth: tests READ these files, they never
mutate them. Re-run this seeder to regenerate. No randomness, no timestamps that
vary between runs.

Invariants asserted by tests (see tests/test_integration_golden.py):
    F01-1  manifest validates against spec_manifest.schema.json
    F01-2  capture validates against capture_package.schema.json
    F01-3  running the engine reproduces fixtures/golden/f01_verdict_report.json
"""

from __future__ import annotations

import json
from pathlib import Path

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

# Floorplan affine: 1 px = 0.01 ft, origin at top-left. [a,b,c,d,e,f].
PIXEL_TO_MODEL = [0.01, 0.0, 0.0, 0.0, 0.01, 0.0]


def build_manifest() -> dict:
    return {
        "schema_version": "1.0.0",
        "project": {
            "id": "demo-office-01",
            "name": "Synthetic Office -- Floor 1",
            "units": "feet",
            "revit_file": "synthetic_office.rvt",
        },
        "coordinate_system": {"name": "Project", "north_angle": 0.0},
        "default_tolerances": {"position": 0.083, "mounting_height": 0.042, "orientation": 10.0},
        "levels": [
            {
                "id": "L1",
                "name": "Level 1",
                "elevation": 0.0,
                "floorplan": {
                    "image": "plan_L1.png",
                    "width_px": 1000,
                    "height_px": 800,
                    "pixel_to_model": PIXEL_TO_MODEL,
                },
            }
        ],
        "devices": [
            _device("D-PASS", "Card Reader", "HID-R10", 8.0, 0.0, 4.0, facing=0.0),
            _device("D-FLAG", "Card Reader", "HID-R10", 8.0, 2.0, 4.0, facing=0.0),
            _device("D-ABSENT", "Speaker", "JBL-C6", 8.0, -2.0, 4.0, facing=0.0),
            _device("D-TYPE", "Card Reader", "HID-R10", 7.5, 1.0, 4.0, facing=0.0),
            # Behind the camera -> never in view -> coverage-gap absence.
            _device("D-GAP", "Camera", "AXIS-P32", -8.0, 0.0, 7.0, facing=180.0),
        ],
    }


def _device(did, family, dtype, x, y, z, facing):
    return {
        "id": did,
        "family": family,
        "type": dtype,
        "level_id": "L1",
        "elevation_id": "E-NORTH",
        "position": {"x": x, "y": y, "z": z},
        "mounting_height": z,  # level elevation is 0, so height == z
        "orientation": {"facing_angle": facing, "up_axis": "up"},
    }


def build_capture() -> dict:
    return {
        "schema_version": "1.0.0",
        "project_id": "demo-office-01",
        "device_model": "iPhone 15 Pro",
        "app_version": "0.1.0",
        "shots": [
            {
                "id": "S1",
                "level_id": "L1",
                "elevation_id": "E-NORTH",
                "rgb_image": "S1.jpg",
                "depth_map": "S1_depth.bin",
                "depth_size": [192, 256],
                "intrinsics": INTRINSICS,
                "pose": IDENTITY_POSE,
                # Operator at model (0,0) facing +X (heading 0).
                "pin": {"x": 0.0, "y": 0.0, "heading": 0.0, "confidence": "high"},
                "observations": [
                    # D-PASS: tight match.
                    {
                        "position": {"x": 8.02, "y": 0.0, "z": 4.01},
                        "mounting_height": 4.01,
                        "facing_angle": 2.0,
                        "detected_type": "HID-R10",
                        "type_confidence": 0.82,
                    },
                    # D-FLAG: 0.3 ft off in Y (within gate 0.5, beyond tol 0.083).
                    {
                        "position": {"x": 8.0, "y": 2.3, "z": 4.0},
                        "mounting_height": 4.0,
                        "facing_angle": 1.0,
                    },
                    # D-TYPE: right place, wrong (confident) type.
                    {
                        "position": {"x": 7.5, "y": 1.0, "z": 4.0},
                        "mounting_height": 4.0,
                        "facing_angle": 0.0,
                        "detected_type": "Exit Sign",
                        "type_confidence": 0.9,
                    },
                    # (No observation near D-ABSENT at (8,-2,4).)
                ],
            }
        ],
    }


def write(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    manifest_path = out_dir / "f01_office.manifest.json"
    capture_path = out_dir / "f01_office.capture.json"
    manifest_path.write_text(json.dumps(build_manifest(), indent=2), encoding="utf-8")
    capture_path.write_text(json.dumps(build_capture(), indent=2), encoding="utf-8")
    paths["manifest"] = manifest_path
    paths["capture"] = capture_path
    return paths


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parents[1]
    paths = write(fixtures_dir / "synthetic")
    for k, v in paths.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
