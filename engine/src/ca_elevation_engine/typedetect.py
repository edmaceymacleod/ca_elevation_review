"""Lightweight device-type detection heuristic (vision-backend stand-in).

The full vision backend is out of scope for v1. Until it lands, an observation
may arrive carrying only a *raw* ``detected_type`` hint (what a coarse detector
or operator read off the device) and no calibrated ``type_confidence``. This
module canonicalizes that raw hint against the project's known device-type
vocabulary -- every ``family`` and ``type`` string in the manifest -- by
case-insensitive substring matching, and assigns a confidence. The
canonicalized ``detected_type`` + ``type_confidence`` then feed the existing
TYPE_MISMATCH path in :mod:`ca_elevation_engine.verdict`.

Contract for :func:`detect_type` (mirrors the ``detected_type`` tri-state):
    raw is None              -> (None, None)              no detection attempted
    raw is blank/whitespace  -> ("", None)                detection attempted, failed
    raw matches the catalog  -> (canonical, confidence)   detected
    raw matches nothing       -> ("", None)               unreconcilable -> failed

Confidences are emitted at or above ``verdict.TYPE_MISMATCH_MIN_CONFIDENCE``
(0.6) so a confident, disagreeing match can fire a TYPE_MISMATCH. The heuristic
is deliberately coarse and opportunistic (registry check ``device_type`` is
"vision-assisted, human-confirmed"); it never fabricates a type outside the
manifest's own vocabulary. Pure: no IO, no heavy deps.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import CapturePackage, SpecManifest

EXACT_MATCH_CONFIDENCE = 0.9
SUBSTRING_MATCH_CONFIDENCE = 0.7


def catalog_from_manifest(manifest: SpecManifest) -> list[str]:
    """Sorted, de-duplicated non-empty family+type vocabulary from the manifest."""
    seen: dict[str, None] = {}
    for device in manifest.devices:
        for token in (device.family, device.type):
            value = (token or "").strip()
            if value:
                seen.setdefault(value, None)
    return sorted(seen)


def detect_type(raw: str | None, catalog: Iterable[str]) -> tuple[str | None, float | None]:
    """Canonicalize a raw type hint against ``catalog``; return (type, confidence).

    See the module docstring for the full tri-state contract.
    """
    if raw is None:
        return None, None
    norm = raw.strip()
    if not norm:
        return "", None
    low = norm.lower()

    candidates = [c.strip() for c in catalog if c and c.strip()]

    # Exact (case-insensitive) match -> highest confidence.
    for name in candidates:
        if name.lower() == low:
            return name, EXACT_MATCH_CONFIDENCE

    # Substring match in either direction -> medium confidence. Prefer the most
    # specific (longest) catalog name so "exit sign" beats a shorter incidental hit.
    best_name: str | None = None
    best_len = -1
    for name in candidates:
        nl = name.lower()
        if (nl in low or low in nl) and len(nl) > best_len:
            best_name, best_len = name, len(nl)
    if best_name is not None:
        return best_name, SUBSTRING_MATCH_CONFIDENCE

    # Detector read something, but it reconciles to no known type -> failed.
    return "", None


def enrich_capture_types(capture: CapturePackage, manifest: SpecManifest) -> None:
    """Fill ``detected_type``/``type_confidence`` for unscored observations in place.

    Only observations that carry a raw ``detected_type`` but NO
    ``type_confidence`` are touched. An observation whose ``type_confidence`` is
    already set (a calibrated vision backend, or a hand-authored fixture) is left
    exactly as-is, so existing goldens never move. An observation with no
    ``detected_type`` at all is left untouched (no raw hint to canonicalize).
    """
    catalog = catalog_from_manifest(manifest)
    for shot in capture.shots:
        for obs in shot.observations:
            if obs.type_confidence is not None:
                continue
            if obs.detected_type is None:
                continue
            detected, confidence = detect_type(obs.detected_type, catalog)
            obs.detected_type = detected
            obs.type_confidence = confidence
