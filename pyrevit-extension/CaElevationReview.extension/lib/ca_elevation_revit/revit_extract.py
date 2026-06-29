"""LIVE: walk the Revit model and produce project + device dicts.

This is one of the three modules that touch the Revit API. The Revit imports are
**function-local** so the module imports cleanly in CI (static analysis still
sees them; that is why the lib mypy config sets ``ignore_missing_imports``). The
function bodies are validated only on Ed's hardware.

Output shapes are the pure ones the rest of the lib consumes:
  - ``extract_project(doc) -> dict`` with id/name/units (+ revit_file).
  - ``extract_devices(doc, level_lookup) -> List[dict]`` via
    ``manifest_builder.device_dict`` -- each id is the Revit **UniqueId**.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional

from .manifest_builder import device_dict

logger = logging.getLogger(__name__)

# Low-voltage / life-safety device categories we harvest. Resolved by NAME via
# ``getattr(BuiltInCategory, name, None)`` so a Revit build that lacks one (e.g.
# OST_NurseCallDevices on some verticals) is skipped rather than raising at
# import-of-the-enum-member time.
_DEVICE_CATEGORIES = (
    "OST_SecurityDevices",
    "OST_CommunicationDevices",
    "OST_ElectricalFixtures",
    "OST_AudioVisualDevices",
    "OST_DataDevices",
    "OST_NurseCallDevices",
    "OST_FireAlarmDevices",
)

# Level-association parameters tried (in priority order) when ``Element.LevelId``
# is invalid -- a device placed on a work plane or carried only by a schedule may
# expose its level solely through one of these. Resolved by name for the same
# version-tolerance reason as the categories above.
_LEVEL_PARAM_FALLBACKS = (
    "FAMILY_LEVEL_PARAM",
    "SCHEDULE_LEVEL_PARAM",
    "INSTANCE_REFERENCE_LEVEL_PARAM",
    "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM",
)


def extract_project(doc) -> dict:  # noqa: ANN001 - doc is a Revit Document
    """Build the manifest ``project`` block from the active document. LIVE.

    Every attribute access is guarded: an unsaved model or a family document may
    lack a populated ``ProjectInformation``, yet ``id``/``name`` must still be
    non-empty strings for the manifest to validate. ``units`` is always ``feet``
    -- positions are emitted in raw Revit internal units (see module conventions),
    so there is no DisplayUnitType inspection here.
    """
    # NOTE: only live ``doc`` attributes are touched; no Revit *type* import is
    # needed, which keeps this function importable headlessly.
    try:
        title = doc.Title or ""
    except Exception:
        title = ""

    try:
        pinfo = doc.ProjectInformation
    except Exception:
        pinfo = None

    # id: ProjectInformation.UniqueId, else the doc title, else a non-empty
    # last-resort sentinel (the schema/builder reject an empty id).
    proj_id = ""
    if pinfo is not None:
        try:
            proj_id = pinfo.UniqueId or ""
        except Exception:
            proj_id = ""
    if not proj_id:
        proj_id = title or "UNKNOWN-PROJECT"

    # name: ProjectInformation.Name, else the doc title, else a friendly default.
    name = ""
    if pinfo is not None:
        try:
            name = pinfo.Name or ""
        except Exception:
            name = ""
    if not name:
        name = title or "Untitled"

    # revit_file: the on-disk path; "" for an unsaved model is acceptable.
    try:
        revit_file = doc.PathName or ""
    except Exception:
        revit_file = ""

    return {
        "id": proj_id,
        "name": name,
        "units": "feet",  # internal units; positions are raw internal feet
        "revit_file": revit_file,
    }


def _resolve_level_int(el) -> int:  # noqa: ANN001
    """Return the device's level as an ``eid_value`` int, or ``-1`` if none.

    Tries ``Element.LevelId`` first; if that is invalid (``eid_value == -1``)
    falls back through the level-association parameters in priority order. The
    returned int is the key the caller looks up in ``level_lookup``.
    """
    from ._compat import eid_value

    # Primary: the element's own level association.
    try:
        level_id_obj = el.LevelId
    except Exception:
        level_id_obj = None
    if level_id_obj is not None:
        lvl_int = eid_value(level_id_obj)
        if lvl_int != -1:
            return lvl_int

    # Fallback: the level parameters (work-plane / schedule placements).
    from Autodesk.Revit.DB import BuiltInParameter

    for pname in _LEVEL_PARAM_FALLBACKS:
        bip = getattr(BuiltInParameter, pname, None)
        if bip is None:
            continue
        try:
            param = el.get_Parameter(bip)
        except Exception:
            param = None
        if param is None or not param.HasValue:
            continue
        try:
            lvl_int = eid_value(param.AsElementId())
        except Exception:
            continue
        if lvl_int != -1:
            return lvl_int
    return -1


def _resolve_position(el) -> Optional[Dict[str, float]]:  # noqa: ANN001
    """Return ``{x,y,z}`` in internal feet, or ``None`` if not locatable.

    Point-based family instances expose ``Location.Point`` directly. Line/curve-
    based ones (rare in these categories) have no ``.Point``; for those we fall
    back to the bounding-box centre. ``None`` means the caller should skip+count.
    """
    # Point-based: the insertion point is the device position.
    try:
        loc = el.Location
        pt = getattr(loc, "Point", None)
    except Exception:
        pt = None
    if pt is not None:
        return {"x": float(pt.X), "y": float(pt.Y), "z": float(pt.Z)}

    # Curve/line-based or no location point: bounding-box centre.
    try:
        bbox = el.get_BoundingBox(None)
    except Exception:
        bbox = None
    if bbox is not None:
        mn, mx = bbox.Min, bbox.Max
        return {
            "x": (float(mn.X) + float(mx.X)) / 2.0,
            "y": (float(mn.Y) + float(mx.Y)) / 2.0,
            "z": (float(mn.Z) + float(mx.Z)) / 2.0,
        }
    return None


def _resolve_orientation(el) -> Optional[dict]:  # noqa: ANN001
    """Plan facing angle for a ``FamilyInstance``, or ``None`` otherwise.

    ``facing_angle`` is the in-plan direction of ``FacingOrientation`` in degrees
    (0 = +X, counter-clockwise), normalised to ``[0, 360)`` to mirror the C#
    ``SpecManifestExtractor.FacingAngleDegrees`` golden. Non-FamilyInstance
    elements (which lack ``FacingOrientation``) yield ``None``.
    """
    fo = getattr(el, "FacingOrientation", None)
    if fo is None:
        return None
    try:
        angle = math.degrees(math.atan2(fo.Y, fo.X))
    except Exception:
        return None
    if angle < 0.0:
        angle += 360.0
    return {"facing_angle": angle, "up_axis": "up"}


def extract_devices(
    doc,  # noqa: ANN001
    level_lookup: Dict[int, str],
    stats: Optional[Dict[str, int]] = None,
) -> List[dict]:
    """Collect installed devices as shaped device dicts. LIVE.

    Identity invariant: stamp each element's **UniqueId** (stable GUID-like
    string) as the device id via ``manifest_builder.device_dict`` -- NOT the int
    ElementId. Write-back resolves elements by UniqueId, and the engine echoes the
    id through unchanged, so the wrong id passes every CI test yet resolves
    nothing live.

    A device whose level is not in ``level_lookup`` belongs to an un-exported
    level (``build_manifest`` would reject the unknown ``level_id``), so it is
    skipped. Per-element processing is wrapped so one bad element cannot abort the
    walk; skips and errors are counted and logged.

    ``stats`` is an optional dict the caller can pass in to RECEIVE the per-walk
    tallies (keys ``devices``/``skipped_level``/``skipped_location``/``errors``).
    A non-zero ``errors`` means real devices were dropped mid-extraction, so the
    review is INCOMPLETE -- the caller should surface that to the user (an INFO log
    is not visible inside pyRevit). The return value stays ``List[dict]`` so
    existing callers are unaffected.
    """
    # LIVE: requires Revit.
    from Autodesk.Revit.DB import (
        BuiltInCategory,
        FilteredElementCollector,
    )

    from ._compat import eid_value, element_name

    devices: List[dict] = []
    seen_unique_ids = set()
    skipped_level = 0  # device on a level we did not export
    skipped_location = 0  # device with no usable position
    errors = 0  # element that raised mid-extraction

    for cat_name in _DEVICE_CATEGORIES:
        bic = getattr(BuiltInCategory, cat_name, None)
        if bic is None:
            continue  # this Revit build lacks the category

        collector = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()
        for el in collector:
            try:
                unique_id = el.UniqueId
                if not unique_id or unique_id in seen_unique_ids:
                    continue  # de-dupe across overlapping category walks
                seen_unique_ids.add(unique_id)

                # Level gate: skip devices whose level we did not export.
                lvl_int = _resolve_level_int(el)
                level_id = level_lookup.get(lvl_int)
                if level_id is None:
                    skipped_level += 1
                    continue

                position = _resolve_position(el)
                if position is None:
                    skipped_location += 1
                    continue

                # Family / type names (guard the FamilyInstance-only Symbol path).
                try:
                    family = el.Symbol.Family.Name
                except Exception:
                    family = element_name(el)
                if not family:
                    family = element_name(el)
                symbol = getattr(el, "Symbol", None)
                type_name = element_name(symbol) if symbol is not None else element_name(el)

                devices.append(
                    device_dict(
                        unique_id=unique_id,
                        family=family,
                        type_name=type_name,
                        level_id=level_id,
                        position=position,
                        # mounting_height: left None on purpose -- the engine
                        # derives it from position.z - level.elevation, avoiding a
                        # second source of truth (see acceptance criteria).
                        mounting_height=None,
                        orientation=_resolve_orientation(el),
                        metadata={"element_id": eid_value(el.Id), "category": cat_name},
                    )
                )
            except Exception:
                errors += 1
                logger.exception("skipping device element that failed extraction")
                continue

    logger.info(
        "extract_devices: %d device(s); skipped %d (un-exported level), %d (no "
        "location); %d element error(s)",
        len(devices),
        skipped_level,
        skipped_location,
        errors,
    )
    if stats is not None:
        stats["devices"] = len(devices)
        stats["skipped_level"] = skipped_level
        stats["skipped_location"] = skipped_location
        stats["errors"] = errors
    return devices
