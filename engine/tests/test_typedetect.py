"""Unit tests for the device-type detection heuristic (typedetect)."""

from __future__ import annotations

import pytest

from ca_elevation_engine.models import (
    CapturePackage,
    Device,
    Intrinsics,
    Observation,
    Pin,
    Point3,
    Project,
    Shot,
    SpecManifest,
)
from ca_elevation_engine.typedetect import (
    EXACT_MATCH_CONFIDENCE,
    SUBSTRING_MATCH_CONFIDENCE,
    catalog_from_manifest,
    detect_type,
    enrich_capture_types,
)

pytestmark = pytest.mark.unit

CATALOG = ["Card Reader", "Exit Sign", "HID-R10", "EXIT-LED"]


def test_none_raw_is_absent():
    assert detect_type(None, CATALOG) == (None, None)


def test_blank_raw_is_failed():
    assert detect_type("", CATALOG) == ("", None)
    assert detect_type("   ", CATALOG) == ("", None)


def test_exact_case_insensitive_match_is_high_confidence():
    assert detect_type("exit sign", CATALOG) == ("Exit Sign", EXACT_MATCH_CONFIDENCE)
    assert detect_type("HID-R10", CATALOG) == ("HID-R10", EXACT_MATCH_CONFIDENCE)


def test_substring_match_is_medium_confidence():
    # "exit sign" is a substring of the raw hint; only one catalog entry matches.
    assert detect_type("illuminated exit sign", CATALOG) == (
        "Exit Sign",
        SUBSTRING_MATCH_CONFIDENCE,
    )


def test_substring_match_picks_longest_when_several_match():
    # DISCRIMINATING longest-wins test: both "Card" and "Card Reader" substring-match
    # the raw hint. "Card" sorts first, so without the `len(nl) > best_len` tie-break
    # the wrong (shorter) "Card" would be returned. This fails if the length
    # comparison is dropped or first/last-match is used instead.
    assert detect_type("card reader panel", ["Card", "Card Reader"]) == (
        "Card Reader",
        SUBSTRING_MATCH_CONFIDENCE,
    )


def test_substring_match_reverse_direction_raw_inside_catalog_name():
    # MATCH-DIRECTION test for the `low in nl` arm: a SHORT raw hint ("exit") is a
    # substring of a LONGER catalog name ("Exit Sign"). A regression that drops
    # `or low in nl` would make this return ("", None) and fail.
    assert detect_type("exit", ["Exit Sign"]) == ("Exit Sign", SUBSTRING_MATCH_CONFIDENCE)


def test_heuristic_confidences_can_fire_type_mismatch():
    # Pin the heuristic against the verdict firing threshold so lowering either
    # confidence below TYPE_MISMATCH_MIN_CONFIDENCE fails fast HERE (a unit test)
    # rather than only surfacing later as f08 golden drift.
    from ca_elevation_engine.verdict import TYPE_MISMATCH_MIN_CONFIDENCE

    assert SUBSTRING_MATCH_CONFIDENCE >= TYPE_MISMATCH_MIN_CONFIDENCE
    assert EXACT_MATCH_CONFIDENCE >= TYPE_MISMATCH_MIN_CONFIDENCE


def test_unknown_raw_reconciles_to_failed():
    assert detect_type("smoke detector", CATALOG) == ("", None)


def test_empty_catalog_is_failed():
    assert detect_type("exit sign", []) == ("", None)


def _device(did, family, dtype, x, y):
    return Device(
        id=did,
        family=family,
        type=dtype,
        level_id="L1",
        position=Point3(x, y, 4.0),
        mounting_height=4.0,
    )


def _manifest(devices):
    return SpecManifest(
        schema_version="1.0.0",
        project=Project(id="p", name="P", units="feet"),
        levels=[],
        devices=devices,
    )


def test_catalog_unions_family_and_type_sorted_unique():
    manifest = _manifest(
        [
            _device("d1", "Card Reader", "HID-R10", 0.0, 0.0),
            _device("d2", "Exit Sign", "EXIT-LED", 1.0, 0.0),
            _device("d3", "Card Reader", "HID-R10", 2.0, 0.0),  # dup family+type
        ]
    )
    assert catalog_from_manifest(manifest) == ["Card Reader", "EXIT-LED", "Exit Sign", "HID-R10"]


def _capture(observations):
    shot = Shot(
        id="S1",
        level_id="L1",
        rgb_image="s.jpg",
        intrinsics=Intrinsics(fx=1.0, fy=1.0, cx=0.0, cy=0.0, width=10, height=10),
        pose=[1.0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        pin=Pin(x=0.0, y=0.0, heading=0.0),
        observations=observations,
    )
    return CapturePackage(schema_version="1.0.0", project_id="p", shots=[shot])


def test_enrich_scores_unscored_raw_hint():
    manifest = _manifest(
        [
            _device("d1", "Card Reader", "HID-R10", 0.0, 0.0),
            _device("d2", "Exit Sign", "EXIT-LED", 1.0, 0.0),
        ]
    )
    obs = Observation(position=Point3(0.0, 0.0, 4.0), detected_type="illuminated exit sign")
    capture = _capture([obs])
    enrich_capture_types(capture, manifest)
    assert obs.detected_type == "Exit Sign"
    assert obs.type_confidence == SUBSTRING_MATCH_CONFIDENCE


def test_enrich_leaves_calibrated_observation_untouched():
    manifest = _manifest([_device("d1", "Card Reader", "HID-R10", 0.0, 0.0)])
    obs = Observation(position=Point3(0.0, 0.0, 4.0), detected_type="HID-R10", type_confidence=0.85)
    enrich_capture_types(_capture([obs]), manifest)
    assert obs.detected_type == "HID-R10"
    assert obs.type_confidence == 0.85  # unchanged: already scored


def test_enrich_ignores_observation_without_detected_type():
    manifest = _manifest([_device("d1", "Card Reader", "HID-R10", 0.0, 0.0)])
    obs = Observation(position=Point3(0.0, 0.0, 4.0))
    enrich_capture_types(_capture([obs]), manifest)
    assert obs.detected_type is None
    assert obs.type_confidence is None


def test_enrich_marks_unknown_raw_hint_as_failed():
    manifest = _manifest([_device("d1", "Card Reader", "HID-R10", 0.0, 0.0)])
    obs = Observation(position=Point3(0.0, 0.0, 4.0), detected_type="smoke detector")
    capture = _capture([obs])
    enrich_capture_types(capture, manifest)
    assert obs.detected_type == ""  # canonicalized to the failed state
    assert obs.type_confidence is None
    # IDEMPOTENCY: a second pass over the now-failed state ("" / None) must be a
    # no-op. detect_type("", catalog) -> ("", None) and type_confidence is still
    # None, so the failed state is stable under re-enrich (the pipeline may run it
    # more than once).
    enrich_capture_types(capture, manifest)
    assert obs.detected_type == ""
    assert obs.type_confidence is None
