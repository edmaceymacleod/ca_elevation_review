"""manifest_builder: pure builder assertions (FLOOR) + engine round-trip (ENGINE).

The pure build/raise tests need no engine and run everywhere. The round-trip test
imports ``ca_elevation_engine`` *inside the function* and is marked ``engine`` so
it only runs on the 3.10+ jobs (and collection never imports the engine).
"""

from __future__ import annotations

import pytest
from ca_elevation_revit import manifest_builder
from ca_elevation_revit.manifest_builder import (
    DEFAULT_TOLERANCES,
    FloorplanExport,
    ManifestBuildError,
)


def _export(level_id="L1", basename="plan_L1.png"):
    return FloorplanExport(
        level_id=level_id,
        level_name="Level 1",
        elevation=0.0,
        image_bytes=b"png",
        basename=basename,
        width_px=1000,
        height_px=800,
        pixel_to_model=[0.01, 0.0, 0.0, 0.0, 0.01, 0.0],
    )


def _device(did="uid-1", level_id="L1"):
    return manifest_builder.device_dict(
        did, "Card Reader", "HID-R10", level_id, {"x": 8.0, "y": 0.0, "z": 4.0}, mounting_height=4.0
    )


# --- pure (FLOOR) -------------------------------------------------------- #
def test_build_manifest_shape_and_default_tolerances():
    m = manifest_builder.build_manifest(
        {"id": "p", "name": "P", "units": "feet"}, [_export()], [_device()]
    )
    assert m["schema_version"] == "1.0.0"
    assert m["levels"][0]["floorplan"]["image"] == "plan_L1.png"
    # The C# thresholds are carried over, NOT the engine's own fallback.
    assert m["default_tolerances"] == {
        "position": 0.25,
        "mounting_height": 0.083,
        "orientation": 10.0,
    }
    assert m["default_tolerances"] == DEFAULT_TOLERANCES


def test_device_only_manifest_rejected():
    with pytest.raises(ManifestBuildError, match="floorplan"):
        manifest_builder.build_manifest({"id": "p", "name": "P", "units": "feet"}, [], [_device()])


def test_empty_device_id_rejected():
    with pytest.raises(ManifestBuildError, match="non-empty"):
        manifest_builder.build_manifest(
            {"id": "p", "name": "P", "units": "feet"},
            [_export()],
            [
                {
                    "id": "  ",
                    "family": "f",
                    "type": "t",
                    "level_id": "L1",
                    "position": {"x": 0, "y": 0, "z": 0},
                }
            ],
        )


def test_duplicate_device_id_rejected():
    with pytest.raises(ManifestBuildError, match="duplicate"):
        manifest_builder.build_manifest(
            {"id": "p", "name": "P", "units": "feet"}, [_export()], [_device("d"), _device("d")]
        )


def test_device_unknown_level_rejected():
    with pytest.raises(ManifestBuildError, match="unknown level_id"):
        manifest_builder.build_manifest(
            {"id": "p", "name": "P", "units": "feet"}, [_export("L1")], [_device(level_id="L9")]
        )


def test_bad_affine_length_rejected():
    bad = _export()
    bad.pixel_to_model = [1, 2, 3]
    with pytest.raises(ManifestBuildError, match="6 elements"):
        manifest_builder.build_manifest(
            {"id": "p", "name": "P", "units": "feet"}, [bad], [_device()]
        )


def test_device_dict_requires_unique_id():
    with pytest.raises(ManifestBuildError):
        manifest_builder.device_dict("", "f", "t", "L1", {"x": 0, "y": 0, "z": 0})


# --- engine round-trip (ENGINE, 3.10+) ----------------------------------- #
@pytest.mark.engine
def test_built_manifest_round_trips_and_validates():
    # Imported here (not at module top) so floor-job collection never needs the engine.
    from ca_elevation_engine import ingest
    from ca_elevation_engine.models import SpecManifest

    manifest = manifest_builder.build_manifest(
        {"id": "demo", "name": "Demo", "units": "feet"},
        [_export()],
        [_device("uid-1"), _device("uid-2")],
    )
    # Schema-validate (fail-closed) AND parse into the typed model.
    parsed = ingest.parse_manifest(manifest, validate=True)
    assert isinstance(parsed, SpecManifest)
    assert len(parsed.devices) == 2
    assert parsed.default_tolerances.position == 0.25  # C# threshold survives round-trip
    # to_dict round-trips structurally.
    assert SpecManifest.from_dict(parsed.to_dict()).to_dict() == parsed.to_dict()
