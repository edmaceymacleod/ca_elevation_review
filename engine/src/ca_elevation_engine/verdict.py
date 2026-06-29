"""Classify each device match into a verdict.

Applies the per-device tolerance ruleset to the measured deltas from
:mod:`ca_elevation_engine.compare` and produces a :class:`DeviceResult` with a
verdict and a confidence. Identity stays human-confirmable: device-type
mismatch is only asserted when a legible, confident vision guess disagrees with
the expected type; otherwise type is left for human confirmation and never
fabricated.

Verdict ladder (first match wins):
  * ABSENT          -- no observation matched the expected device.
  * TYPE_MISMATCH   -- a confident detected_type disagrees with the expected type.
  * FLAG            -- matched, but a measured delta exceeds its tolerance.
  * PASS            -- matched and every measured delta within tolerance.
"""

from __future__ import annotations

from .compare import Match
from .models import (
    Deltas,
    DeviceResult,
    SpecManifest,
    Verdict,
)

# A detected device-type guess is only trusted to assert a mismatch above this
# confidence; below it, type stays human-confirmable.
TYPE_MISMATCH_MIN_CONFIDENCE = 0.6


def _types_disagree(expected_type: str, detected: str) -> bool:
    """Loose, case-insensitive token comparison of device types."""
    e = expected_type.strip().lower()
    d = detected.strip().lower()
    if not d:
        return False
    if e == d:
        return False
    # Treat one being a substring of the other as agreement (e.g. "Card Reader"
    # vs "reader").
    return e not in d and d not in e


def classify(match: Match, manifest: SpecManifest) -> DeviceResult:
    device = match.device
    tol = manifest.effective_tolerances(device)
    deltas = Deltas(
        position=match.position_delta,
        mounting_height=match.height_delta,
        orientation=match.orientation_delta,
    )
    result = DeviceResult(
        device_id=device.id,
        verdict=Verdict.PASS,
        confidence=0.5,
        family=device.family,
        type=device.type,
        matched_shot_id=match.matched_shot_id,
        deltas=deltas,
        approximate=match.approximate,
        notes=list(match.notes),
    )

    # --- ABSENT ----------------------------------------------------------- #
    if match.observation is None:
        result.verdict = Verdict.ABSENT
        # Confident absence only when the device was actually in a captured
        # view; a coverage gap is low-confidence absence.
        result.confidence = 0.7 if match.in_coverage else 0.25
        return result

    obs = match.observation

    # --- TYPE_MISMATCH ---------------------------------------------------- #
    if (
        obs.detected_type
        and obs.type_confidence is not None
        and obs.type_confidence >= TYPE_MISMATCH_MIN_CONFIDENCE
        and _types_disagree(device.type, obs.detected_type)
    ):
        result.verdict = Verdict.TYPE_MISMATCH
        result.confidence = float(obs.type_confidence)
        result.notes.append(
            f"detected type {obs.detected_type!r} disagrees with expected {device.type!r}"
        )
        return result

    if obs.detected_type and not _types_disagree(device.type, obs.detected_type):
        result.identity_confirmed = (
            obs.type_confidence is not None and obs.type_confidence >= TYPE_MISMATCH_MIN_CONFIDENCE
        )

    # --- FLAG vs PASS ----------------------------------------------------- #
    breaches: list[str] = []
    if deltas.position is not None and tol.position is not None and deltas.position > tol.position:
        breaches.append(f"position {deltas.position:.3f} > tol {tol.position:.3f}")
    if (
        deltas.mounting_height is not None
        and tol.mounting_height is not None
        and deltas.mounting_height > tol.mounting_height
    ):
        breaches.append(
            f"mounting height {deltas.mounting_height:.3f} > tol {tol.mounting_height:.3f}"
        )
    if (
        deltas.orientation is not None
        and tol.orientation is not None
        and deltas.orientation > tol.orientation
    ):
        breaches.append(f"orientation {deltas.orientation:.1f}deg > tol {tol.orientation:.1f}deg")

    result.confidence = _match_confidence(match, tol)
    if breaches:
        result.verdict = Verdict.FLAG
        result.notes.extend(breaches)
    else:
        result.verdict = Verdict.PASS
    return result


def _match_confidence(match: Match, tol) -> float:
    """Confidence in [0,1] from how tightly the observation sits in the gate."""
    if match.position_delta is None or tol.position is None:
        base = 0.6
    else:
        # 1.0 at zero delta, decaying as the delta approaches the tolerance.
        ratio = match.position_delta / max(tol.position, 1e-6)
        base = max(0.3, 1.0 - 0.5 * min(ratio, 2.0))
    if match.approximate:
        base *= 0.8
    return round(min(max(base, 0.05), 0.99), 4)


def classify_all(matches: list[Match], manifest: SpecManifest) -> list[DeviceResult]:
    return [classify(m, manifest) for m in matches]
