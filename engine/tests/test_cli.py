"""CLI surface tests -- the contract the Revit add-in invokes out-of-process."""

from __future__ import annotations

import json

import pytest

from ca_elevation_engine.cli import main

pytestmark = pytest.mark.unit


def test_run_writes_report_and_exits_zero(tmp_path, f01_manifest_path, f01_capture_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "run",
            "--manifest",
            str(f01_manifest_path),
            "--capture",
            str(f01_capture_path),
            "--out",
            str(out),
            "--generated-at",
            "2026-06-28T00:00:00Z",
        ]
    )
    assert code == 0
    report = json.loads((out / "verdict_report.json").read_text())
    assert report["summary"]["total"] == 5
    # Default format is PDF, but the CLI degrades to a self-contained HTML report
    # when the optional reportlab backend is absent (the engine_no_report CI leg).
    import importlib.util

    if importlib.util.find_spec("reportlab") is not None:
        assert (out / "report.pdf").exists()
        assert (out / "report.pdf").read_bytes().startswith(b"%PDF")
    else:
        assert (out / "report.html").exists()
        assert not (out / "report.pdf").exists()
        assert (
            (out / "report.html").read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")
        )
    captured = capsys.readouterr()
    assert "PASS" in captured.out  # text summary


def test_run_format_json_only(tmp_path, f01_manifest_path, f01_capture_path):
    out = tmp_path / "out"
    code = main(
        [
            "run",
            "--manifest",
            str(f01_manifest_path),
            "--capture",
            str(f01_capture_path),
            "--out",
            str(out),
            "--format",
            "json",
            "--quiet",
        ]
    )
    assert code == 0
    assert (out / "verdict_report.json").exists()
    assert not (out / "report.html").exists()


def test_validate_ok(f01_manifest_path, f01_capture_path, capsys):
    code = main(
        ["validate", "--manifest", str(f01_manifest_path), "--capture", str(f01_capture_path)]
    )
    assert code == 0
    assert "manifest OK" in capsys.readouterr().out


def test_validate_bad_manifest_exits_one(tmp_path, f01_manifest_path):
    bad = tmp_path / "bad.json"
    data = json.loads(f01_manifest_path.read_text())
    del data["project"]["units"]
    bad.write_text(json.dumps(data))
    code = main(["validate", "--manifest", str(bad)])
    assert code == 1


def test_schema_subcommand(capsys):
    code = main(["schema", "spec_manifest"])
    assert code == 0
    out = capsys.readouterr().out
    assert json.loads(out)["title"] == "Spec Manifest"


def test_run_no_validate_emits_warning(tmp_path, f01_manifest_path, f01_capture_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "run",
            "--manifest",
            str(f01_manifest_path),
            "--capture",
            str(f01_capture_path),
            "--out",
            str(out),
            "--format",
            "json",
            "--no-validate",
            "--quiet",
        ]
    )
    assert code == 0
    # The skipped-validation warning is printed so a --no-validate run is not
    # indistinguishable from a fully validated one.
    err = capsys.readouterr().err
    assert "validation was SKIPPED" in err


def test_run_missing_file_exits_one(tmp_path, f01_capture_path):
    code = main(
        [
            "run",
            "--manifest",
            "/no/such.json",
            "--capture",
            str(f01_capture_path),
            "--out",
            str(tmp_path / "o"),
        ]
    )
    assert code == 1
