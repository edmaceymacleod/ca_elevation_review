"""Coverage ratchets over the verification registry (design principle #2).

These tests fail the build when the engine's declared capabilities and its
proven fixture coverage drift apart. They are intentionally strict: adding a new
verdict class or v1 check, or a new scenario, forces a corresponding fixture +
golden update in the same change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ca_elevation_engine import registry
from ca_elevation_engine.models import Verdict

pytestmark = pytest.mark.unit

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ENGINE_ROOT / "fixtures"


def test_registry_verdicts_match_enum():
    # The registry must enumerate exactly the verdict classes the model defines.
    assert set(registry.VERDICTS) == set(Verdict)


def test_every_scenario_has_seeder_and_golden():
    for scenario, golden in registry.SCENARIO_GOLDENS.items():
        seeder = FIXTURES / "seeders" / f"{scenario}.py"
        assert seeder.exists(), f"scenario {scenario} missing seeder {seeder}"
        # Each scenario is bound to its OWN golden report (not just "some golden").
        golden_path = FIXTURES / "golden" / golden
        assert golden_path.exists(), f"scenario {scenario} missing golden {golden_path}"


def test_golden_demonstrates_every_verdict_class():
    """The fixture suite must exercise every emittable verdict class.

    Unions verdicts across ALL scenario goldens so the coverage ratchet
    considers the whole corpus, not just f01.
    """
    seen: set[str] = set()
    for golden_name in registry.SCENARIO_GOLDENS.values():
        g = json.loads((FIXTURES / "golden" / golden_name).read_text())
        seen |= {r["verdict"] for r in g["device_results"]}
    required = {v.value for v in registry.VERDICTS}
    missing = required - seen
    assert not missing, f"no golden case demonstrates verdict(s): {sorted(missing)}"


def test_scenario_payload_stems_complete():
    assert set(registry.SCENARIO_PAYLOAD_STEMS) == set(registry.SCENARIO_GOLDENS)


def test_check_ratchet_count():
    """Pin the number of declared checks so additions are deliberate.

    Bump this when you intentionally add a check -- and add its fixture coverage
    in the same change.
    """
    assert len(registry.CHECKS) == 7
    assert len(registry.v1_checks()) == 5


def test_out_of_scope_checks_marked_not_v1():
    for cid in ("sku_identity", "behind_wall"):
        assert registry.check_by_id(cid).in_v1 is False


def test_v1_checks_have_titles():
    for c in registry.v1_checks():
        assert c.title and c.notes
