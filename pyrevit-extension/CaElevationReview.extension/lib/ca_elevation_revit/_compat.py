"""Cross-version Revit API compatibility shims for the LIVE revit_* modules.

Borrowed from Sterling Revit Tools (``Sterling.extension/lib/revit_compat.py``)
and trimmed to what the three Revit-touching modules here need. Keep this module
Revit-API-light: helpers accept already-fetched Revit objects and return plain
Python values, so the pure ones stay headlessly testable.

eid_value(element_id) -> int
    Revit 2025+ ships an ``ElementId`` whose ``.Value`` (Int64) is the canonical
    accessor; pre-2025 exposes ``.IntegerValue``. Both coexist in some builds, so
    prefer ``.Value`` and fall back to ``.IntegerValue``. Used to stringify level
    ids identically in ``revit_extract`` and ``revit_export``.

make_eid(value) -> ElementId
    Revit 2026 removed the ``ElementId(System.Int32)`` constructor; a bare
    ``DB.ElementId(python_int)`` then raises an overload-resolution ``TypeError``
    (Int64 / BuiltInParameter / BuiltInCategory all match). Force the Int64
    overload on R26+, plain int on R23-R25; the choice is probed once and cached.
"""


def eid_value(element_id):
    """Return the integer value of an ElementId across Revit versions.

    Prefers ``.Value`` (Revit 2025+); falls back to ``.IntegerValue``. Only a
    TypeError/AttributeError from coercing ``.Value`` is swallowed; anything else
    propagates.
    """
    if hasattr(element_id, "Value"):
        try:
            return int(element_id.Value)
        except (TypeError, AttributeError):
            pass  # .Value exists but is not coercible; fall back
    return int(element_id.IntegerValue)


def _probe_int64_eid(db):
    """True when ``DB.ElementId(python_int)`` is ambiguous (R26+)."""
    try:
        db.ElementId(1)
        return False
    except TypeError:
        return True


# None = not yet probed, True = force Int64 (R26+), False = plain int (R23-R25).
_USE_INT64_EID = None


def make_eid(value, _db=None, _int64=None):
    """Construct a ``DB.ElementId`` from a python int across Revit versions.

    ``_db`` / ``_int64`` are headless-test seams; production callers pass neither.
    """
    global _USE_INT64_EID
    if _db is None:
        from Autodesk.Revit import DB as _db
    if _USE_INT64_EID is None:
        _USE_INT64_EID = _probe_int64_eid(_db)
    if _USE_INT64_EID:
        if _int64 is None:
            from System import Int64 as _int64
        return _db.ElementId(_int64(value))
    return _db.ElementId(value)


def element_name(element):
    """Best-effort name of a Revit element, version/IronPython safe.

    IronPython 2.7 can shadow the ``Name`` property; CPython/pythonnet under
    pyRevit is fine with plain ``.Name``. Try the attribute, then the
    descriptor, then the built-in VIEW/SYMBOL name parameter, else ''.
    """
    try:
        name = getattr(element, "Name", None)
        if name:
            return name
    except Exception:
        pass
    try:
        from Autodesk.Revit import DB

        return DB.Element.Name.__get__(element)  # IronPython descriptor workaround
    except Exception:
        return ""
