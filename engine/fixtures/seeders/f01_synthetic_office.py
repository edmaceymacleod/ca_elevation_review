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
import tempfile
from pathlib import Path

# Fixed clock used to stamp the golden deterministically. MUST match the value
# tests/test_integration_golden.py uses (imported from fixtures.seeders._common)
# so the golden this seeder writes is the golden the integration test reproduces.
# test_fixture_drift.py asserts the two literals agree.
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


def _write_authored(path: Path, obj: dict) -> None:
    """Serializer for hand-authored fixtures (manifest, capture).

    Preserves authored key order (sort_keys=False), indent=2, UTF-8, NO trailing
    newline -- byte-identical to the committed manifest/capture and to the rest
    of the synthetic corpus (which is written by ``_common.write_payloads`` the
    same way). The golden, by contrast, IS key-sorted with a trailing newline
    (see ``_write_golden``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _write_golden(path: Path, report) -> None:
    """Serializer for the golden: the engine's own render_json + newline.

    Byte-identical to the committed golden (sorted keys, indent=2, trailing
    newline). Do NOT route the golden through _write_authored -- the committed
    golden is key-sorted, an authored-order dump would churn it.
    """
    from ca_elevation_engine.report.json_report import render_json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_json(report) + "\n", encoding="utf-8")


def build_golden():
    """Produce the F-01 golden report object by running the engine on the
    in-memory manifest/capture, stamped with the fixed GENERATED_AT clock.

    Returns the VerdictReport (the report OBJECT, not its dict/bytes) so the
    caller serializes it via the engine's render_json. Uses the real pipeline so
    the golden can never silently diverge from engine behavior; the integration
    test independently re-derives it as a cross-check.

    Ingest does NOT load the referenced image/depth asset files (it only checks
    the JSON paths it is given), so no asset bytes are needed in the tempdir.
    """
    from ca_elevation_engine.pipeline import run_pipeline

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        _write_authored(tdp / "m.manifest.json", build_manifest())
        _write_authored(tdp / "c.capture.json", build_capture())
        result = run_pipeline(
            tdp / "m.manifest.json",
            tdp / "c.capture.json",
            generated_at=GENERATED_AT,
        )
    return result.report


def write(out_dir: Path) -> dict[str, Path]:
    """Write the F-01 manifest, capture, and golden.

    ``out_dir`` is the *synthetic* directory; the golden is resolved relative to
    it as ``out_dir.parent / "golden"``. This ``out_dir.parent / "golden"``
    contract is load-bearing: regen_fixtures.py relies on it to map outputs to
    committed paths by relative path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "f01_office.manifest.json"
    capture_path = out_dir / "f01_office.capture.json"
    golden_path = out_dir.parent / "golden" / "f01_verdict_report.json"
    _write_authored(manifest_path, build_manifest())
    _write_authored(capture_path, build_capture())
    _write_golden(golden_path, build_golden())
    return {"manifest": manifest_path, "capture": capture_path, "golden": golden_path}


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parents[1]
    paths = write(fixtures_dir / "synthetic")
    for k, v in paths.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
