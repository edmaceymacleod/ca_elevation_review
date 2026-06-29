"""Tests for the PDF report renderer (the primary deliverable)."""

from __future__ import annotations

import contextlib

import pytest

from ca_elevation_engine import ingest
from ca_elevation_engine.models import (
    Deltas,
    DeviceResult,
    Verdict,
    VerdictReport,
)
from ca_elevation_engine.pipeline import run_pipeline

pytestmark = pytest.mark.unit

reportlab = pytest.importorskip("reportlab")


@contextlib.contextmanager
def _no_compression():
    """Disable ReportLab stream compression in the test body only.

    With compression off, device ids and labels appear literally in the PDF
    bytes so we can assert content. The prior value is restored in a finally
    (test-local toggle; the renderer never touches rl_config -- see spec §4.5).
    """
    from reportlab import rl_config

    prev = rl_config.pageCompression
    rl_config.pageCompression = 0
    try:
        yield
    finally:
        rl_config.pageCompression = prev


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


# --------------------------------------------------------------------------- #
# Grouped + coverage content probes (§6.5). Compression is disabled in the test
# body so device ids and labels appear literally in the PDF bytes.
# --------------------------------------------------------------------------- #
def _grouped_report() -> VerdictReport:
    """All four verdicts present; DEV-003 is the only coverage gap."""
    results = [
        DeviceResult(
            device_id="DEV-001",
            verdict=Verdict.PASS,
            confidence=0.97,
            family="Card Reader",
            type="HID Signo 20",
            matched_shot_id="SHOT-A",
            deltas=Deltas(position=0.02, mounting_height=0.01, orientation=1.2),
        ),
        DeviceResult(
            device_id="DEV-002",
            verdict=Verdict.FLAG,
            confidence=0.71,
            family="Camera",
            type="Dome 4MP",
            matched_shot_id="SHOT-A",
            deltas=Deltas(position=0.31, mounting_height=0.22, orientation=14.0),
            approximate=True,
            notes=["Position delta exceeds tolerance"],
        ),
        DeviceResult(
            device_id="DEV-003",
            verdict=Verdict.ABSENT,
            confidence=0.40,
            family="Speaker",
            type="Ceiling 6in",
            matched_shot_id=None,
            deltas=Deltas(),
            notes=["Not observed in any shot"],
        ),
        DeviceResult(
            device_id="DEV-004",
            verdict=Verdict.TYPE_MISMATCH,
            confidence=0.66,
            family="Panel",
            type="Access Control",
            matched_shot_id="SHOT-A",
            deltas=Deltas(position=0.05),
            notes=["Detected type differs from spec"],
        ),
    ]
    return VerdictReport(
        schema_version="1.0.0",
        project_id="proj-42",
        device_results=results,
        units="feet",
        generated_at="2026-06-28T12:00:00Z",
        engine_version="0.1.0",
    )


def _stub_manifest_capture():
    """Minimal manifest/capture sufficient for the PDF renderer."""
    from ca_elevation_engine.models import (
        CapturePackage,
        Floorplan,
        Intrinsics,
        Level,
        Pin,
        Point3,
        Project,
        Shot,
        SpecManifest,
    )

    fp = Floorplan(
        image="L1.png",
        width_px=2000,
        height_px=1500,
        pixel_to_model=[0.01, 0.0, 0.0, 0.0, -0.01, 15.0],
    )
    level = Level(id="L1", name="Level 1", elevation=0.0, floorplan=fp)
    from ca_elevation_engine.models import Device

    devices = [
        Device(
            id="DEV-009",
            family="Manifest Family",
            type="Manifest Type",
            level_id="L1",
            position=Point3(1.0, 2.0, 3.0),
        ),
    ]
    manifest = SpecManifest(
        schema_version="1.0.0",
        project=Project(id="proj-42", name="Acme HQ Lobby", units="feet"),
        levels=[level],
        devices=devices,
    )
    intr = Intrinsics(fx=1400.0, fy=1400.0, cx=960.0, cy=720.0, width=1920, height=1440)
    pose = [1.0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    shot = Shot(
        id="SHOT-A",
        level_id="L1",
        rgb_image="a.jpg",
        intrinsics=intr,
        pose=pose,
        pin=Pin(x=500.0, y=600.0, heading=90.0),
    )
    capture = CapturePackage(schema_version="1.0.0", project_id="proj-42", shots=[shot])
    return manifest, capture


def test_pdf_groups_and_coverage(tmp_path):
    from ca_elevation_engine.report import render_pdf

    report = _grouped_report()
    manifest, capture = _stub_manifest_capture()
    out = tmp_path / "grouped.pdf"
    with _no_compression():
        render_pdf(report, manifest, capture, str(out))
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    for label in (b"FLAG", b"ABSENT", b"TYPE", b"PASS"):
        assert label in data
    assert b"Coverage" in data
    assert b"DEV-003" in data  # the unmatched id appears in the callout


def test_pdf_backfills_family_type_from_manifest(tmp_path):
    from ca_elevation_engine.report import render_pdf

    report = VerdictReport(
        schema_version="1.0.0",
        project_id="proj-42",
        device_results=[
            DeviceResult(
                device_id="DEV-009",
                verdict=Verdict.PASS,
                confidence=0.9,
                family=None,
                type=None,
                matched_shot_id="SHOT-A",
                deltas=Deltas(),
            ),
        ],
        units="feet",
        generated_at="2026-06-28T12:00:00Z",
        engine_version="0.1.0",
    )
    manifest, capture = _stub_manifest_capture()
    out = tmp_path / "backfill.pdf"
    with _no_compression():
        render_pdf(report, manifest, capture, str(out))
    data = out.read_bytes()
    # The manifest family/type words appear (ReportLab may line-break at the "/"
    # separator, so assert on the individual words rather than the joined string).
    assert b"Manifest" in data
    assert b"Family" in data
    assert b"Type" in data


def test_pdf_empty_report(tmp_path):
    from ca_elevation_engine.report import render_pdf

    report = VerdictReport(
        schema_version="1.0.0",
        project_id="proj-42",
        device_results=[],
        units="feet",
        generated_at="2026-06-28T12:00:00Z",
        engine_version="0.1.0",
    )
    manifest, capture = _stub_manifest_capture()
    out = tmp_path / "empty.pdf"
    render_pdf(report, manifest, capture, str(out))  # must not raise
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"%%EOF" in data[-1024:]
