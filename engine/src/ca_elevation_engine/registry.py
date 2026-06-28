"""The verification registry -- single source of truth for what the engine checks.

Ported from the design doc's principle #2: a registry declares every check the
engine performs and every verdict class it can emit, each with a stable id and a
v1 status. The companion ratchet test (``tests/test_registry.py``) fails the
build when a new check or verdict ships without fixture coverage and a golden
case -- coverage can only go up, never silently down.

This keeps the engine honest: you cannot add a capability the README implies is
verified without also proving it on a fixture.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Verdict


@dataclass(frozen=True)
class Check:
    """One verification dimension the engine measures."""

    id: str
    title: str
    in_v1: bool
    notes: str = ""


# The verification scope, v1 (mirrors the table in design.md). ``in_v1=False``
# rows are declared-but-out-of-scope so the ratchet test can assert they are NOT
# silently exercised/claimed.
CHECKS: tuple[Check, ...] = (
    Check("presence", "Presence", True, "robust, needs no scale"),
    Check("position", "Position", True, "metric via LiDAR; approximate without it"),
    Check("mounting_height", "Mounting height", True, "needs a vertical datum"),
    Check("orientation", "Orientation", True, "up/down, facing"),
    Check("device_type", "Device type", True, "opportunistic; vision-assisted, human-confirmed"),
    Check("sku_identity", "Exact SKU identity", False, "out of scope for v1"),
    Check(
        "behind_wall",
        "Behind-wall (cable, backbox)",
        False,
        "not observable from a surface capture",
    ),
)

# Every verdict class the engine can emit. The ratchet test requires each to be
# demonstrated by at least one golden fixture case.
VERDICTS: tuple[Verdict, ...] = (
    Verdict.PASS,
    Verdict.FLAG,
    Verdict.ABSENT,
    Verdict.TYPE_MISMATCH,
)

# Registered capture scenarios (fixtures). Each must have a seeder and a golden.
SCENARIOS: tuple[str, ...] = ("f01_synthetic_office",)


def v1_checks() -> tuple[Check, ...]:
    return tuple(c for c in CHECKS if c.in_v1)


def check_by_id(check_id: str) -> Check:
    for c in CHECKS:
        if c.id == check_id:
            return c
    raise KeyError(check_id)
