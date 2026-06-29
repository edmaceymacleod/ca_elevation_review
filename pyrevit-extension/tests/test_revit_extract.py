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
        self.Symbol = types.SimpleNamespace(
            Family=types.SimpleNamespace(Name="Fam"), Name="Type"
        )
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
