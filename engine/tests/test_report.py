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
    _ordering,
    render_html,
    render_json,
    render_report,
    summarize,
)
from ca_elevation_engine.report import html as html_mod
from ca_elevation_engine.report import pdf as pdf_mod
from ca_elevation_engine.report._ordering import (
    coverage,
    grouped_results,
    ordered_results,
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
def test_render_json_rejects_non_finite():
    # A non-finite delta must raise rather than emit bare NaN/Infinity tokens,
    # which are invalid JSON and would break a standards-compliant consumer.
    report = _report()
    report.device_results[0].deltas.position = float("nan")
    with pytest.raises(ValueError):
        render_json(report)

    report = _report()
    report.device_results[0].confidence = float("inf")
    with pytest.raises(ValueError):
        render_json(report)


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


def _all_matched_report() -> VerdictReport:
    """A report where every device has a matched_shot_id (no coverage gap)."""
    rep = _report()
    for r in rep.device_results:
        r.matched_shot_id = "SHOT-A"
    return rep


def _empty_report() -> VerdictReport:
    return VerdictReport(
        schema_version="1.0.0",
        project_id="proj-42",
        device_results=[],
        units="feet",
        generated_at="2026-06-28T12:00:00Z",
        engine_version="0.1.0",
    )


# --------------------------------------------------------------------------- #
# _ordering helper (§6.1)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_ordered_results_problems_first():
    ids = [r.device_id for r in ordered_results(_report())]
    assert ids == ["DEV-002", "DEV-003", "DEV-004", "DEV-001"]


@pytest.mark.unit
def test_grouped_results_buckets_and_omits_empty():
    rep = VerdictReport(
        schema_version="1.0.0",
        project_id="p",
        device_results=[
            DeviceResult(device_id="B", verdict=Verdict.PASS, confidence=1.0),
            DeviceResult(device_id="A", verdict=Verdict.PASS, confidence=1.0),
            DeviceResult(device_id="C", verdict=Verdict.FLAG, confidence=0.5),
        ],
    )
    groups = grouped_results(rep)
    assert [v for v, _ in groups] == [Verdict.FLAG, Verdict.PASS]
    flag_ids = [r.device_id for r in groups[0][1]]
    pass_ids = [r.device_id for r in groups[1][1]]
    assert flag_ids == ["C"]
    assert pass_ids == ["A", "B"]  # sorted by id within group


@pytest.mark.unit
def test_coverage_counts_unmatched():
    cov = coverage(_report())
    assert cov.total == 4
    assert cov.matched == 3
    assert cov.unmatched == 1
    assert cov.unmatched_ids == ["DEV-003"]


@pytest.mark.unit
def test_coverage_empty_report():
    cov = coverage(_empty_report())
    assert cov.total == 0
    assert cov.matched == 0
    assert cov.unmatched == 0
    assert cov.unmatched_ids == []


# --------------------------------------------------------------------------- #
# HTML grouped + coverage (§6.2)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_html_groups_by_status():
    html = render_html(_report(), _manifest(), _capture())
    assert 'class="group flag"' in html
    assert 'class="group absent"' in html
    assert 'class="group type_mismatch"' in html
    assert 'class="group pass"' in html
    assert html.index('class="group flag"') < html.index('class="group pass"')


@pytest.mark.unit
def test_html_coverage_line():
    html = render_html(_report(), _manifest(), _capture())
    assert "3 / 4 matched" in html


_GAP_SECTION = '<section class="coverage-gap">'


@pytest.mark.unit
def test_html_coverage_gap_callout():
    html = render_html(_report(), _manifest(), _capture())
    assert _GAP_SECTION in html
    assert "DEV-003" in html
    assert "rest on absence, not measurement" in html
    # The callout lists only DEV-003; DEV-002 is matched and must not appear in it.
    callout = html[html.index(_GAP_SECTION) :]
    callout = callout[: callout.index("</section>")]
    assert "DEV-003" in callout
    assert "DEV-002" not in callout


@pytest.mark.unit
def test_html_no_coverage_gap_when_all_matched():
    # The CSS class name lives in the static <style>; assert the *section* is absent.
    html = render_html(_all_matched_report(), _manifest(), _capture())
    assert _GAP_SECTION not in html


@pytest.mark.unit
def test_html_empty_report_valid():
    html = render_html(_empty_report(), _manifest(), _capture())
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "No devices" in html
    assert _GAP_SECTION not in html


@pytest.mark.unit
def test_html_escapes_xss_in_grouped_markup():
    html = render_html(_report(), _manifest(), _capture())
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# --------------------------------------------------------------------------- #
# JSON / text contract (§6.3)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_text_uses_shared_ordering():
    report = _report()
    text = summarize(report)
    expected = [
        r.device_id for r in ordered_results(report) if r.verdict in _ordering.PROBLEM_VERDICTS
    ]
    positions = [text.index(did) for did in expected]
    assert positions == sorted(positions)


# --------------------------------------------------------------------------- #
# Determinism (HTML) (§6.4)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_html_deterministic():
    a = render_html(_report(), _manifest(), _capture())
    b = render_html(_report(), _manifest(), _capture())
    assert a == b


# --------------------------------------------------------------------------- #
# Graceful degradation (§6.6) -- runs even though reportlab IS installed
# --------------------------------------------------------------------------- #
def _raise_missing_backend():
    from ca_elevation_engine.report.pdf import MissingPdfBackend

    raise MissingPdfBackend("simulated absence")


@pytest.mark.unit
def test_render_pdf_missing_backend_raises(tmp_path, monkeypatch):
    from ca_elevation_engine.report.pdf import MissingPdfBackend

    monkeypatch.setattr(pdf_mod, "_require_reportlab", _raise_missing_backend)
    with pytest.raises(MissingPdfBackend):
        pdf_mod.render_pdf(_report(), _manifest(), _capture(), str(tmp_path / "x.pdf"))


@pytest.mark.unit
def test_pipeline_falls_back_to_html_without_reportlab(tmp_path, monkeypatch):
    from ca_elevation_engine.pipeline import run_pipeline

    monkeypatch.setattr(pdf_mod, "_require_reportlab", _raise_missing_backend)
    result = run_pipeline(
        _manifest(),
        _capture(),
        out_dir=str(tmp_path),
        report_format="pdf",
        generated_at="2026-06-28T12:00:00Z",
    )
    assert "html" in result.written
    html_path = result.written["html"]
    from pathlib import Path

    assert Path(html_path).exists()
    assert Path(html_path).read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")
    assert any("Falling back to HTML" in w for w in result.warnings)


@pytest.mark.unit
def test_pipeline_real_html_fallback_when_reportlab_absent(tmp_path):
    # Genuine-absence companion to the monkeypatched test above. With reportlab
    # ACTUALLY uninstalled, the real `import reportlab` failure inside
    # report.pdf._require_reportlab is exercised end-to-end -- not simulated via
    # monkeypatch. Skipped where reportlab is present; this is the test the
    # `engine_no_report` CI leg exists to run (engine installed without [report]).
    import importlib.util

    if importlib.util.find_spec("reportlab") is not None:
        pytest.skip(
            "reportlab present; genuine-absence fallback runs in the engine_no_report CI leg"
        )

    from ca_elevation_engine.pipeline import run_pipeline

    result = run_pipeline(
        _manifest(),
        _capture(),
        out_dir=str(tmp_path),
        report_format="pdf",
        generated_at="2026-06-28T12:00:00Z",
    )
    # Asked for pdf, got html -- the real fallback fired, with no pdf produced.
    assert "html" in result.written
    assert "pdf" not in result.written
    from pathlib import Path

    html_path = result.written["html"]
    assert Path(html_path).exists()
    assert Path(html_path).read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")
    assert any("Falling back to HTML" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
# Anti-drift guard (ranking only) (§6.7)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_renderers_share_ranking():
    assert _ordering.VERDICT_DISPLAY_ORDER == (
        Verdict.FLAG,
        Verdict.ABSENT,
        Verdict.TYPE_MISMATCH,
        Verdict.PASS,
    )
    assert not hasattr(pdf_mod, "_VERDICT_ORDER")
    assert not hasattr(html_mod, "_VERDICT_SORT_RANK")
