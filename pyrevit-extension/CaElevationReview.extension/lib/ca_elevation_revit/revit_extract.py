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

from typing import Dict, List


def extract_project(doc) -> dict:  # noqa: ANN001 - doc is a Revit Document
    """Build the manifest ``project`` block from the active document. LIVE."""
    # LIVE: requires Revit.
    from Autodesk.Revit.DB import DisplayUnitType  # noqa: F401  # type: ignore

    raise NotImplementedError(
        "LIVE: read doc.Title / project info / units from the Revit Document. "
        "Validate on Ed's hardware."
    )


def extract_devices(doc, level_lookup: Dict[int, str]) -> List[dict]:  # noqa: ANN001
    """Collect installed devices as shaped device dicts. LIVE.

    Identity invariant: stamp each element's **UniqueId** (stable GUID-like
    string) as the device id via ``manifest_builder.device_dict`` -- NOT the int
    ElementId. Write-back resolves elements by UniqueId, and the engine echoes the
    id through unchanged, so the wrong id passes every CI test yet resolves
    nothing live.
    """
    # LIVE: requires Revit.
    from Autodesk.Revit.DB import (  # noqa: F401  # type: ignore
        BuiltInCategory,
        FilteredElementCollector,
    )

    raise NotImplementedError(
        "LIVE: FilteredElementCollector over device categories; for each instance "
        "emit manifest_builder.device_dict(unique_id=el.UniqueId, family=..., "
        "type_name=..., level_id=..., position={x,y,z}, mounting_height=..., "
        "orientation=...). UniqueId is mandatory. Validate on Ed's hardware."
    )
