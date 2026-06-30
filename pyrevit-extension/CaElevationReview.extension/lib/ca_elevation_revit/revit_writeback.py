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
import re
from typing import List, Optional

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
# The marker now ENCODES the view id the override was applied in (``[CAElev:123]``)
# because the Comments param is model-wide (one value per element, shared across
# views) while the colour override is PER-VIEW. Without the view id, a clear pass
# run with a different active view would strip the model-wide marker while leaving
# the colour in the original view -- an unclearable stale colour. Encoding the view
# lets clear_prior_overrides reset the override in the view it was actually applied
# in, regardless of which view is active. A bare legacy ``[CAElev]`` (no id) is
# still recognised so markers written by older runs are not orphaned.
_SENTINEL = "[CAElev]"
_VIEW_MARKER_RE = re.compile(r"\[CAElev(?::(-?\d+))?\]")


def _view_sentinel(view_int: int) -> str:
    """The marker token encoding the view id, e.g. ``[CAElev:123]``."""
    return f"[CAElev:{view_int}]"


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

        # (2) Apply the current report's overrides, marking each element with the
        #     ACTIVE view id so a later clear can reset the right view.
        from ._compat import eid_value

        view_int = eid_value(view.Id)
        applied = 0
        missing = 0
        unmarked = 0  # override applied but marker could not be written
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
            if not _stamp_marker(el, view_int):
                # The colour override landed (it targets the view) but the
                # ownership marker could not be stamped (Comments read-only/absent),
                # so a future re-import that DROPS this device will NOT find the
                # marker and will leave a stale colour behind. Count + warn so the
                # broken-idempotency case is visible instead of a clean "applied".
                unmarked += 1
            applied += 1

        txn.Commit()
        if missing:
            logger.info(
                "CA Elevation: applied %d override(s); %d device id(s) unresolved",
                applied,
                missing,
            )
        if unmarked:
            logger.warning(
                "CA Elevation: %d of %d override(s) could not be marked "
                "(Comments read-only/absent); those device(s) will NOT be cleared "
                "on a later re-import that drops them and may keep a stale colour",
                unmarked,
                applied,
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

    The ownership marker is a model-wide Comments value but the colour override is
    PER-VIEW, so this enumerates marked elements DOCUMENT-WIDE (not just the passed
    ``view``) and resets each element's override in the SPECIFIC view its marker
    records. That clears a stale colour left in a view that is not currently active
    -- the previous active-view-only pass could strip the model-wide marker while
    leaving the colour orphaned in another view. ``view`` is still used as the
    fallback for legacy markers that carry no view id.
    """
    # LIVE: requires Revit.
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        OverrideGraphicSettings,
        Transaction,
    )

    from ._compat import eid_value

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
        fallback_view_int = eid_value(view.Id)
        view_cache = {fallback_view_int: view}  # view_int -> View (resolved lazily)
        # Document-wide (no view filter): a marked element may carry an override in
        # a view other than the active one.
        collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
        # Materialise before mutating params: editing Comments mid-walk must not
        # disturb the collector's lazy enumeration.
        for el in list(collector):
            # The Comments sentinel -- NOT the colour -- is the authoritative
            # "this is ours" test, so a hand-coloured or colour-sharing element
            # is never touched and a dropped device IS reset.
            marked_view_int = _marked_view_int(el)
            if marked_view_int is None:
                continue
            # A legacy marker (no encoded view id) yields -1; reset in the passed
            # view, the best available guess for where the legacy colour landed.
            target_int = fallback_view_int if marked_view_int == -1 else marked_view_int
            target_view = _resolve_view(doc, target_int, view_cache)
            if target_view is not None:
                target_view.SetElementOverrides(el.Id, default_ogs)
            _strip_marker(el)
            cleared += 1
        if own_txn is not None:
            own_txn.Commit()
        return cleared
    except Exception:
        if own_txn is not None and own_txn.HasStarted() and not own_txn.HasEnded():
            own_txn.RollBack()
        raise


def _resolve_view(doc, view_int, cache):  # noqa: ANN001
    """Resolve a View by its integer id, memoised. None if it no longer exists."""
    if view_int in cache:
        return cache[view_int]
    from ._compat import make_eid

    try:
        resolved = doc.GetElement(make_eid(view_int))
    except Exception:
        resolved = None
    cache[view_int] = resolved
    return resolved


# --- marker + override helpers (palette-independent Comments sentinel) --------


def _comments_param(el):  # noqa: ANN001
    """Return the element's Comments instance Parameter, or None if absent."""
    from Autodesk.Revit.DB import BuiltInParameter

    try:
        return el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    except Exception:
        return None


def _has_marker(el) -> bool:  # noqa: ANN001
    """True when the element's Comments param carries any CA-Elevation marker."""
    return _marked_view_int(el) is not None


def _marked_view_int(el) -> Optional[int]:  # noqa: ANN001
    """The view id encoded in the element's marker, -1 for a legacy id-less marker.

    Returns ``None`` when the element carries no CA-Elevation marker at all.
    """
    param = _comments_param(el)
    if param is None:
        return None
    match = _VIEW_MARKER_RE.search(param.AsString() or "")
    if match is None:
        return None
    captured = match.group(1)
    return int(captured) if captured is not None else -1


def _stamp_marker(el, view_int: int) -> bool:  # noqa: ANN001
    """Append the view-scoped sentinel token to Comments. Returns whether written.

    Returns ``False`` when the Comments param is absent or read-only (the marker
    could NOT be written, breaking idempotency for this element); ``True`` when the
    marker is present afterwards (newly written, or already there).
    """
    param = _comments_param(el)
    if param is None or param.IsReadOnly:
        return False
    value = param.AsString() or ""
    if _VIEW_MARKER_RE.search(value):
        return True  # already marked (this or a prior run); idempotent
    token = _view_sentinel(view_int)
    param.Set((value + " " + token).strip() if value else token)
    return True


def _strip_marker(el) -> None:  # noqa: ANN001
    """Remove any CA-Elevation marker from Comments, leaving user text intact."""
    param = _comments_param(el)
    if param is None or param.IsReadOnly:
        return
    value = param.AsString() or ""
    if not _VIEW_MARKER_RE.search(value):
        return
    param.Set(_VIEW_MARKER_RE.sub("", value).strip())


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
