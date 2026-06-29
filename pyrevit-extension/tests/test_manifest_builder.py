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


_GOOD_PROJECT = {"id": "p", "name": "P", "units": "feet"}


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


# --- new FLOOR rejection cases (schema subset, no engine) ----------------- #
def test_project_units_must_be_enum():
    with pytest.raises(ManifestBuildError, match="units"):
        manifest_builder.build_manifest(
            {"id": "p", "name": "P", "units": "inches"}, [_export()], [_device()]
        )


def test_project_missing_id_rejected():
    with pytest.raises(ManifestBuildError, match="id"):
        manifest_builder.build_manifest(
            {"id": "", "name": "P", "units": "feet"}, [_export()], [_device()]
        )


def test_nonpositive_width_px_rejected():
    bad = _export()
    bad.width_px = 0
    with pytest.raises(ManifestBuildError, match="positive integer"):
        manifest_builder.build_manifest(_GOOD_PROJECT, [bad], [_device()])


def test_nonpositive_height_px_rejected():
    bad = _export()
    bad.height_px = -5
    with pytest.raises(ManifestBuildError, match="positive integer"):
        manifest_builder.build_manifest(_GOOD_PROJECT, [bad], [_device()])


def test_nonfinite_affine_rejected():
    bad = _export()
    bad.pixel_to_model = [float("nan"), 0, 0, 0, 0.01, 0]
    with pytest.raises(ManifestBuildError, match="finite|number"):
        manifest_builder.build_manifest(_GOOD_PROJECT, [bad], [_device()])


def test_negative_tolerance_rejected():
    with pytest.raises(ManifestBuildError, match="positive"):
        manifest_builder.build_manifest(
            _GOOD_PROJECT, [_export()], [_device()], default_tolerances={"position": -1}
        )


def test_unknown_tolerance_key_rejected():
    with pytest.raises(ManifestBuildError, match="slop|unknown"):
        manifest_builder.build_manifest(
            _GOOD_PROJECT, [_export()], [_device()], default_tolerances={"slop": 1.0}
        )


def test_unknown_device_key_rejected():
    dev = _device()
    dev["sku"] = "x"
    with pytest.raises(ManifestBuildError, match="sku"):
        manifest_builder.build_manifest(_GOOD_PROJECT, [_export()], [dev])


def test_device_position_must_have_xyz():
    dev = _device()
    dev["position"] = {"x": 0, "y": 0}
    with pytest.raises(ManifestBuildError, match="position"):
        manifest_builder.build_manifest(_GOOD_PROJECT, [_export()], [dev])


def test_device_dict_rejects_nonfinite_coord():
    with pytest.raises(ManifestBuildError, match="finite"):
        manifest_builder.device_dict("uid", "f", "t", "L1", {"x": float("inf"), "y": 0, "z": 0})


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


@pytest.mark.engine
def test_built_manifest_round_trips_and_is_capture_compatible(engine_fixtures_dir):
    import os

    from ca_elevation_engine import ingest
    from ca_elevation_engine.models import SpecManifest

    manifest = manifest_builder.build_manifest(
        {"id": "demo-office-01", "name": "Demo", "units": "feet"},
        [_export(level_id="L1")],
        [_device("uid-1", level_id="L1")],
        coordinate_system={"name": "Survey", "north_angle": 12.5},
    )
    parsed = ingest.parse_manifest(manifest, validate=True)
    assert isinstance(parsed, SpecManifest)
    # coordinate_system parses as a plain dict in SpecManifest.
    assert parsed.coordinate_system["north_angle"] == 12.5

    capture = ingest.load_capture(
        os.path.join(engine_fixtures_dir, "f01_office.capture.json"), validate=True
    )
    # check_compatible returns a list of warnings; an empty list == fully compatible.
    assert ingest.check_compatible(parsed, capture) == []


def _good_manifest_dict():
    """A known-good raw manifest dict (built via the builder happy path)."""
    return manifest_builder.build_manifest(_GOOD_PROJECT, [_export()], [_device()])


def _bad_manifest_dicts():
    """One raw bad manifest dict per FLOOR rejection case 1-10.

    Each is constructed by mutating a known-good manifest so only the single
    offending field differs -- so a schema rejection isolates that field.
    """
    import copy

    cases = {}

    m = _good_manifest_dict()
    m["project"]["units"] = "inches"
    cases["units_enum"] = m  # case 1

    m = copy.deepcopy(_good_manifest_dict())
    m["project"]["id"] = ""
    cases["missing_id"] = m  # case 2

    m = copy.deepcopy(_good_manifest_dict())
    m["levels"][0]["floorplan"]["width_px"] = 0
    cases["width_px_zero"] = m  # case 3

    m = copy.deepcopy(_good_manifest_dict())
    m["levels"][0]["floorplan"]["height_px"] = -5
    cases["height_px_neg"] = m  # case 4

    m = copy.deepcopy(_good_manifest_dict())
    m["default_tolerances"]["position"] = -1
    cases["negative_tolerance"] = m  # case 6

    m = copy.deepcopy(_good_manifest_dict())
    m["default_tolerances"]["slop"] = 1.0
    cases["unknown_tolerance_key"] = m  # case 7

    m = copy.deepcopy(_good_manifest_dict())
    m["devices"][0]["sku"] = "x"
    cases["unknown_device_key"] = m  # case 8

    m = copy.deepcopy(_good_manifest_dict())
    m["devices"][0]["position"] = {"x": 0, "y": 0}
    cases["position_missing_z"] = m  # case 9

    # NOTE: cases 5 (non-finite affine) and 10 (non-finite coord) are deliberately
    # EXCLUDED from this subset guard. Empirically the engine's Draft7Validator
    # ACCEPTS NaN/Inf for "type: number" (Python jsonschema treats them as floats),
    # so the builder's finite pre-check is stricter than the schema for those two
    # inputs. The finite guard is still kept (it catches a bad Revit param before
    # the wire -- see test_nonfinite_affine_rejected / test_device_dict_rejects_
    # nonfinite_coord) but it is NOT claimed here as a schema subset.

    return cases


@pytest.mark.engine
@pytest.mark.parametrize("name", sorted(_bad_manifest_dicts().keys()))
def test_builder_prefilter_is_a_schema_subset(name):
    """Every builder-rejected input is ALSO engine-rejected (subset invariant)."""
    from ca_elevation_engine import ingest

    bad = _bad_manifest_dicts()[name]
    with pytest.raises(ingest.ValidationError):
        ingest.parse_manifest(bad, validate=True)


@pytest.mark.engine
def test_device_key_allowlist_matches_schema():
    from ca_elevation_engine import ingest

    schema = ingest.load_schema("spec_manifest")
    assert manifest_builder._DEVICE_KEYS == set(schema["$defs"]["device"]["properties"])
