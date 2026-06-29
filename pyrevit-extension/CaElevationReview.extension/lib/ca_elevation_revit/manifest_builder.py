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

import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

SCHEMA_VERSION = "1.0.0"

_VALID_UNITS = ("feet", "meters")

# Mirrors spec_manifest.schema.json -> $defs.device.properties (additionalProperties:false).
# Pinned here to keep manifest_builder engine-import-free. Case 13b (engine-tier)
# asserts this set EQUALS the schema's device property keys so drift is caught.
_DEVICE_KEYS = frozenset(
    {
        "id",
        "family",
        "type",
        "level_id",
        "elevation_id",
        "position",
        "mounting_height",
        "orientation",
        "tolerances",
        "metadata",
    }
)
_TOLERANCE_KEYS = frozenset({"position", "mounting_height", "orientation"})

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


def _require_positive_int(value, what):  # noqa: ANN001
    # bool is an int subclass: reject it explicitly so True/False cannot pass.
    # Do NOT reject integer-valued floats here -- the schema accepts 1000.0 for
    # "type: integer", so rejecting a float instance would make the builder
    # STRICTER than the schema (forbidden -- see the subset invariant).
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestBuildError(f"{what} must be a positive integer, got {value!r}")


def _require_positive_number(value, what):  # noqa: ANN001
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ManifestBuildError(f"{what} must be a positive number, got {value!r}")


def _require_finite(value, what):  # noqa: ANN001
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ManifestBuildError(f"{what} must be a finite number, got {value!r}")


def _validate_tolerances(tolerances: dict, what: str) -> None:
    """Reject unknown tolerance keys / non-positive values (schema subset)."""
    for key, value in tolerances.items():
        if key not in _TOLERANCE_KEYS:
            raise ManifestBuildError(
                f"unknown tolerance key {key!r} in {what} (allowed: {sorted(_TOLERANCE_KEYS)})"
            )
        _require_positive_number(value, f"{what} tolerance {key!r}")


def _validate_project(project: dict) -> None:
    """Require id (non-empty str), name (str), units in the enum (schema subset)."""
    pid = project.get("id")
    if not isinstance(pid, str) or not pid.strip():
        raise ManifestBuildError("project id must be a non-empty string")
    if not isinstance(project.get("name"), str):
        raise ManifestBuildError("project name must be a string")
    if project.get("units") not in _VALID_UNITS:
        raise ManifestBuildError(
            f"project units must be one of {_VALID_UNITS}, got {project.get('units')!r}"
        )


def _validate_device_dict(d: dict) -> None:
    """Reject unknown device keys, bad position shape, non-finite coords (schema subset)."""
    for key in d:
        if key not in _DEVICE_KEYS:
            raise ManifestBuildError(
                f"unknown device key {key!r} in device {d.get('id')!r} "
                f"(allowed: {sorted(_DEVICE_KEYS)})"
            )
    position = d.get("position")
    if not isinstance(position, dict) or set(position) != {"x", "y", "z"}:
        raise ManifestBuildError(
            f"device {d.get('id')!r} position must be a dict with exactly x/y/z, got {position!r}"
        )
    for axis in ("x", "y", "z"):
        _require_finite(position[axis], f"device {d.get('id')!r} position[{axis!r}]")
    tolerances = d.get("tolerances")
    if tolerances is not None:
        if not isinstance(tolerances, dict):
            raise ManifestBuildError(f"device {d.get('id')!r} tolerances must be a dict")
        _validate_tolerances(tolerances, f"device {d.get('id')!r}")


def _level_dict(fp: FloorplanExport) -> dict:
    if len(list(fp.pixel_to_model)) != 6:
        raise ManifestBuildError(f"level {fp.level_id!r} pixel_to_model must have 6 elements")
    _require_positive_int(fp.width_px, f"level {fp.level_id!r} width_px")
    _require_positive_int(fp.height_px, f"level {fp.level_id!r} height_px")
    for i, v in enumerate(fp.pixel_to_model):
        _require_finite(v, f"level {fp.level_id!r} pixel_to_model[{i}]")
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

    _validate_project(project)

    if default_tolerances is not None:
        _validate_tolerances(default_tolerances, "default_tolerances")

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
        _validate_device_dict(d)

    seen_basenames = set()
    seen_level_ids = set()
    for fp in floorplans:
        if fp.basename in seen_basenames:
            raise ManifestBuildError(
                f"duplicate floorplan basename {fp.basename!r}: each level's image must be a "
                "distinct relative path (else bundle_io overwrites one and a level "
                "references the wrong floorplan)"
            )
        seen_basenames.add(fp.basename)
        if fp.level_id in seen_level_ids:
            raise ManifestBuildError(f"duplicate level id: {fp.level_id!r}")
        seen_level_ids.add(fp.level_id)

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
    for axis in ("x", "y", "z"):
        _require_finite(position[axis], f"device {unique_id!r} position[{axis!r}]")
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
