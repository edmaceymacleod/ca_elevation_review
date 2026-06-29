"""Pretty JSON writer for the verdict report.

Serializes :meth:`VerdictReport.to_dict` to a stable, human-diffable JSON
document (sorted keys, two-space indent). This is the same wire shape validated
against ``schemas/verdict_report.schema.json`` and consumed by the Revit
write-back, so it must round-trip through :meth:`VerdictReport.from_dict`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import VerdictReport


def render_json(report: VerdictReport) -> str:
    """Return the pretty-printed JSON string for ``report``."""
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)
