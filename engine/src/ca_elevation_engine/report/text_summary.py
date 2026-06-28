"""Plain-text one-screen summary of a verdict report.

Used by the CLI to print a quick, terminal-friendly digest: a counts line plus
a short list of every non-pass device. No colors, no dependencies -- pure ASCII
so it is safe in any console or log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Verdict

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import VerdictReport

# Non-pass verdicts, in the order they are listed under the counts line.
_PROBLEM_ORDER = (Verdict.FLAG, Verdict.ABSENT, Verdict.TYPE_MISMATCH)


def summarize(report: VerdictReport) -> str:
    """Return a one-screen plaintext summary of ``report``."""
    s = report.summary
    lines: list[str] = []

    header = (
        f"PASS {s['pass']}  FLAG {s['flag']}  ABSENT {s['absent']}  "
        f"TYPE_MISMATCH {s['type_mismatch']}  ({s['total']} devices)"
    )
    lines.append(header)

    problems = [r for r in report.device_results if r.verdict is not Verdict.PASS]
    # Surface problems grouped by severity, stable by device id within a group.
    rank = {v: i for i, v in enumerate(_PROBLEM_ORDER)}
    problems.sort(key=lambda r: (rank.get(r.verdict, 99), r.device_id))

    if not problems:
        lines.append("")
        lines.append("All devices pass.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Non-pass devices:")
    for r in problems:
        verdict = r.verdict.value.upper()
        bits = [f"  [{verdict}] {r.device_id}"]
        descr = " / ".join(x for x in (r.family, r.type) if x)
        if descr:
            bits.append(f"({descr})")
        if r.deltas.position is not None:
            bits.append(f"dpos={r.deltas.position:.3f}")
        if r.deltas.mounting_height is not None:
            bits.append(f"dmh={r.deltas.mounting_height:.3f}")
        if r.deltas.orientation is not None:
            bits.append(f"dori={r.deltas.orientation:.1f}deg")
        if r.approximate:
            bits.append("[approx]")
        if r.notes:
            bits.append("- " + "; ".join(r.notes))
        lines.append(" ".join(bits))

    return "\n".join(lines)
