"""Integration: run the engine over the seeded fixture and diff against golden.

This is the determinism guard. Re-running the pipeline on the immutable F-01
fixture must reproduce ``fixtures/golden/f01_verdict_report.json`` byte-for-byte
at the dict level. If the engine's behaviour changes intentionally, regenerate
the golden via the seeder + a deliberate update -- never let the test write it.
"""

from __future__ import annotations

import json

import pytest
from fixtures.seeders._common import GENERATED_AT  # single source of the constant

import ca_elevation_engine
from ca_elevation_engine import ingest, registry
from ca_elevation_engine.pipeline import run_pipeline

pytestmark = pytest.mark.integration


def test_pipeline_reproduces_golden(f01_manifest_path, f01_capture_path, f01_golden):
    import ca_elevation_engine

    result = run_pipeline(f01_manifest_path, f01_capture_path, generated_at=GENERATED_AT)
    produced = result.report.to_dict()
    # engine_version is stamped from the package version, not the golden; assert it
    # is present and correct (catches a None/empty regression) THEN drop it before
    # comparing the rest exactly.
    assert produced.get("engine_version") == ca_elevation_engine.__version__
    assert produced["engine_version"]  # non-empty
    produced.pop("engine_version", None)
    golden = dict(f01_golden)
    golden.pop("engine_version", None)
    assert produced == golden


def test_golden_summary(f01_golden):
    assert f01_golden["summary"] == {
        "total": 5,
        "pass": 1,
        "flag": 1,
        "absent": 2,
        "type_mismatch": 1,
    }


def test_fixtures_validate_against_schemas(f01_manifest_path, f01_capture_path):
    # F01-1 / F01-2 invariants.
    ingest.load_manifest(f01_manifest_path)
    ingest.load_capture(f01_capture_path)


def test_pipeline_writes_reports(tmp_path, f01_manifest_path, f01_capture_path):
    result = run_pipeline(
        f01_manifest_path,
        f01_capture_path,
        generated_at=GENERATED_AT,
        out_dir=tmp_path,
        report_format="html",
    )
    assert (tmp_path / "verdict_report.json").exists()
    assert (tmp_path / "report.html").exists()
    assert "json" in result.written and "html" in result.written


def test_pipeline_writes_pdf_by_default(tmp_path, f01_manifest_path, f01_capture_path):
    pytest.importorskip("reportlab")
    result = run_pipeline(
        f01_manifest_path,
        f01_capture_path,
        generated_at=GENERATED_AT,
        out_dir=tmp_path,
    )
    pdf = tmp_path / "report.pdf"
    assert pdf.exists()
    assert pdf.read_bytes().startswith(b"%PDF")
    assert "pdf" in result.written


def test_pipeline_falls_back_to_html_without_pdf_backend(
    tmp_path, f01_manifest_path, f01_capture_path, monkeypatch
):
    # Simulate the PDF backend being unavailable.
    from ca_elevation_engine.report import pdf as pdf_mod

    def _boom(*args, **kwargs):
        raise pdf_mod.MissingPdfBackend("no reportlab")

    monkeypatch.setattr(pdf_mod, "render_pdf", _boom)
    result = run_pipeline(
        f01_manifest_path,
        f01_capture_path,
        generated_at=GENERATED_AT,
        out_dir=tmp_path,
        report_format="pdf",
    )
    assert (tmp_path / "report.html").exists()
    assert not (tmp_path / "report.pdf").exists()
    assert any("Falling back to HTML" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
# Corpus-wide parametrized golden + payload-validation tests (every scenario).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("scenario,golden_name", list(registry.SCENARIO_GOLDENS.items()))
def test_scenario_reproduces_golden(scenario, golden_name, fixtures_dir):
    stem = registry.SCENARIO_PAYLOAD_STEMS[scenario]
    mpath = fixtures_dir / "synthetic" / f"{stem}.manifest.json"
    cpath = fixtures_dir / "synthetic" / f"{stem}.capture.json"
    golden = json.loads((fixtures_dir / "golden" / golden_name).read_text())
    result = run_pipeline(mpath, cpath, generated_at=GENERATED_AT)
    produced = result.report.to_dict()
    assert produced.get("engine_version") == ca_elevation_engine.__version__
    produced.pop("engine_version", None)
    golden.pop("engine_version", None)
    assert produced == golden, f"{scenario} drifted from golden"


@pytest.mark.parametrize("scenario", list(registry.SCENARIO_GOLDENS))
def test_scenario_payloads_validate(scenario, fixtures_dir):
    stem = registry.SCENARIO_PAYLOAD_STEMS[scenario]
    ingest.load_manifest(fixtures_dir / "synthetic" / f"{stem}.manifest.json")
    ingest.load_capture(fixtures_dir / "synthetic" / f"{stem}.capture.json")


# --------------------------------------------------------------------------- #
# Intent-pinning assertions: catch a golden silently drifting to a different but
# self-consistent verdict mix, plus the two fixed ABSENT confidences.
# --------------------------------------------------------------------------- #


def _golden(fixtures_dir, name):
    return json.loads((fixtures_dir / "golden" / name).read_text())


def _by_id(golden):
    return {r["device_id"]: r for r in golden["device_results"]}


def test_f02_datum_paths(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f02_multilevel_datum_verdict_report.json"))
    assert r["D-L2-DATUM-PASS"]["verdict"] == "pass"
    assert r["D-L2-HEIGHT-FLAG"]["verdict"] == "flag"
    assert any("mounting height" in n for n in r["D-L2-HEIGHT-FLAG"]["notes"])
    assert r["D-L2-HEIGHT-PASS"]["verdict"] == "pass"


def test_f03_boundary_directions(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f03_tolerance_boundary_verdict_report.json"))
    assert r["D-POS-INSIDE"]["verdict"] == "pass"
    assert r["D-POS-OUTSIDE"]["verdict"] == "flag"
    assert r["D-ORIENT-OUTSIDE"]["verdict"] == "flag"  # the orientation-FLAG path
    assert r["D-OVERRIDE-TIGHT"]["verdict"] == "flag"
    assert r["D-OVERRIDE-LOOSE"]["verdict"] == "pass"


def test_f04_coverage_confidences(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f04_coverage_orientation_verdict_report.json"))
    assert r["D-INVIEW-ABSENT"]["verdict"] == "absent"
    assert r["D-INVIEW-ABSENT"]["confidence"] == 0.7  # literal const in verdict.py (safe ==)
    assert r["D-GAP-ABSENT"]["verdict"] == "absent"
    assert r["D-GAP-ABSENT"]["confidence"] == 0.25  # literal const in verdict.py (safe ==)
    assert r["D-ORIENT-FLAG"]["verdict"] == "flag"
    assert r["D-DOWN-PASS"]["verdict"] == "pass"  # up_axis=down is a no-op on the verdict


def test_f04_manifest_up_axis_roundtrips(fixtures_dir):
    m = ingest.load_manifest(fixtures_dir / "synthetic" / "f04_coverage_orientation.manifest.json")
    d = next(x for x in m.devices if x.id == "D-DOWN-PASS")
    assert d.orientation.up_axis == "down"


def test_f05_distinctions(fixtures_dir):
    r = _by_id(_golden(fixtures_dir, "f05_distinctions_verdict_report.json"))
    assert r["D-TYPE"]["verdict"] == "type_mismatch"
    assert r["D-TYPE-LOWCONF"]["verdict"] == "pass"  # confidence gate holds
    assert r["D-ABSENT"]["verdict"] == "absent"
    assert r["D-FLAG"]["verdict"] == "flag"
    assert r["D-PASS"]["verdict"] == "pass"


def test_f06_wall_all_pass_and_decoy(fixtures_dir):
    g = _golden(fixtures_dir, "f06_device_wall_verdict_report.json")
    assert all(r["verdict"] == "pass" for r in g["device_results"])
    assert g["summary"]["total"] == 12
    assert _by_id(g)["D-W05"]["verdict"] == "pass"  # agreeing obs beat the wrong-type decoy


def test_f07_empty(fixtures_dir):
    g = _golden(fixtures_dir, "f07_empty_manifest_verdict_report.json")
    assert g["device_results"] == []
    assert g["summary"] == {"total": 0, "pass": 0, "flag": 0, "absent": 0, "type_mismatch": 0}


def test_generated_at_single_source():
    from fixtures.seeders import _common, regen_goldens  # regen imports _common.GENERATED_AT

    # both must reference the same value; this fails if someone re-hardcodes a literal
    assert _common.GENERATED_AT == "2026-06-28T00:00:00Z"
    assert regen_goldens.c.GENERATED_AT == _common.GENERATED_AT
