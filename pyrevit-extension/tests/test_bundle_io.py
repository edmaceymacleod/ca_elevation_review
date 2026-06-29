"""FLOOR tier: field-bundle write + capture read round-trips (stdlib only)."""

from __future__ import annotations

import json
import os

import pytest
from ca_elevation_revit import bundle_io, manifest_builder
from ca_elevation_revit.manifest_builder import FloorplanExport


def _export(level_id="L1", basename="plan_L1.png"):
    return FloorplanExport(
        level_id=level_id,
        level_name="Level 1",
        elevation=0.0,
        image_bytes=b"\x89PNG\r\n\x1a\n-fake-png-bytes",
        basename=basename,
        width_px=1000,
        height_px=800,
        pixel_to_model=[0.01, 0.0, 0.0, 0.0, 0.01, 0.0],
    )


def _manifest(exports):
    devices = [
        manifest_builder.device_dict(
            "uid-1", "Card Reader", "HID-R10", "L1", {"x": 8.0, "y": 0.0, "z": 4.0}
        )
    ]
    return manifest_builder.build_manifest(
        {"id": "p", "name": "P", "units": "feet"}, exports, devices
    )


def test_write_field_bundle_writes_manifest_and_images(tmp_path):
    exports = [_export()]
    manifest = _manifest(exports)
    written = bundle_io.write_field_bundle(str(tmp_path), manifest, exports)

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    assert (tmp_path / "plan_L1.png").read_bytes() == exports[0].image_bytes
    reloaded = json.loads(manifest_path.read_text())
    assert reloaded["levels"][0]["floorplan"]["image"] == "plan_L1.png"
    assert os.path.basename(written["manifest"]) == "manifest.json"


def test_manifest_image_and_record_basename_cannot_diverge(tmp_path):
    exports = [_export(basename="plan_L1.png")]
    manifest = _manifest(exports)
    # Tamper the manifest so its referenced image no longer matches the record.
    manifest["levels"][0]["floorplan"]["image"] = "other.png"
    with pytest.raises(ValueError, match="do not match"):
        bundle_io.write_field_bundle(str(tmp_path), manifest, exports)


def test_basename_escaping_bundle_dir_is_rejected(tmp_path):
    exports = [_export(basename="../escape.png")]
    manifest = _manifest(exports)
    with pytest.raises(ValueError, match="escapes"):
        bundle_io.write_field_bundle(str(tmp_path), manifest, exports)


def test_read_capture_package_round_trip(tmp_path):
    payload = {"schema_version": "1.0.0", "project_id": "p", "shots": []}
    p = tmp_path / "capture.json"
    p.write_text(json.dumps(payload))
    assert bundle_io.read_capture_package(str(p)) == payload


# --- read_capture_package error surface (FLOOR) -------------------------- #
def test_read_capture_missing_file_raises_bundle_error(tmp_path):
    with pytest.raises(bundle_io.BundleReadError, match="not found"):
        bundle_io.read_capture_package(str(tmp_path / "nope.json"))


def test_read_capture_malformed_json_raises_bundle_error(tmp_path):
    p = tmp_path / "capture.json"
    p.write_text("{not json")
    with pytest.raises(bundle_io.BundleReadError, match="not valid JSON"):
        bundle_io.read_capture_package(str(p))


def test_read_capture_non_object_raises(tmp_path):
    p = tmp_path / "capture.json"
    p.write_text("[1,2,3]")
    with pytest.raises(bundle_io.BundleReadError, match="object"):
        bundle_io.read_capture_package(str(p))


def test_read_capture_partial_payload_returns_dict(tmp_path):
    # bundle_io does NOT schema-validate; a capture missing 'shots' still reads,
    # returned unchanged. The engine owns schema validation.
    payload = {"schema_version": "1.0.0", "project_id": "p"}
    p = tmp_path / "capture.json"
    p.write_text(json.dumps(payload))
    assert bundle_io.read_capture_package(str(p)) == payload


# --- write_field_bundle edges (FLOOR) ------------------------------------ #
def test_write_field_bundle_nested_basename_creates_subdir(tmp_path):
    image_bytes = b"\x89PNG\r\n\x1a\n-nested"
    fp = FloorplanExport(
        level_id="L1",
        level_name="Level 1",
        elevation=0.0,
        image_bytes=image_bytes,
        basename="floorplans/level_1.png",
        width_px=1000,
        height_px=800,
        pixel_to_model=[0.01, 0.0, 0.0, 0.0, 0.01, 0.0],
    )
    manifest = _manifest([fp])
    bundle_io.write_field_bundle(str(tmp_path), manifest, [fp])
    assert (tmp_path / "floorplans" / "level_1.png").read_bytes() == image_bytes
    assert manifest["levels"][0]["floorplan"]["image"] == "floorplans/level_1.png"


def test_write_field_bundle_absolute_basename_rejected(tmp_path):
    fp = _export(basename="/etc/evil.png")
    manifest = _manifest([fp])
    with pytest.raises(ValueError, match="relative"):
        bundle_io.write_field_bundle(str(tmp_path), manifest, [fp])


def test_write_field_bundle_partial_manifest_record_mismatch(tmp_path):
    exports = [_export(level_id="L1", basename="plan_L1.png")]
    manifest = _manifest(exports)
    # Add a second export the manifest does not reference (2 records vs 1 image).
    exports.append(
        FloorplanExport(
            level_id="L2",
            level_name="Level 2",
            elevation=10.0,
            image_bytes=b"\x89PNG\r\n\x1a\n-2",
            basename="plan_L2.png",
            width_px=1000,
            height_px=800,
            pixel_to_model=[0.01, 0.0, 0.0, 0.0, 0.01, 0.0],
        )
    )
    with pytest.raises(ValueError, match="do not match"):
        bundle_io.write_field_bundle(str(tmp_path), manifest, exports)


def test_write_field_bundle_is_sole_writer_idempotent(tmp_path):
    exports = [_export()]
    manifest = _manifest(exports)
    bundle_io.write_field_bundle(str(tmp_path), manifest, exports)
    bundle_io.write_field_bundle(str(tmp_path), manifest, exports)
    # Second call overwrites cleanly: same bytes, no stale extra files.
    assert (tmp_path / "plan_L1.png").read_bytes() == exports[0].image_bytes
    entries = sorted(os.listdir(str(tmp_path)))
    assert entries == ["manifest.json", "plan_L1.png"]


# --- engine round-trip (ENGINE, 3.10+) ----------------------------------- #
@pytest.mark.engine
def test_written_bundle_loads_through_engine(tmp_path):
    from ca_elevation_engine import ingest
    from ca_elevation_engine.models import SpecManifest

    exports = [_export()]
    manifest = _manifest(exports)
    bundle_io.write_field_bundle(str(tmp_path), manifest, exports)
    parsed = ingest.load_manifest(str(tmp_path / "manifest.json"), validate=True)
    assert isinstance(parsed, SpecManifest)
