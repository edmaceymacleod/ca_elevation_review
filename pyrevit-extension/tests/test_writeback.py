"""FLOOR tier: verdict->colour mapping + result grouping (no engine import)."""

from __future__ import annotations

import logging

from ca_elevation_revit import writeback
from ca_elevation_revit.writeback import SENTINEL_COLOR, VERDICT_COLORS


def test_known_verdicts_map_to_distinct_colours():
    colours = {writeback.color_for_verdict(v) for v in ("pass", "flag", "absent", "type_mismatch")}
    assert len(colours) == 4
    assert SENTINEL_COLOR not in colours


def test_unknown_verdict_is_sentinel_not_keyerror(caplog):
    with caplog.at_level(logging.WARNING):
        colour = writeback.color_for_verdict("totally_new_verdict")
    assert colour == SENTINEL_COLOR
    assert any("unmapped verdict" in r.message for r in caplog.records)


def test_is_known_verdict():
    assert writeback.is_known_verdict("pass")
    assert not writeback.is_known_verdict("nope")


def test_overrides_for_report_groups_by_device_id():
    report = {
        "device_results": [
            {"device_id": "uid-1", "verdict": "pass"},
            {"device_id": "uid-2", "verdict": "flag"},
        ]
    }
    overrides = writeback.overrides_for_report(report)
    assert {o.device_id for o in overrides} == {"uid-1", "uid-2"}
    o1 = next(o for o in overrides if o.device_id == "uid-1")
    assert o1.color == VERDICT_COLORS["pass"]


def test_overrides_duplicate_device_id_last_wins(caplog):
    report = {
        "device_results": [
            {"device_id": "uid-1", "verdict": "pass"},
            {"device_id": "uid-1", "verdict": "flag"},
        ]
    }
    with caplog.at_level(logging.WARNING):
        overrides = writeback.overrides_for_report(report)
    assert len(overrides) == 1
    assert overrides[0].verdict == "flag"
    assert any("duplicate device_id" in r.message for r in caplog.records)


def test_overrides_skips_result_without_device_id():
    report = {"device_results": [{"verdict": "pass"}, {"device_id": "uid-2", "verdict": "absent"}]}
    overrides = writeback.overrides_for_report(report)
    assert [o.device_id for o in overrides] == ["uid-2"]
