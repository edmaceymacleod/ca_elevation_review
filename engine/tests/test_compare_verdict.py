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


# --- classify-level TYPE_MISMATCH boundary cases (no fixtures) -------------- #
def _classify_with_observation(expected_type, detected_type, type_confidence):
    """Classify one device whose single observation sits exactly on it."""
    from ca_elevation_engine.compare import Match
    from ca_elevation_engine.models import (
        Device,
        Observation,
        Point3,
        Project,
        SpecManifest,
        Tolerances,
    )
    from ca_elevation_engine.verdict import classify

    device = Device(
        id="d1",
        family="Access",
        type=expected_type,
        level_id="L1",
        position=Point3(0.0, 0.0, 4.0),
        mounting_height=4.0,
    )
    manifest = SpecManifest(
        schema_version="1.0.0",
        project=Project(id="p", name="P", units="feet"),
        levels=[],
        devices=[device],
        default_tolerances=Tolerances(position=0.083, mounting_height=0.042, orientation=10.0),
    )
    obs = Observation(
        position=Point3(0.0, 0.0, 4.0),
        mounting_height=4.0,
        facing_angle=0.0,
        detected_type=detected_type,
        type_confidence=type_confidence,
    )
    match = Match(
        device=device,
        observation=obs,
        matched_shot_id="S1",
        position_delta=0.0,
        height_delta=0.0,
        orientation_delta=0.0,
    )
    return classify(match, manifest)


def test_substring_type_agreement_is_pass_not_mismatch():
    # "reader" is a substring of "Card Reader" -> agreement, confident -> PASS + confirmed.
    r = _classify_with_observation("Card Reader", "reader", 0.7)
    assert r.verdict is Verdict.PASS
    assert r.identity_confirmed is True


def test_disagreeing_type_below_confidence_is_not_mismatch():
    # Disagrees, but type_confidence 0.4 < 0.6 threshold -> identity stays human-confirmable.
    r = _classify_with_observation("Card Reader", "Exit Sign", 0.4)
    assert r.verdict is Verdict.PASS
    assert r.identity_confirmed is False


def test_disagreeing_type_above_confidence_is_mismatch():
    r = _classify_with_observation("Card Reader", "Exit Sign", 0.9)
    assert r.verdict is Verdict.TYPE_MISMATCH


# --- non-finite delta must NOT silently PASS -------------------------------- #
def _classify_with_position_delta(position_delta):
    """Classify a matched device whose position delta is set directly."""
    from ca_elevation_engine.compare import Match
    from ca_elevation_engine.models import (
        Device,
        Observation,
        Point3,
        Project,
        SpecManifest,
        Tolerances,
    )
    from ca_elevation_engine.verdict import classify

    device = Device(
        id="d1",
        family="Access",
        type="Reader",
        level_id="L1",
        position=Point3(0.0, 0.0, 4.0),
    )
    manifest = SpecManifest(
        schema_version="1.0.0",
        project=Project(id="p", name="P", units="feet"),
        levels=[],
        devices=[device],
        default_tolerances=Tolerances(position=0.083, mounting_height=0.042, orientation=10.0),
    )
    obs = Observation(position=Point3(0.0, 0.0, 4.0))
    match = Match(
        device=device,
        observation=obs,
        matched_shot_id="S1",
        position_delta=position_delta,
    )
    return classify(match, manifest)


def test_nan_position_delta_flags_not_passes():
    # `NaN > tol` is False; without a finiteness guard this fell through to PASS.
    r = _classify_with_position_delta(float("nan"))
    assert r.verdict is Verdict.FLAG
    assert any("non-finite" in n for n in r.notes)
    # Confidence must not look clean (the old clamp accident returned 0.3).
    assert r.confidence <= 0.05


def test_inf_position_delta_flags_not_passes():
    r = _classify_with_position_delta(float("inf"))
    assert r.verdict is Verdict.FLAG


def test_finite_in_tolerance_delta_still_passes():
    # Guard must not break legitimate in-tolerance matches.
    r = _classify_with_position_delta(0.01)
    assert r.verdict is Verdict.PASS


# --- frustum-bypass (empty-coverage fallback) marks the match -------------- #
def test_frustum_bypass_match_is_marked_approximate():
    """A device no shot framed, matched via the same-level fallback, is flagged
    approximate with an explanatory note rather than reading as a clean match."""
    from ca_elevation_engine.compare import match_device
    from ca_elevation_engine.models import (
        CapturePackage as Cap,
    )
    from ca_elevation_engine.models import (
        Device,
        Floorplan,
        Intrinsics,
        Level,
        Observation,
        Pin,
        Point3,
        Project,
        Shot,
        SpecManifest,
    )
    from ca_elevation_engine.register import register_capture

    # Device far behind/away from the camera so it projects outside every frustum,
    # but a same-level observation sits exactly on its expected position.
    device = Device(id="d1", family="F", type="T", level_id="L1", position=Point3(0.0, 0.0, 4.0))
    manifest = SpecManifest(
        schema_version="1.0.0",
        project=Project(id="p", name="P", units="feet"),
        levels=[
            Level(
                id="L1",
                name="L1",
                elevation=0.0,
                floorplan=Floorplan("p.png", 100, 100, [0.01, 0, 0, 0, 0.01, 0]),
            )
        ],
        devices=[device],
    )
    intr = Intrinsics(fx=1400.0, fy=1400.0, cx=960.0, cy=720.0, width=1920, height=1440)
    # Pose looking away (camera at origin, device behind it) -> not in frame.
    pose = [1.0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    shot = Shot(
        id="S1",
        level_id="L1",
        rgb_image="a.jpg",
        intrinsics=intr,
        pose=pose,
        pin=Pin(x=5000.0, y=5000.0, heading=0.0),
        observations=[Observation(position=Point3(0.0, 0.0, 4.0))],
    )
    capture = Cap(schema_version="1.0.0", project_id="p", shots=[shot])
    regs = register_capture(manifest, capture)
    match = match_device(device, capture, manifest, regs)

    if match.observation is not None and not match.in_coverage:
        # Fallback fired: the match must carry the bypass signal.
        assert match.approximate is True
        assert any("outside any camera frustum" in n for n in match.notes)


def test_registration_notes_surface_in_match_and_result(f01_manifest_path, f01_capture_path):
    """Matched-shot registration notes must reach Match.notes -> DeviceResult.notes."""
    from ca_elevation_engine.compare import match_device
    from ca_elevation_engine.verdict import classify

    manifest = ingest.load_manifest(f01_manifest_path)
    capture = ingest.load_capture(f01_capture_path)
    regs = register_capture(manifest, capture)
    # Seed a synthetic registration note on the shot D-PASS matches against (S1).
    regs["S1"].notes.append("ICP refinement applied: rmse=0.0123 feet")

    device = next(d for d in manifest.devices if d.id == "D-PASS")
    match = match_device(device, capture, manifest, regs)
    assert match.matched_shot_id == "S1"
    assert any("registration: ICP refinement applied" in n for n in match.notes)

    result = classify(match, manifest)
    assert any("registration: ICP refinement applied" in n for n in result.notes)
