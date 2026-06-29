"""Assemble a spec-manifest dict from extracted Revit values. Pure stdlib.

Input: plain device dicts (from ``revit_extract``) + per-level floorplan records
(from ``revit_export``). Output: a dict matching
``engine/src/ca_elevation_engine/schemas/spec_manifest.schema.json``. No Revit
API, no engine import -- correctness is proven at test time by importing the
engine and round-tripping through ``SpecManifest.from_dict`` + schema validate
(the engine-tier test).

This module is the single place the floorplan **relative path** is decided: it
writes ``floorplan.image`` as the export record's basename, and ``bundle_io``
writes the image bytes at exactly that basename -- so the dict and the on-disk
layout cannot diverge (the engine never ``stat``s the image, so a mismatch would
surface only late, at register/render).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

SCHEMA_VERSION = "1.0.0"

# Carried over verbatim from the C# SpecManifestExtractor so the pyRevit front
# door applies the SAME verdict thresholds as the C# one. These intentionally
# DIFFER from the engine's own fallback (0.083 / 0.042 / 10.0), which the engine
# applies only when a manifest omits default_tolerances -- a literal port that
# dropped these would silently change thresholds. Pinned as a golden in tests.
DEFAULT_TOLERANCES: Dict[str, float] = {
    "position": 0.25,
    "mounting_height": 0.083,
    "orientation": 10.0,
}


@dataclass
class FloorplanExport:
    """A floorplan exported for one level (produced by ``revit_export``).

    Carries the image **bytes** plus a stable **basename** (the relative path the
    manifest will reference and ``bundle_io`` will write to), and the dimensions
    + 6-element ``pixel_to_model`` affine the schema requires.
    """

    level_id: str
    level_name: str
    elevation: float
    image_bytes: bytes
    basename: str
    width_px: int
    height_px: int
    pixel_to_model: Sequence[float]  # 6 elements [a,b,c,d,e,f]


class ManifestBuildError(ValueError):
    """Raised when inputs cannot form a schema-valid manifest."""


def _level_dict(fp: FloorplanExport) -> dict:
    if len(list(fp.pixel_to_model)) != 6:
        raise ManifestBuildError(f"level {fp.level_id!r} pixel_to_model must have 6 elements")
    return {
        "id": fp.level_id,
        "name": fp.level_name,
        "elevation": float(fp.elevation),
        "floorplan": {
            "image": fp.basename,  # the single place the relative path is decided
            "width_px": int(fp.width_px),
            "height_px": int(fp.height_px),
            "pixel_to_model": [float(v) for v in fp.pixel_to_model],
        },
    }


def build_manifest(
    project: dict,
    floorplans: Sequence[FloorplanExport],
    devices: Sequence[dict],
    *,
    default_tolerances: Optional[Dict[str, float]] = None,
    coordinate_system: Optional[dict] = None,
) -> dict:
    """Build a spec-manifest dict.

    ``project`` must carry at least ``id``/``name``/``units``. ``devices`` are
    already-shaped device dicts from ``revit_extract`` (their ``id`` MUST be the
    Revit ``UniqueId`` -- see the live-validation acceptance criterion). A
    device-only manifest is schema-INVALID (levels[].floorplan is required), so
    at least one floorplan record is required.
    """
    if not floorplans:
        raise ManifestBuildError(
            "at least one floorplan record is required (levels[].floorplan is "
            "schema-required); a device-only manifest is invalid"
        )

    seen_ids = set()
    for d in devices:
        did = d.get("id")
        if not isinstance(did, str) or not did.strip():
            raise ManifestBuildError(
                "every device needs a non-empty string id (the Revit UniqueId)"
            )
        if did in seen_ids:
            raise ManifestBuildError(f"duplicate device id: {did!r}")
        seen_ids.add(did)

    levels = [_level_dict(fp) for fp in floorplans]
    level_ids = {lv["id"] for lv in levels}
    for d in devices:
        if d.get("level_id") not in level_ids:
            raise ManifestBuildError(
                "device {!r} references unknown level_id {!r}".format(
                    d.get("id"), d.get("level_id")
                )
            )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "project": dict(project),
        "default_tolerances": dict(default_tolerances or DEFAULT_TOLERANCES),
        "levels": levels,
        "devices": [dict(d) for d in devices],
    }
    if coordinate_system:
        manifest["coordinate_system"] = dict(coordinate_system)
    return manifest


def device_dict(
    unique_id: str,
    family: str,
    type_name: str,
    level_id: str,
    position: Dict[str, float],
    *,
    elevation_id: Optional[str] = None,
    mounting_height: Optional[float] = None,
    orientation: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Shape one device dict (helper for ``revit_extract`` to call).

    ``unique_id`` MUST be the Revit ``UniqueId`` (stable GUID-like string), not
    the int ``ElementId`` -- write-back resolves elements by ``UniqueId``.
    """
    if not isinstance(unique_id, str) or not unique_id.strip():
        raise ManifestBuildError("device id must be a non-empty UniqueId string")
    d: dict = {
        "id": unique_id,
        "family": family,
        "type": type_name,
        "level_id": level_id,
        "position": {
            "x": float(position["x"]),
            "y": float(position["y"]),
            "z": float(position["z"]),
        },
    }
    if elevation_id is not None:
        d["elevation_id"] = elevation_id
    if mounting_height is not None:
        d["mounting_height"] = float(mounting_height)
    if orientation is not None:
        d["orientation"] = dict(orientation)
    if metadata:
        d["metadata"] = dict(metadata)
    return d
