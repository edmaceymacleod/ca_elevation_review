"""LIVE: apply verdict colours to elements, idempotently.

The third Revit-touching module. Owns BOTH application and marker-based clearing
of prior overrides, so a re-import is idempotent even when a device was dropped
from the new report.

Idempotency mechanism (genuinely new logic, NOT a C# port -- the C#
``VerdictWriteback.Clear`` was never wired and cleared by the *new* report's ids,
which cannot remove stale colours on dropped devices):

  1. Enumerate every element in the active view carrying the CA-Elevation
     **marker**, reset its ``OverrideGraphicSettings``, and clear the marker.
  2. Apply the new report's overrides, stamping the marker on each.

The model itself is the record -- no persisted prior-override store (avoids
extensible-storage schema GUIDs and their own partial-set failure modes). All of
this runs inside a single ``Transaction``.
"""

from __future__ import annotations

from typing import List

from .writeback import DeviceOverride

# Name of the project/shared parameter (or named element set) used as the
# "this element was overridden by CA Elevation Review" marker.
MARKER_PARAM = "CAElevationOverridden"


def apply_verdicts(doc, view, overrides: List[DeviceOverride]) -> int:  # noqa: ANN001
    """Idempotently apply verdict overrides to ``view``. LIVE. Returns count applied.

    ``overrides`` come from ``writeback.overrides_for_report``. Elements are
    resolved by ``doc.GetElement(unique_id)`` (the UniqueId overload) -- which is
    why ``revit_extract`` must stamp UniqueId as the device id.
    """
    # LIVE: requires Revit (pythonnet/CLR idioms, not "C# in Python").
    from Autodesk.Revit.DB import (  # noqa: F401  # type: ignore
        Color,
        OverrideGraphicSettings,
        Transaction,
    )

    raise NotImplementedError(
        "LIVE: open a Transaction; (1) clear_prior_overrides(doc, view) by marker; "
        "(2) for each override, el = doc.GetElement(override.device_id) [UniqueId "
        "overload], build OverrideGraphicSettings with Color(*override.color), "
        "view.SetElementOverrides(el.Id, ogs), and stamp MARKER_PARAM. Idempotent "
        "re-import incl. the drop-a-device case is a live acceptance criterion."
    )


def clear_prior_overrides(doc, view) -> int:  # noqa: ANN001
    """Reset overrides + clear the marker on every previously-marked element. LIVE.

    Returns the number cleared. This is what makes a re-import idempotent for
    devices dropped from the new report.
    """
    # LIVE: requires Revit.
    from Autodesk.Revit.DB import (  # noqa: F401  # type: ignore
        FilteredElementCollector,
        OverrideGraphicSettings,
    )

    raise NotImplementedError(
        "LIVE: enumerate elements in `view` carrying MARKER_PARAM, reset each via "
        "view.SetElementOverrides(id, OverrideGraphicSettings()) and clear the "
        "marker. Validate the drop-a-device case on Ed's hardware."
    )
