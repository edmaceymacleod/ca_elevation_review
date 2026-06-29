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

import logging
from typing import List

from .writeback import DeviceOverride

logger = logging.getLogger(__name__)

# Logical name of the "this element was overridden by CA Elevation Review"
# marker. An arbitrary model may have NO project/shared parameter literally
# named this, and adding shared parameters from a script is heavy -- so the
# *physical* marker is a sentinel token (``_SENTINEL``) appended to each
# element's built-in Comments instance parameter. That needs no schema and no
# model setup, and -- being palette-independent -- it stays the authoritative
# record of ownership even when two verdicts share a colour, which is what makes
# the "device dropped from the new report" case clear correctly.
MARKER_PARAM = "CAElevationOverridden"

# Physical marker token, appended to BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS.
_SENTINEL = "[CAElev]"


def apply_verdicts(doc, view, overrides: List[DeviceOverride]) -> int:  # noqa: ANN001
    """Idempotently apply verdict overrides to ``view``. LIVE. Returns count applied.

    ``overrides`` come from ``writeback.overrides_for_report``. Elements are
    resolved by ``doc.GetElement(unique_id)`` (the UniqueId overload) -- which is
    why ``revit_extract`` must stamp UniqueId as the device id.
    """
    # LIVE: requires Revit (pythonnet/CLR idioms, not "C# in Python").
    from Autodesk.Revit.DB import Transaction

    txn = Transaction(doc, "CA Elevation verdicts")
    txn.Start()
    try:
        # (1) Reset every element this tool previously marked, so a re-import
        #     whose report DROPPED a device leaves no stale colour behind. This
        #     runs inside the transaction just opened: clear_prior_overrides sees
        #     doc.IsModifiable == True and does NOT open a second one.
        clear_prior_overrides(doc, view)

        # Resolve the model's solid fill pattern ONCE (a doc-level lookup, not
        # per element). Without it the surface foreground pattern is "<none>",
        # so the colour shows on plan lines but the surface fill renders empty in
        # 3D/section views -- the review-flagged gap. None => fall back to the
        # colour-only override and log, never crash.
        solid_fill_id = _solid_fill_pattern_id(doc)
        if solid_fill_id is None:
            logger.warning(
                "no solid fill pattern found in this model; surface fills will "
                "not render (plan line colour still applied)"
            )

        # (2) Apply the current report's overrides, marking each element.
        applied = 0
        missing = 0
        for override in overrides:
            # UniqueId overload: pass the stable GUID-like string straight in.
            el = doc.GetElement(override.device_id)
            if el is None:
                missing += 1
                logger.warning(
                    "device_id %r did not resolve in this model; skipped",
                    override.device_id,
                )
                continue
            ogs = _build_override(override.color, solid_fill_id)
            view.SetElementOverrides(el.Id, ogs)
            _stamp_marker(el)
            applied += 1

        txn.Commit()
        if missing:
            logger.info(
                "CA Elevation: applied %d override(s); %d device id(s) unresolved",
                applied,
                missing,
            )
        return applied
    except Exception:
        if txn.HasStarted() and not txn.HasEnded():
            txn.RollBack()
        raise


def clear_prior_overrides(doc, view) -> int:  # noqa: ANN001
    """Reset overrides + clear the marker on every previously-marked element. LIVE.

    Returns the number cleared. This is what makes a re-import idempotent for
    devices dropped from the new report.
    """
    # LIVE: requires Revit.
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        OverrideGraphicSettings,
        Transaction,
    )

    # Transaction policy: apply_verdicts calls us with its own transaction
    # already open (doc.IsModifiable is True), so we must NOT open a second one.
    # Called standalone the document is not modifiable, so we open + commit our
    # own transaction.
    own_txn = None
    if not doc.IsModifiable:
        own_txn = Transaction(doc, "CA Elevation clear overrides")
        own_txn.Start()
    try:
        cleared = 0
        default_ogs = OverrideGraphicSettings()  # a fresh, all-default override
        collector = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
        # Materialise before mutating params: editing Comments mid-walk must not
        # disturb the collector's lazy enumeration.
        for el in list(collector):
            # The Comments sentinel -- NOT the colour -- is the authoritative
            # "this is ours" test, so a hand-coloured or colour-sharing element
            # is never touched and a dropped device IS reset.
            if not _has_marker(el):
                continue
            view.SetElementOverrides(el.Id, default_ogs)
            _strip_marker(el)
            cleared += 1
        if own_txn is not None:
            own_txn.Commit()
        return cleared
    except Exception:
        if own_txn is not None and own_txn.HasStarted() and not own_txn.HasEnded():
            own_txn.RollBack()
        raise


# --- marker + override helpers (palette-independent Comments sentinel) --------


def _comments_param(el):  # noqa: ANN001
    """Return the element's Comments instance Parameter, or None if absent."""
    from Autodesk.Revit.DB import BuiltInParameter

    try:
        return el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    except Exception:
        return None


def _has_marker(el) -> bool:  # noqa: ANN001
    """True when the element's Comments param carries our sentinel token."""
    param = _comments_param(el)
    if param is None:
        return False
    return _SENTINEL in (param.AsString() or "")


def _stamp_marker(el) -> None:  # noqa: ANN001
    """Append the sentinel token to Comments if not already present."""
    param = _comments_param(el)
    if param is None or param.IsReadOnly:
        return
    value = param.AsString() or ""
    if _SENTINEL in value:
        return
    param.Set((value + " " + _SENTINEL).strip() if value else _SENTINEL)


def _strip_marker(el) -> None:  # noqa: ANN001
    """Remove the sentinel token from Comments, leaving any user text intact."""
    param = _comments_param(el)
    if param is None or param.IsReadOnly:
        return
    value = param.AsString() or ""
    if _SENTINEL not in value:
        return
    param.Set(value.replace(_SENTINEL, "").strip())


def _solid_fill_pattern_id(doc):  # noqa: ANN001
    """Return an ElementId of a SOLID fill pattern in ``doc``, or None. LIVE.

    Needed so the surface/cut foreground override paints a filled colour rather
    than an empty pattern. Prefers a *drafting*-target solid fill (renders in any
    view type); falls back to any solid fill. The well-known ``"<Solid fill>"``
    name is localised in non-English Revit, so we test ``IsSolidFill`` rather than
    matching the name. None when the model has no solid fill pattern at all.
    """
    from Autodesk.Revit.DB import (
        FillPatternElement,
        FillPatternTarget,
        FilteredElementCollector,
    )

    any_solid = None
    for fpe in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            pattern = fpe.GetFillPattern()
        except Exception:
            continue
        if pattern is None or not pattern.IsSolidFill:
            continue
        if any_solid is None:
            any_solid = fpe.Id
        try:
            if pattern.Target == FillPatternTarget.Drafting:
                return fpe.Id  # drafting solid fill: ideal, stop here
        except Exception:
            pass
    return any_solid


def _build_override(color, solid_fill_id=None):  # noqa: ANN001
    """Build OverrideGraphicSettings painting projection lines + surface fill.

    ``color`` is a 3-int RGB tuple (Autodesk.Revit.DB.Color takes byte r,g,b;
    pythonnet narrows the ints). ``solid_fill_id`` is the ElementId of a solid
    fill pattern (from ``_solid_fill_pattern_id``); without it the surface/cut
    foreground colour is set but the pattern stays "<none>", so the fill renders
    empty in 3D/section views. Setter names have drifted across API years, so each
    is guarded with ``hasattr``; cut-plane setters are applied too for the
    section/3D views where they exist.
    """
    from Autodesk.Revit.DB import Color, OverrideGraphicSettings

    revit_color = Color(*color)
    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(revit_color)
    if hasattr(ogs, "SetSurfaceForegroundPatternColor"):
        ogs.SetSurfaceForegroundPatternColor(revit_color)
    if hasattr(ogs, "SetSurfaceForegroundPatternVisible"):
        ogs.SetSurfaceForegroundPatternVisible(True)
    if solid_fill_id is not None and hasattr(ogs, "SetSurfaceForegroundPatternId"):
        ogs.SetSurfaceForegroundPatternId(solid_fill_id)
    if hasattr(ogs, "SetCutLineColor"):
        ogs.SetCutLineColor(revit_color)
    if hasattr(ogs, "SetCutForegroundPatternColor"):
        ogs.SetCutForegroundPatternColor(revit_color)
    if hasattr(ogs, "SetCutForegroundPatternVisible"):
        ogs.SetCutForegroundPatternVisible(True)
    if solid_fill_id is not None and hasattr(ogs, "SetCutForegroundPatternId"):
        ogs.SetCutForegroundPatternId(solid_fill_id)
    return ogs
