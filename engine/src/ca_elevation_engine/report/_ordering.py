"""Shared, deterministic verdict ordering + grouping for all renderers.

Single source of truth so HTML, PDF, and text never drift on ordering. Pure
stdlib, no heavy deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..models import Verdict

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import DeviceResult, VerdictReport

# Display order: problems first (by severity), pass last. THE one ranking.
VERDICT_DISPLAY_ORDER: tuple[Verdict, ...] = (
    Verdict.FLAG,
    Verdict.ABSENT,
    Verdict.TYPE_MISMATCH,
    Verdict.PASS,
)
_RANK = {v: i for i, v in enumerate(VERDICT_DISPLAY_ORDER)}

# Canonical full-length human labels. Renderers MAY style/abbreviate (e.g. PDF
# uses a shorter "TYPE"); this map is the long form used by HTML/text.
VERDICT_LABELS: dict[Verdict, str] = {
    Verdict.PASS: "PASS",
    Verdict.FLAG: "FLAG",
    Verdict.ABSENT: "ABSENT",
    Verdict.TYPE_MISMATCH: "TYPE MISMATCH",
}

PROBLEM_VERDICTS = frozenset({Verdict.FLAG, Verdict.ABSENT, Verdict.TYPE_MISMATCH})


@dataclass(frozen=True)
class Coverage:
    """Derived, render-time-only coverage stats. Never serialized."""

    total: int
    matched: int
    unmatched: int
    unmatched_ids: list[str]


def sort_key(r: DeviceResult) -> tuple[int, str]:
    return (_RANK.get(r.verdict, 99), r.device_id)


def ordered_results(report: VerdictReport) -> list[DeviceResult]:
    """All device results, problems-first then by device_id (stable)."""
    return sorted(report.device_results, key=sort_key)


def grouped_results(report: VerdictReport) -> list[tuple[Verdict, list[DeviceResult]]]:
    """Results bucketed by verdict in display order. Empty groups omitted.

    Within a group, sorted by device_id.
    """
    buckets: dict[Verdict, list[DeviceResult]] = {v: [] for v in VERDICT_DISPLAY_ORDER}
    for r in report.device_results:
        buckets.setdefault(r.verdict, []).append(r)
    out: list[tuple[Verdict, list[DeviceResult]]] = []
    for v in VERDICT_DISPLAY_ORDER:
        rs = sorted(buckets.get(v, []), key=lambda r: r.device_id)
        if rs:
            out.append((v, rs))
    return out


def coverage(report: VerdictReport) -> Coverage:
    """A device is 'matched' iff matched_shot_id is set. unmatched_ids sorted."""
    total = len(report.device_results)
    unmatched = sorted(r.device_id for r in report.device_results if not r.matched_shot_id)
    return Coverage(
        total=total,
        matched=total - len(unmatched),
        unmatched=len(unmatched),
        unmatched_ids=unmatched,
    )
