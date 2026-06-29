"""Tests for the PDF report renderer (the primary deliverable)."""

from __future__ import annotations

import pytest

from ca_elevation_engine import ingest
from ca_elevation_engine.pipeline import run_pipeline

pytestmark = pytest.mark.unit

reportlab = pytest.importorskip("reportlab")


def _report(f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    result = run_pipeline(manifest, capture, generated_at="2026-06-28T00:00:00Z")
    return result.report, manifest, capture


def test_render_pdf_produces_valid_pdf(tmp_path, f01_manifest_path, f01_capture_path):
    from ca_elevation_engine.report import render_report

    report, manifest, capture = _report(f01_manifest_path, f01_capture_path)
    out = tmp_path / "r.pdf"
    render_report(report, manifest, capture, str(out), fmt="pdf")
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1500  # non-trivial document
    assert b"%%EOF" in data[-1024:]


def test_render_pdf_via_helper(tmp_path, f01_manifest_path, f01_capture_path):
    from ca_elevation_engine.report import render_pdf

    report, manifest, capture = _report(f01_manifest_path, f01_capture_path)
    out = tmp_path / "r2.pdf"
    path = render_pdf(report, manifest, capture, str(out))
    assert path == str(out)
    assert out.exists()


def test_pdf_in_supported_formats():
    from ca_elevation_engine.report import SUPPORTED_FORMATS

    assert "pdf" in SUPPORTED_FORMATS


def test_pdf_escapes_malicious_notes(tmp_path, f01_manifest_path, f01_capture_path):
    """A note containing markup must not break ReportLab paragraph parsing."""
    from ca_elevation_engine.report import render_pdf

    report, manifest, capture = _report(f01_manifest_path, f01_capture_path)
    report.device_results[0].notes.append("<b>x</b> & <script>bad</script>")
    out = tmp_path / "r3.pdf"
    # Must not raise.
    render_pdf(report, manifest, capture, str(out))
    assert out.read_bytes().startswith(b"%PDF")
