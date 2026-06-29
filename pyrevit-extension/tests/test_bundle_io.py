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
