"""Schema validation and cross-payload checks."""

from __future__ import annotations

import json

import pytest

from ca_elevation_engine import ingest
from ca_elevation_engine.ingest import ValidationError

pytestmark = pytest.mark.unit


def test_load_valid_fixtures(f01_manifest_path, f01_capture_path):
    m = ingest.load_manifest(f01_manifest_path)
    c = ingest.load_capture(f01_capture_path)
    assert len(m.devices) == 5
    assert ingest.check_compatible(m, c) == []  # all levels covered


def test_schema_bundled_loads():
    for name in ("spec_manifest", "capture_package", "verdict_report"):
        schema = ingest.load_schema(name)
        assert schema["$schema"].startswith("http")


def test_missing_required_field_fails(f01_manifest_path):
    data = json.loads(f01_manifest_path.read_text())
    del data["project"]["units"]
    with pytest.raises(ValidationError):
        ingest.parse_manifest(data)


def test_bad_affine_length_fails(f01_manifest_path):
    data = json.loads(f01_manifest_path.read_text())
    data["levels"][0]["floorplan"]["pixel_to_model"] = [1, 2, 3]
    with pytest.raises(ValidationError):
        ingest.parse_manifest(data)


def test_duplicate_device_ids_fail(f01_manifest_path):
    data = json.loads(f01_manifest_path.read_text())
    data["devices"][1]["id"] = data["devices"][0]["id"]
    with pytest.raises(ValidationError, match="duplicate device ids"):
        ingest.parse_manifest(data)


def test_device_unknown_level_fails(f01_manifest_path):
    data = json.loads(f01_manifest_path.read_text())
    data["devices"][0]["level_id"] = "NOPE"
    with pytest.raises(ValidationError, match="unknown level_id"):
        ingest.parse_manifest(data)


def test_project_id_mismatch_raises(f01_manifest_path, f01_capture_path):
    m = ingest.load_manifest(f01_manifest_path)
    data = json.loads(f01_capture_path.read_text())
    data["project_id"] = "different"
    c = ingest.parse_capture(data)
    with pytest.raises(ValidationError, match="does not match"):
        ingest.check_compatible(m, c)


def test_capture_unknown_level_raises(f01_manifest_path, f01_capture_path):
    m = ingest.load_manifest(f01_manifest_path)
    data = json.loads(f01_capture_path.read_text())
    data["shots"][0]["level_id"] = "L9"
    c = ingest.parse_capture(data)
    with pytest.raises(ValidationError, match="unknown level_id"):
        ingest.check_compatible(m, c)


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        ingest.load_manifest("/no/such/file.json")
