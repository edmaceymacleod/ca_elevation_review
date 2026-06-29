"""Verdict -> override-colour mapping and result grouping. Pure stdlib.

The pure half of write-back: decide what colour each device's verdict maps to and
group the report's per-device results for application. The actual Revit
``OverrideGraphicSettings`` / transaction / marker logic is in ``revit_writeback``
(LIVE).

Raise-safety is a hard requirement: an unknown/unmapped verdict maps to a loud
**sentinel** colour (magenta) and logs a warning -- it NEVER ``KeyError``s.
Rationale: a KeyError here would land inside a Revit transaction on Ed's
hardware, the worst place to discover a gap. The exhaustiveness ratchet
(``test_writeback_ratchet.py``, engine-tier) is best-effort; this fail-soft
behaviour is the real guard.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

RGB = Tuple[int, int, int]

# Verdict string -> RGB. Verdict strings mirror ca_elevation_engine.models.Verdict
# values; we hardcode the strings to keep this module engine-import-free.
VERDICT_COLORS: Dict[str, RGB] = {
    "pass": (26, 127, 55),  # green
    "flag": (191, 135, 0),  # orange
    "absent": (207, 34, 46),  # red
    "type_mismatch": (130, 80, 223),  # purple
}

# Loud, deliberately ugly colour for an unmapped verdict -- a visible signal, not
# a crash.
SENTINEL_COLOR: RGB = (255, 0, 255)  # magenta


def color_for_verdict(verdict: str) -> RGB:
    """Map a verdict string to an RGB colour, fail-soft to the sentinel."""
    try:
        return VERDICT_COLORS[verdict]
    except KeyError:
        logger.warning(
            "unmapped verdict %r -> sentinel colour %s; writeback MAPPING may be "
            "stale vs the engine's Verdict enum",
            verdict,
            SENTINEL_COLOR,
        )
        return SENTINEL_COLOR


def is_known_verdict(verdict: str) -> bool:
    return verdict in VERDICT_COLORS


class DeviceOverride:
    """One element's intended override (the input to LIVE ``revit_writeback``)."""

    __slots__ = ("device_id", "verdict", "color")

    def __init__(self, device_id: str, verdict: str, color: RGB) -> None:
        self.device_id = device_id
        self.verdict = verdict
        self.color = color

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DeviceOverride({self.device_id!r}, {self.verdict!r}, {self.color})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, DeviceOverride)
            and other.device_id == self.device_id
            and other.verdict == self.verdict
            and other.color == self.color
        )


def overrides_for_report(report: dict) -> List[DeviceOverride]:
    """Build the list of per-element overrides from a verdict report dict.

    Keyed by ``device_id`` (the Revit UniqueId the engine echoed through). If the
    same device id appears twice, the last result wins (and is logged).
    """
    by_id: Dict[str, DeviceOverride] = {}
    for result in report.get("device_results", []):
        device_id = result.get("device_id")
        verdict = result.get("verdict", "")
        if not device_id:
            logger.warning("device result with no device_id skipped: %r", result)
            continue
        if not verdict:
            # A missing/empty verdict is a STRUCTURALLY MALFORMED per-device record
            # (the schema marks verdict required), distinct from a present-but-
            # unrecognised verdict (engine-enum drift). Log it with its own message
            # and apply the sentinel colour DIRECTLY -- routing "" through
            # color_for_verdict would emit the generic "unmapped verdict -> sentinel"
            # warning, conflating a corrupt record with engine-enum drift. We still
            # render the loud sentinel (the module's fail-soft contract).
            logger.warning(
                "device result %r has missing/empty verdict; rendering sentinel "
                "colour (report record may be corrupt)",
                device_id,
            )
            color = SENTINEL_COLOR
        else:
            color = color_for_verdict(verdict)
        if device_id in by_id:
            logger.warning("duplicate device_id %r in report; last result wins", device_id)
        by_id[device_id] = DeviceOverride(device_id, verdict, color)
    return list(by_id.values())
