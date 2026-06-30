"""Round-trip and behaviour tests for the data models."""

from __future__ import annotations

import pytest

from ca_elevation_engine.models import (
    DEFAULT_TOLERANCES,
    CapturePackage,
    Device,
    SpecManifest,
    Tolerances,
    Verdict,
    VerdictReport,
)

pytestmark = pytest.mark.unit


def test_manifest_roundtrip(f01_manifest_path):
    import json

    data = json.loads(f01_manifest_path.read_text())
    m = SpecManifest.from_dict(data)
    assert m.project.id == "demo-office-01"
    assert len(m.devices) == 5
    # Round-trip preserves structure.
    again = SpecManifest.from_dict(m.to_dict())
    assert again.to_dict() == m.to_dict()


def test_capture_roundtrip(f01_capture_path):
    import json

    data = json.loads(f01_capture_path.read_text())
    c = CapturePackage.from_dict(data)
    assert c.project_id == "demo-office-01"
    assert len(c.shots) == 1
    assert len(c.shots[0].observations) == 3
    assert CapturePackage.from_dict(c.to_dict()).to_dict() == c.to_dict()


def test_tolerances_merge():
    base = Tolerances(position=0.1)
    fallback = Tolerances(position=0.2, mounting_height=0.05, orientation=8)
    merged = base.merged_with(fallback)
    assert merged.position == 0.1  # own value wins
    assert merged.mounting_height == 0.05  # filled from fallback
    assert merged.orientation == 8


def test_effective_tolerances_uses_defaults():
    dev = Device(id="d", family="f", type="t", level_id="L1", position=_p())
    m = SpecManifest(
        schema_version="1.0.0",
        project=_proj(),
        levels=[],
        devices=[dev],
        default_tolerances=Tolerances(),
    )
    tol = m.effective_tolerances(dev)
    # Falls all the way back to module DEFAULT_TOLERANCES.
    assert tol.position == DEFAULT_TOLERANCES.position
    assert tol.orientation == DEFAULT_TOLERANCES.orientation


def test_verdict_report_summary_counts():
    from ca_elevation_engine.models import DeviceResult

    results = [
        DeviceResult("a", Verdict.PASS, 0.9),
        DeviceResult("b", Verdict.FLAG, 0.5),
        DeviceResult("c", Verdict.ABSENT, 0.7),
        DeviceResult("d", Verdict.ABSENT, 0.3),
    ]
    rep = VerdictReport("1.0.0", "p", results)
    s = rep.summary
    assert s == {"total": 4, "pass": 1, "flag": 1, "absent": 2, "type_mismatch": 0}
    assert VerdictReport.from_dict(rep.to_dict()).summary == s


def _p():
    from ca_elevation_engine.models import Point3

    return Point3(0, 0, 0)


def _proj():
    from ca_elevation_engine.models import Project

    return Project(id="p", name="n", units="feet")


def test_observation_empty_detected_type_roundtrips():
    # "" is a meaningful state (detection attempted but failed); it must survive
    # serialization, distinct from an absent (None) detected_type.
    from ca_elevation_engine.models import Observation, Point3

    o = Observation(position=Point3(0.0, 0.0, 0.0), detected_type="")
    d = o.to_dict()
    assert d["detected_type"] == ""
    assert Observation.from_dict(d).detected_type == ""

    absent = Observation(position=Point3(0.0, 0.0, 0.0))
    assert "detected_type" not in absent.to_dict()
    assert Observation.from_dict(absent.to_dict()).detected_type is None
