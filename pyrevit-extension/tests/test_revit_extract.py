"""FLOOR tier: revit_extract.extract_devices error/stats surfacing (stubbed Revit).

extract_devices wraps each element in a broad ``except Exception`` that counts and
logs, so a device that raises mid-extraction is dropped from the returned list. The
fix surfaces the per-walk tallies via an optional ``stats`` out-dict (and keeps the
``List[dict]`` return) so the caller can warn the user that the review is
incomplete. We drive that with a minimal fake Autodesk.Revit.DB.
"""

from __future__ import annotations

import logging
import sys
import types


# --------------------------------------------------------------------------- #
# Minimal fake Autodesk.Revit.DB for extract_devices' function-local imports.
# --------------------------------------------------------------------------- #
class _BuiltInCategory:
    # Only one category resolves; the rest are absent (getattr -> None -> skipped).
    OST_SecurityDevices = "OST_SecurityDevices"


class _BuiltInParameter:
    pass  # level-param fallbacks resolve to None via getattr -> skipped


class _FilteredElementCollector:
    """Unified fake collector (same shape as the writeback test's, order-safe)."""

    def __init__(self, doc, view_id=None):
        self._doc = doc

    def OfCategory(self, _bic):
        return self

    def OfClass(self, _cls):
        return iter([])

    def WhereElementIsNotElementType(self):
        return self

    def __iter__(self):
        return iter(self._doc.elements)


def _install_fake_revit():
    existing = sys.modules.get("Autodesk.Revit.DB")
    if existing is None:
        autodesk = sys.modules.setdefault("Autodesk", types.ModuleType("Autodesk"))
        revit = sys.modules.setdefault("Autodesk.Revit", types.ModuleType("Autodesk.Revit"))
        existing = types.ModuleType("Autodesk.Revit.DB")
        revit.DB = existing
        autodesk.Revit = revit
        sys.modules["Autodesk.Revit.DB"] = existing
    existing.BuiltInCategory = _BuiltInCategory
    # Only add names this module needs if a sibling test has not already provided a
    # richer version (e.g. BuiltInParameter with ALL_MODEL_INSTANCE_COMMENTS).
    if not hasattr(existing, "BuiltInParameter"):
        existing.BuiltInParameter = _BuiltInParameter
    if not hasattr(existing, "FilteredElementCollector"):
        existing.FilteredElementCollector = _FilteredElementCollector


_install_fake_revit()

from ca_elevation_revit import revit_extract  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake Revit elements.
# --------------------------------------------------------------------------- #
class _Eid:
    def __init__(self, value):
        self.Value = value


class _Loc:
    def __init__(self, x, y, z):
        self.Point = types.SimpleNamespace(X=x, Y=y, Z=z)


class _GoodElement:
    def __init__(self, uid, level_int, eid=1):
        self.UniqueId = uid
        self.Id = _Eid(eid)
        self.LevelId = _Eid(level_int)
        self.Location = _Loc(1.0, 2.0, 3.0)
        self.Name = "Device"
        self.Symbol = types.SimpleNamespace(Family=types.SimpleNamespace(Name="Fam"), Name="Type")
        self.FacingOrientation = None


class _RaisingElement:
    """Raises when its UniqueId is read -- a transient mid-extraction failure."""

    @property
    def UniqueId(self):
        raise RuntimeError("transient API error reading UniqueId")


class _Doc:
    def __init__(self, elements):
        self.elements = elements


def test_extract_devices_surfaces_error_count_in_stats(caplog):
    # One good device + one element that raises mid-extraction (dropped). The good
    # device is returned; the drop is counted in stats["errors"] so the caller can
    # warn the user the review is incomplete.
    doc = _Doc([_GoodElement("uid-good", level_int=7, eid=1), _RaisingElement()])
    level_lookup = {7: "L7"}
    stats = {}
    with caplog.at_level(logging.ERROR):
        devices = revit_extract.extract_devices(doc, level_lookup, stats=stats)

    assert [d["id"] for d in devices] == ["uid-good"]
    assert stats["devices"] == 1
    assert stats["errors"] == 1
    assert stats["skipped_level"] == 0
    # The drop was logged (logger.exception -> ERROR record).
    assert any("failed extraction" in r.message for r in caplog.records)


def test_extract_devices_stats_optional_backward_compatible():
    # Without a stats dict the return is still a plain List[dict] (caller signature
    # unchanged).
    doc = _Doc([_GoodElement("uid-good", level_int=7, eid=1)])
    devices = revit_extract.extract_devices(doc, {7: "L7"})
    assert [d["id"] for d in devices] == ["uid-good"]


def test_extract_devices_counts_skipped_level():
    doc = _Doc([_GoodElement("uid-x", level_int=99, eid=2)])
    stats = {}
    devices = revit_extract.extract_devices(doc, {7: "L7"}, stats=stats)
    assert devices == []
    assert stats["skipped_level"] == 1
    assert stats["errors"] == 0


# --------------------------------------------------------------------------- #
# T3.4: curve/line fallback + position-source tagging fakes.
# --------------------------------------------------------------------------- #
class _Pt:
    """A bare Revit XYZ-like point (has .X/.Y/.Z, nothing else)."""

    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class _Curve:
    """Fake Revit Curve: Evaluate(0.5, normalized=True) -> the midpoint."""

    def __init__(self, mid):
        self._mid = mid

    def Evaluate(self, parameter, normalized):
        assert normalized is True
        assert parameter == 0.5
        return self._mid


class _RaisingCurve:
    """Fake Curve whose Evaluate raises (degenerate/unsupported curve)."""

    def Evaluate(self, parameter, normalized):
        raise RuntimeError("curve evaluation failed")


class _CurveLoc:
    """Location with a Curve and deliberately NO .Point (line/curve-based)."""

    def __init__(self, mid):
        self.Curve = _Curve(mid)


class _PointAndCurveLoc:
    """Location exposing BOTH a (possibly malformed) .Point and a .Curve."""

    def __init__(self, pt, mid):
        self.Point = pt
        self.Curve = _Curve(mid)


class _BBox:
    def __init__(self, mn, mx):
        self.Min, self.Max = mn, mx


class _BBoxOnlyElement:
    """No usable Location.Point and no Curve -> bbox-centre fallback."""

    def __init__(self, bbox):
        self._bbox = bbox
        self.Location = object()  # has neither .Point nor .Curve

    def get_BoundingBox(self, _view):
        return self._bbox


class _CurveAndBBoxElement:
    """Curve-based element whose curve raises on Evaluate; falls to bbox centre."""

    def __init__(self, curve, bbox):
        self.Location = types.SimpleNamespace(Curve=curve)
        self._bbox = bbox

    def get_BoundingBox(self, _view):
        return self._bbox


def test_xyz_to_dict_happy_path():
    assert revit_extract._xyz_to_dict(_Pt(1.0, 2.0, 3.0)) == {
        "x": 1.0,
        "y": 2.0,
        "z": 3.0,
    }


def test_xyz_to_dict_none_on_missing_coordinate():
    # The whole reason the helper returns Optional: a malformed point (missing .Z)
    # yields None so the resolver can fall through instead of aborting the device.
    assert revit_extract._xyz_to_dict(types.SimpleNamespace(X=1.0, Y=2.0)) is None


def test_xyz_to_dict_none_on_non_numeric_coordinate():
    assert revit_extract._xyz_to_dict(types.SimpleNamespace(X="a", Y=2.0, Z=3.0)) is None


def test_resolve_position_point_based_tagged_location_point():
    el = types.SimpleNamespace(Location=_Loc(1.0, 2.0, 3.0))
    assert revit_extract._resolve_position(el) == (
        {"x": 1.0, "y": 2.0, "z": 3.0},
        revit_extract.POSITION_SOURCE_LOCATION_POINT,
    )


def test_resolve_position_curve_based_uses_midpoint_tagged_curve_midpoint():
    el = types.SimpleNamespace(Location=_CurveLoc(_Pt(4.0, 6.0, 8.0)))
    assert revit_extract._resolve_position(el) == (
        {"x": 4.0, "y": 6.0, "z": 8.0},
        revit_extract.POSITION_SOURCE_CURVE_MIDPOINT,
    )


def test_resolve_position_malformed_point_falls_through_to_curve():
    # Point present but malformed (missing .Z) -> _xyz_to_dict None -> use curve.
    # Proves the point -> curve fall-through chain end to end.
    loc = _PointAndCurveLoc(types.SimpleNamespace(X=1.0, Y=2.0), _Pt(4.0, 6.0, 8.0))
    el = types.SimpleNamespace(Location=loc)
    assert revit_extract._resolve_position(el) == (
        {"x": 4.0, "y": 6.0, "z": 8.0},
        revit_extract.POSITION_SOURCE_CURVE_MIDPOINT,
    )


def test_resolve_position_curve_evaluate_raises_falls_back_to_bbox():
    # Curve present but Evaluate raises -> guarded except -> bbox-centre fallback.
    el = _CurveAndBBoxElement(_RaisingCurve(), _BBox(_Pt(0.0, 0.0, 0.0), _Pt(2.0, 4.0, 6.0)))
    assert revit_extract._resolve_position(el) == (
        {"x": 1.0, "y": 2.0, "z": 3.0},
        revit_extract.POSITION_SOURCE_BBOX_CENTRE,
    )


def test_resolve_position_falls_back_to_bbox_centre_tagged_bbox_centre():
    el = _BBoxOnlyElement(_BBox(_Pt(0.0, 0.0, 0.0), _Pt(2.0, 4.0, 6.0)))
    assert revit_extract._resolve_position(el) == (
        {"x": 1.0, "y": 2.0, "z": 3.0},
        revit_extract.POSITION_SOURCE_BBOX_CENTRE,
    )


def test_resolve_position_none_when_unlocatable():
    # Location with neither Point nor Curve, and get_BoundingBox absent (raises).
    el = types.SimpleNamespace(Location=object())
    assert revit_extract._resolve_position(el) is None


class _CurveElement:
    """Curve/line-based device: Location has a Curve, no Point (bbox-free)."""

    def __init__(self, uid, level_int, mid, eid=1):
        self.UniqueId = uid
        self.Id = _Eid(eid)
        self.LevelId = _Eid(level_int)
        self.Location = _CurveLoc(mid)
        self.Name = "CurveDevice"
        self.Symbol = types.SimpleNamespace(Family=types.SimpleNamespace(Name="Fam"), Name="Type")
        self.FacingOrientation = None


class _BBoxDeviceElement:
    """Full device whose Location has neither Point nor Curve -> bbox-centre."""

    def __init__(self, uid, level_int, bbox, eid=3):
        self.UniqueId = uid
        self.Id = _Eid(eid)
        self.LevelId = _Eid(level_int)
        self.Location = object()  # neither .Point nor .Curve
        self.Name = "BBoxDevice"
        self.Symbol = types.SimpleNamespace(Family=types.SimpleNamespace(Name="Fam"), Name="Type")
        self.FacingOrientation = None
        self._bbox = bbox

    def get_BoundingBox(self, _view):
        return self._bbox


class _MalformedPointDeviceElement:
    """Device whose Location.Point is malformed (non-numeric .X) and has no
    curve and no get_BoundingBox.

    Pre-T3.4 the unguarded ``float(pt.X)`` RAISED and the element was counted in
    stats['errors']. Post-T3.4 ``_xyz_to_dict`` swallows it, and with no
    curve/bbox the element resolves to None -> counted in skipped_location. This
    fake pins that deliberate, documented semantics change.
    """

    def __init__(self, uid, level_int, eid=4):
        self.UniqueId = uid
        self.Id = _Eid(eid)
        self.LevelId = _Eid(level_int)
        self.Location = types.SimpleNamespace(Point=types.SimpleNamespace(X="bad", Y=2.0, Z=3.0))
        self.Name = "BadPointDevice"
        self.Symbol = types.SimpleNamespace(Family=types.SimpleNamespace(Name="Fam"), Name="Type")
        self.FacingOrientation = None


def test_extract_devices_tags_point_based_position_source():
    doc = _Doc([_GoodElement("uid-good", level_int=7, eid=1)])
    devices = revit_extract.extract_devices(doc, {7: "L7"})
    assert devices[0]["position"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert devices[0]["metadata"]["position_source"] == (
        revit_extract.POSITION_SOURCE_LOCATION_POINT
    )


def test_extract_devices_curve_device_uses_midpoint_and_tags_source():
    doc = _Doc([_CurveElement("uid-curve", level_int=7, mid=_Pt(4.0, 6.0, 8.0), eid=2)])
    devices = revit_extract.extract_devices(doc, {7: "L7"})
    assert devices[0]["position"] == {"x": 4.0, "y": 6.0, "z": 8.0}
    assert devices[0]["metadata"]["position_source"] == (
        revit_extract.POSITION_SOURCE_CURVE_MIDPOINT
    )
    # element_id / category still present (no regression).
    assert devices[0]["metadata"]["element_id"] == 2
    assert devices[0]["metadata"]["category"] == "OST_SecurityDevices"


def test_extract_devices_bbox_fallback_tags_bbox_centre():
    # End-to-end: the residual bbox path is threaded through extract_devices into
    # metadata, not just covered at the unit level.
    doc = _Doc(
        [
            _BBoxDeviceElement(
                "uid-bbox",
                level_int=7,
                bbox=_BBox(_Pt(0.0, 0.0, 0.0), _Pt(2.0, 4.0, 6.0)),
                eid=3,
            )
        ]
    )
    devices = revit_extract.extract_devices(doc, {7: "L7"})
    assert devices[0]["position"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert devices[0]["metadata"]["position_source"] == (revit_extract.POSITION_SOURCE_BBOX_CENTRE)


def test_extract_devices_malformed_point_counted_skipped_location_not_errors():
    # Behavior-change contract: a malformed Location.Point with no curve/bbox is
    # now counted in skipped_location (NOT errors). Pre-T3.4 it raised inside
    # float(pt.X) and incremented stats['errors']. See PR body note.
    doc = _Doc([_MalformedPointDeviceElement("uid-bad", level_int=7, eid=4)])
    stats = {}
    devices = revit_extract.extract_devices(doc, {7: "L7"}, stats=stats)
    assert devices == []
    assert stats["skipped_location"] == 1
    assert stats["errors"] == 0
