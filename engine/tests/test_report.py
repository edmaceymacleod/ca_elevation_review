"""Headless unit tests for the report renderer sub-package.

These build small in-memory :class:`VerdictReport` / :class:`SpecManifest` /
:class:`CapturePackage` objects from the real dataclasses and exercise the HTML,
JSON, and plaintext renderers. No heavy deps, no Revit, no device -- everything
runs against ``tmp_path``.
"""

from __future__ import annotations

import json

import pytest

from ca_elevation_engine.models import (
    CapturePackage,
    Deltas,
    Device,
    DeviceResult,
    Floorplan,
    Intrinsics,
    Level,
    Orientation,
    Pin,
    Point3,
    Project,
    Shot,
    SpecManifest,
    Verdict,
    VerdictReport,
)
from ca_elevation_engine.report import (
    render_html,
    render_json,
    render_report,
    summarize,
)

# A note containing markup we expect to be escaped in HTML output.
XSS_NOTE = "<script>alert('x')</script> & check <b>wall</b>"


def _manifest() -> SpecManifest:
    fp = Floorplan(
        image="L1.png",
        width_px=2000,
        height_px=1500,
        pixel_to_model=[0.01, 0.0, 0.0, 0.0, -0.01, 15.0],
    )
    level = Level(id="L1", name="Level 1", elevation=0.0, floorplan=fp)
    devices = [
        Device(
            id="DEV-001",
            family="Card Reader",
            type="HID Signo 20",
            level_id="L1",
            position=Point3(10.0, 4.0, 3.5),
            mounting_height=3.5,
        ),
        Device(
            id="DEV-002",
            family="Camera",
            type="Dome 4MP",
            level_id="L1",
            position=Point3(20.0, 4.0, 9.0),
            mounting_height=9.0,
            orientation=Orientation(facing_angle=90.0),
        ),
        Device(
            id="DEV-003",
            family="Speaker",
            type="Ceiling 6in",
            level_id="L1",
            position=Point3(30.0, 4.0, 9.5),
        ),
        Device(
            id="DEV-004",
            family="Panel",
            type="Access Control",
            level_id="L1",
            position=Point3(2.0, 4.0, 4.0),
        ),
    ]
    return SpecManifest(
        schema_version="1.0.0",
        project=Project(id="proj-42", name="Acme HQ Lobby", units="feet"),
        levels=[level],
        devices=devices,
    )


def _capture() -> CapturePackage:
    intr = Intrinsics(fx=1400.0, fy=1400.0, cx=960.0, cy=720.0, width=1920, height=1440)
    pose = [1.0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    pin = Pin(x=500.0, y=600.0, heading=90.0)
    shot = Shot(
        id="SHOT-A",
        level_id="L1",
        rgb_image="a.jpg",
        intrinsics=intr,
        pose=pose,
        pin=pin,
    )
    return CapturePackage(
        schema_version="1.0.0",
        project_id="proj-42",
        shots=[shot],
    )


def _report() -> VerdictReport:
    results = [
        DeviceResult(
            device_id="DEV-001",
            verdict=Verdict.PASS,
            confidence=0.97,
            family="Card Reader",
            type="HID Signo 20",
            matched_shot_id="SHOT-A",
            identity_confirmed=True,
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
            notes=["Position delta exceeds tolerance", XSS_NOTE],
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


@pytest.mark.unit
def test_render_html_to_file(tmp_path):
    report, manifest, capture = _report(), _manifest(), _capture()
    out = tmp_path / "report.html"
    written = render_report(report, manifest, capture, str(out), fmt="html")

    assert written == str(out)
    assert out.exists()
    html = out.read_text(encoding="utf-8")

    assert len(html) > 500
    assert html.lstrip().startswith("<!DOCTYPE html>")

    # Header / metadata present.
    assert "Acme HQ Lobby" in html
    assert "2026-06-28T12:00:00Z" in html
    assert "0.1.0" in html

    # Every device id is rendered.
    for did in ("DEV-001", "DEV-002", "DEV-003", "DEV-004"):
        assert did in html

    # Verdict words appear.
    assert "PASS" in html
    assert "FLAG" in html
    assert "ABSENT" in html
    assert "TYPE MISMATCH" in html or "TYPE_MISMATCH" in html

    # Summary counts (3 problems + 1 pass).
    assert ">4<" in html  # total chip
    assert "Type mismatch" in html

    # Scope/honesty footer.
    assert "Scope" in html
    assert "sub-inch" in html


@pytest.mark.unit
def test_html_escapes_dynamic_text(tmp_path):
    report, manifest, capture = _report(), _manifest(), _capture()
    out = tmp_path / "report.html"
    render_report(report, manifest, capture, str(out), fmt="html")
    html = out.read_text(encoding="utf-8")

    # The raw script tag must never appear unescaped.
    assert "<script>alert('x')</script>" not in html
    # It should be present in escaped form.
    assert "&lt;script&gt;" in html


@pytest.mark.unit
def test_html_orders_problems_first(tmp_path):
    report, manifest, capture = _report(), _manifest(), _capture()
    out = tmp_path / "report.html"
    render_report(report, manifest, capture, str(out), fmt="html")
    html = out.read_text(encoding="utf-8")

    # DEV-002 (flag) must appear before DEV-001 (pass) in the row order.
    assert html.index("DEV-002") < html.index("DEV-001")
    assert html.index("DEV-003") < html.index("DEV-001")


@pytest.mark.unit
def test_render_json_round_trip(tmp_path):
    report, manifest, capture = _report(), _manifest(), _capture()
    out = tmp_path / "report.json"
    written = render_report(report, manifest, capture, str(out), fmt="json")

    assert written == str(out)
    text = out.read_text(encoding="utf-8")

    parsed = json.loads(text)
    assert parsed == report.to_dict()

    # Round-trips back through the dataclass.
    rebuilt = VerdictReport.from_dict(parsed)
    assert rebuilt.project_id == report.project_id
    assert rebuilt.summary == report.summary
    assert len(rebuilt.device_results) == len(report.device_results)
    assert rebuilt.device_results[0].verdict is Verdict.PASS

    # render_json helper matches the file content.
    assert render_json(report) == text


@pytest.mark.unit
def test_summarize_text(tmp_path):
    report = _report()
    text = summarize(report)

    assert "PASS 1" in text
    assert "FLAG 1" in text
    assert "ABSENT 1" in text
    assert "TYPE_MISMATCH 1" in text
    assert "(4 devices)" in text

    # Non-pass devices are listed; passing one is not.
    assert "DEV-002" in text
    assert "DEV-003" in text
    assert "DEV-004" in text
    assert "DEV-001" not in text

    # Problems surface before pass; flag listed first by severity rank.
    assert text.index("DEV-002") < text.index("DEV-003")


@pytest.mark.unit
def test_render_html_helper_nonempty():
    report, manifest, capture = _report(), _manifest(), _capture()
    html = render_html(report, manifest, capture)
    assert isinstance(html, str) and len(html) > 500


@pytest.mark.unit
def test_summarize_all_pass():
    report = VerdictReport(
        schema_version="1.0.0",
        project_id="p",
        device_results=[
            DeviceResult(device_id="D1", verdict=Verdict.PASS, confidence=1.0),
        ],
    )
    text = summarize(report)
    assert "PASS 1" in text
    assert "All devices pass." in text


@pytest.mark.unit
def test_unsupported_format_raises(tmp_path):
    report, manifest, capture = _report(), _manifest(), _capture()
    with pytest.raises(ValueError):
        render_report(report, manifest, capture, str(tmp_path / "x.docx"), fmt="docx")
