"""Compare + verdict: device matching, deltas, and classification."""

from __future__ import annotations

import pytest

from ca_elevation_engine import ingest
from ca_elevation_engine.compare import match_all
from ca_elevation_engine.models import Verdict
from ca_elevation_engine.register import register_capture
from ca_elevation_engine.verdict import classify_all

pytestmark = pytest.mark.unit


@pytest.fixture
def results(f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    regs = register_capture(manifest, capture)
    matches = match_all(manifest, capture, regs)
    return {r.device_id: r for r in classify_all(matches, manifest)}


def test_pass_device(results):
    r = results["D-PASS"]
    assert r.verdict is Verdict.PASS
    assert r.deltas.position == pytest.approx(0.02236, abs=1e-4)
    assert r.matched_shot_id == "S1"
    assert r.confidence > 0.8


def test_flag_device_out_of_position_tolerance(results):
    r = results["D-FLAG"]
    assert r.verdict is Verdict.FLAG
    assert r.deltas.position == pytest.approx(0.3, abs=1e-6)
    assert any("position" in n for n in r.notes)


def test_absent_in_coverage_is_higher_confidence(results):
    r = results["D-ABSENT"]
    assert r.verdict is Verdict.ABSENT
    assert r.matched_shot_id is None
    assert r.confidence == pytest.approx(0.7)


def test_type_mismatch(results):
    r = results["D-TYPE"]
    assert r.verdict is Verdict.TYPE_MISMATCH
    assert r.confidence == pytest.approx(0.9)
    assert any("disagrees" in n for n in r.notes)


def test_coverage_gap_low_confidence_absent(results):
    r = results["D-GAP"]
    assert r.verdict is Verdict.ABSENT
    assert r.confidence == pytest.approx(0.25)
    assert any("coverage gap" in n for n in r.notes)


def test_every_verdict_class_present(results):
    seen = {r.verdict for r in results.values()}
    assert seen == {Verdict.PASS, Verdict.FLAG, Verdict.ABSENT, Verdict.TYPE_MISMATCH}


def test_height_delta_within_tolerance_does_not_flag(results):
    # D-PASS height delta is 0.01 (< 0.042 tol); must not contribute a breach.
    r = results["D-PASS"]
    assert r.deltas.mounting_height == pytest.approx(0.01, abs=1e-6)


def test_type_agreement_marks_identity_confirmed(results):
    # D-PASS observation detected_type "HID-R10" agrees w/ expected type at 0.82.
    assert results["D-PASS"].identity_confirmed is True


def test_no_observations_all_absent(f01_manifest_path, f01_capture_path):
    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    for shot in capture.shots:
        shot.observations = []
    regs = register_capture(manifest, capture)
    results = classify_all(match_all(manifest, capture, regs), manifest)
    assert all(r.verdict is Verdict.ABSENT for r in results)
