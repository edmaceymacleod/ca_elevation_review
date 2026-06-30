"""FLOOR tier: revit_writeback marker + idempotency logic, with a stubbed Revit API.

revit_writeback does its Revit imports function-locally (``from Autodesk.Revit.DB
import ...``), so we inject a minimal fake ``Autodesk.Revit.DB`` module into
sys.modules and drive the pure marker/clear logic with fake elements. This covers
the two data-integrity fixes that do NOT need a live Revit:

  * a read-only Comments param means the override is applied but the marker is NOT
    written -- apply_verdicts must count + warn (idempotency is broken for it);
  * the marker encodes the view id, so clear_prior_overrides resets the override in
    the view it was applied in even when a DIFFERENT view is active (no orphaned
    stale colour).
"""

from __future__ import annotations

import logging
import sys
import types


# --------------------------------------------------------------------------- #
# Minimal fake Autodesk.Revit.DB injected before importing revit_writeback.
# --------------------------------------------------------------------------- #
class _BuiltInParameter:
    ALL_MODEL_INSTANCE_COMMENTS = "ALL_MODEL_INSTANCE_COMMENTS"


class _OverrideGraphicSettings:
    """Records the setters that were called (enough for _build_override)."""

    def __init__(self):
        self.calls = []

    def _rec(self, name):
        def _setter(*a):
            self.calls.append((name, a))

        return _setter

    def __getattr__(self, name):
        if name.startswith("Set"):
            return self._rec(name)
        raise AttributeError(name)


class _Color:
    def __init__(self, r, g, b):
        self.rgb = (r, g, b)


class _RevitElementId:
    """Stand-in for DB.ElementId so _compat.make_eid resolves a view by int id."""

    def __init__(self, value):
        self.Value = int(value)

    def __eq__(self, other):
        return getattr(other, "Value", object()) == self.Value

    def __hash__(self):
        return hash(self.Value)


class _Transaction:
    def __init__(self, doc, name):
        self.doc = doc
        self._started = False
        self._ended = False

    def Start(self):
        self._started = True
        self.doc.is_modifiable = True

    def Commit(self):
        self._ended = True
        self.doc.is_modifiable = False

    def RollBack(self):
        self._ended = True
        self.doc.is_modifiable = False

    def HasStarted(self):
        return self._started

    def HasEnded(self):
        return self._ended


class _FilteredElementCollector:
    """Unified fake collector: supports document-wide iteration + OfClass/OfCategory.

    Shared shape so test modules that each install a fake Autodesk.Revit.DB do not
    clobber one another regardless of import order.
    """

    def __init__(self, doc, view_id=None):
        self._doc = doc

    def WhereElementIsNotElementType(self):
        return self

    def OfClass(self, _cls):
        return iter([])  # no fill patterns -> _solid_fill_pattern_id returns None

    def OfCategory(self, _bic):
        return self

    def __iter__(self):
        return iter(self._doc.elements)


def _get_fake_db():
    """Get-or-create a shared fake Autodesk.Revit.DB module, then add our names."""
    existing = sys.modules.get("Autodesk.Revit.DB")
    if existing is not None:
        return existing
    autodesk = sys.modules.setdefault("Autodesk", types.ModuleType("Autodesk"))
    revit = sys.modules.setdefault("Autodesk.Revit", types.ModuleType("Autodesk.Revit"))
    db = types.ModuleType("Autodesk.Revit.DB")
    revit.DB = db
    autodesk.Revit = revit
    sys.modules["Autodesk.Revit.DB"] = db
    return db


def _install_fake_revit():
    db = _get_fake_db()
    db.BuiltInParameter = _BuiltInParameter
    db.OverrideGraphicSettings = _OverrideGraphicSettings
    db.Color = _Color
    db.Transaction = _Transaction
    db.FilteredElementCollector = _FilteredElementCollector
    db.FillPatternElement = object
    db.FillPatternTarget = types.SimpleNamespace(Drafting="Drafting")
    db.ElementId = _RevitElementId


_install_fake_revit()

from ca_elevation_revit import revit_writeback  # noqa: E402
from ca_elevation_revit.writeback import DeviceOverride  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake Revit elements / views / document.
# --------------------------------------------------------------------------- #
class _Eid:
    def __init__(self, value):
        self.Value = value

    def __eq__(self, other):
        return isinstance(other, _Eid) and other.Value == self.Value

    def __hash__(self):
        return hash(self.Value)


class _Param:
    def __init__(self, value="", read_only=False):
        self._value = value
        self.IsReadOnly = read_only

    def AsString(self):
        return self._value

    def Set(self, value):
        if self.IsReadOnly:
            raise AssertionError("Set() called on a read-only param")
        self._value = value


class _Element:
    def __init__(self, eid, comments_param):
        self.Id = _Eid(eid)
        self._comments = comments_param

    def get_Parameter(self, _bip):
        return self._comments


class _View:
    def __init__(self, view_id):
        self.Id = _Eid(view_id)
        self.overrides = {}  # element_int -> ogs

    def SetElementOverrides(self, el_id, ogs):
        self.overrides[el_id.Value] = ogs


class _Doc:
    def __init__(self, elements, views):
        self.elements = elements
        self._by_uid = {}
        self._views = {v.Id.Value: v for v in views}
        self.is_modifiable = False

    @property
    def IsModifiable(self):
        return self.is_modifiable

    def register_uid(self, uid, el):
        self._by_uid[uid] = el

    def GetElement(self, key):
        # apply_verdicts resolves devices by UniqueId (str); clear resolves views
        # by ElementId.
        if isinstance(key, str):
            return self._by_uid.get(key)
        return self._views.get(key.Value)


# --------------------------------------------------------------------------- #
# marker helper unit tests
# --------------------------------------------------------------------------- #
def test_stamp_marker_writes_view_scoped_token_and_returns_true():
    el = _Element(10, _Param(""))
    assert revit_writeback._stamp_marker(el, 42) is True
    assert revit_writeback._marked_view_int(el) == 42
    assert "[CAElev:42]" in el._comments.AsString()


def test_stamp_marker_preserves_existing_comment_text():
    el = _Element(10, _Param("user note"))
    revit_writeback._stamp_marker(el, 7)
    assert el._comments.AsString().startswith("user note")
    assert "[CAElev:7]" in el._comments.AsString()


def test_stamp_marker_readonly_returns_false_and_does_not_write():
    el = _Element(10, _Param("locked", read_only=True))
    assert revit_writeback._stamp_marker(el, 5) is False
    assert el._comments.AsString() == "locked"  # untouched
    assert revit_writeback._has_marker(el) is False


def test_stamp_marker_absent_param_returns_false():
    el = _Element(10, None)
    assert revit_writeback._stamp_marker(el, 5) is False


def test_strip_marker_leaves_user_text():
    el = _Element(10, _Param("user note [CAElev:7]"))
    revit_writeback._strip_marker(el)
    assert el._comments.AsString() == "user note"
    assert revit_writeback._has_marker(el) is False


def test_legacy_idless_marker_is_recognised():
    el = _Element(10, _Param("[CAElev]"))
    assert revit_writeback._has_marker(el) is True
    assert revit_writeback._marked_view_int(el) == -1  # legacy sentinel


# --------------------------------------------------------------------------- #
# apply_verdicts: read-only Comments -> applied but unmarked + warned
# --------------------------------------------------------------------------- #
def test_apply_verdicts_readonly_comments_is_applied_but_unmarked_and_warns(caplog):
    view = _View(view_id=100)
    writable = _Element(1, _Param(""))
    locked = _Element(2, _Param("", read_only=True))
    doc = _Doc(elements=[writable, locked], views=[view])
    doc.register_uid("uid-writable", writable)
    doc.register_uid("uid-locked", locked)

    overrides = [
        DeviceOverride("uid-writable", "pass", (1, 2, 3)),
        DeviceOverride("uid-locked", "absent", (4, 5, 6)),
    ]
    with caplog.at_level(logging.WARNING):
        applied = revit_writeback.apply_verdicts(doc, view, overrides)

    # Both colour overrides land (override targets the view, not Comments)...
    assert applied == 2
    assert view.overrides.get(1) is not None
    assert view.overrides.get(2) is not None
    # ...but only the writable element carries a marker; the locked one is
    # surfaced as unmarked (broken idempotency) rather than a clean apply.
    assert revit_writeback._has_marker(writable) is True
    assert revit_writeback._has_marker(locked) is False
    assert any("could not be marked" in r.message for r in caplog.records)


# --------------------------------------------------------------------------- #
# clear_prior_overrides: per-view clearing via the marker's recorded view
# --------------------------------------------------------------------------- #
def test_clear_resets_override_in_the_view_recorded_in_the_marker():
    # Element was coloured in View A (id 100) and marked [CAElev:100]; the active
    # view at clear time is View B (id 200). The stale colour must still be reset
    # in View A, not left orphaned.
    view_a = _View(view_id=100)
    view_b = _View(view_id=200)
    el = _Element(1, _Param("[CAElev:100]"))
    view_a.overrides[1] = object()  # a non-default override sitting in View A
    doc = _Doc(elements=[el], views=[view_a, view_b])

    cleared = revit_writeback.clear_prior_overrides(doc, view_b)

    assert cleared == 1
    # View A's override was reset (to the default OverrideGraphicSettings)...
    assert isinstance(view_a.overrides[1], _OverrideGraphicSettings)
    # ...and the marker stripped so the device is no longer claimed.
    assert revit_writeback._has_marker(el) is False


def test_clear_skips_unmarked_elements():
    view = _View(view_id=100)
    el = _Element(1, _Param("just a user comment"))
    doc = _Doc(elements=[el], views=[view])
    cleared = revit_writeback.clear_prior_overrides(doc, view)
    assert cleared == 0
    assert el._comments.AsString() == "just a user comment"


def test_clear_legacy_marker_uses_active_view():
    view = _View(view_id=100)
    el = _Element(1, _Param("[CAElev]"))  # legacy, no view id
    view.overrides[1] = object()
    doc = _Doc(elements=[el], views=[view])
    cleared = revit_writeback.clear_prior_overrides(doc, view)
    assert cleared == 1
    assert isinstance(view.overrides[1], _OverrideGraphicSettings)
    assert revit_writeback._has_marker(el) is False
