"""Integration: run the engine over the seeded fixture and diff against golden.

This is the determinism guard. Re-running the pipeline on the immutable F-01
fixture must reproduce ``fixtures/golden/f01_verdict_report.json`` byte-for-byte
at the dict level. If the engine's behaviour changes intentionally, regenerate
the golden via the seeder + a deliberate update -- never let the test write it.
"""

from __future__ import annotations

import pytest

from ca_elevation_engine import ingest
from ca_elevation_engine.pipeline import run_pipeline

pytestmark = pytest.mark.integration

GENERATED_AT = "2026-06-28T00:00:00Z"


def test_pipeline_reproduces_golden(f01_manifest_path, f01_capture_path, f01_golden):
    result = run_pipeline(f01_manifest_path, f01_capture_path, generated_at=GENERATED_AT)
    produced = result.report.to_dict()
    # engine_version is environment-derived; compare everything else exactly.
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
