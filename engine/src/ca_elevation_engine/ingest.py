"""Ingest and validate the two engine inputs.

Loads the spec manifest and capture package from JSON, validates each against
its JSON Schema (fail-closed), and returns typed models. Also performs
cross-payload checks (matching project id, referenced levels exist) that the
schemas alone cannot express.

This is the only module that reads the wire JSON; everything downstream works
with the typed models from :mod:`ca_elevation_engine.models`.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema

from .models import CapturePackage, SpecManifest

_SCHEMA_FILES = {
    "spec_manifest": "spec_manifest.schema.json",
    "capture_package": "capture_package.schema.json",
    "verdict_report": "verdict_report.schema.json",
}


class ValidationError(ValueError):
    """Raised when a payload fails schema or cross-payload validation."""


@cache
def load_schema(name: str) -> dict[str, Any]:
    """Load a bundled JSON Schema by short name (e.g. ``spec_manifest``)."""
    if name not in _SCHEMA_FILES:
        raise KeyError(f"unknown schema {name!r}; known: {sorted(_SCHEMA_FILES)}")
    pkg = resources.files("ca_elevation_engine.schemas")
    text = (pkg / _SCHEMA_FILES[name]).read_text(encoding="utf-8")
    return json.loads(text)


def _validate(instance: dict[str, Any], schema_name: str) -> None:
    schema = load_schema(schema_name)
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        lines = []
        for err in errors[:20]:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            lines.append(f"  at {loc}: {err.message}")
        more = "" if len(errors) <= 20 else f"\n  ... and {len(errors) - 20} more"
        raise ValidationError(
            f"{schema_name} failed schema validation:\n" + "\n".join(lines) + more
        )


def _read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{p} is not valid JSON: {exc}") from exc


def parse_manifest(data: dict[str, Any], *, validate: bool = True) -> SpecManifest:
    """Validate (optional) and parse a manifest dict into a :class:`SpecManifest`."""
    if validate:
        _validate(data, "spec_manifest")
    manifest = SpecManifest.from_dict(data)
    _check_manifest_internal(manifest)
    return manifest


def parse_capture(data: dict[str, Any], *, validate: bool = True) -> CapturePackage:
    """Validate (optional) and parse a capture dict into a :class:`CapturePackage`."""
    if validate:
        _validate(data, "capture_package")
    return CapturePackage.from_dict(data)


def load_manifest(path: str | Path, *, validate: bool = True) -> SpecManifest:
    """Load and validate a spec manifest from a JSON file."""
    return parse_manifest(_read_json(path), validate=validate)


def load_capture(path: str | Path, *, validate: bool = True) -> CapturePackage:
    """Load and validate a capture package from a JSON file."""
    return parse_capture(_read_json(path), validate=validate)


def _check_manifest_internal(manifest: SpecManifest) -> None:
    """Cross-field checks the schema cannot express."""
    level_ids = {lv.id for lv in manifest.levels}
    if len(level_ids) != len(manifest.levels):
        raise ValidationError("duplicate level ids in manifest")
    device_ids = [d.id for d in manifest.devices]
    if len(set(device_ids)) != len(device_ids):
        dupes = sorted({i for i in device_ids if device_ids.count(i) > 1})
        raise ValidationError(f"duplicate device ids in manifest: {dupes}")
    for d in manifest.devices:
        if d.level_id not in level_ids:
            raise ValidationError(f"device {d.id!r} references unknown level_id {d.level_id!r}")


def check_compatible(manifest: SpecManifest, capture: CapturePackage) -> list[str]:
    """Return a list of non-fatal compatibility warnings between the two payloads.

    Raises :class:`ValidationError` only on hard mismatches (project id, a shot
    targeting a level absent from the manifest).
    """
    warnings: list[str] = []
    if capture.project_id != manifest.project.id:
        raise ValidationError(
            f"capture project_id {capture.project_id!r} does not match "
            f"manifest project.id {manifest.project.id!r}"
        )
    level_ids = {lv.id for lv in manifest.levels}
    for shot in capture.shots:
        if shot.level_id not in level_ids:
            raise ValidationError(f"shot {shot.id!r} targets unknown level_id {shot.level_id!r}")
    covered_levels = {s.level_id for s in capture.shots}
    uncovered = sorted(level_ids - covered_levels)
    if uncovered:
        warnings.append(f"levels with no capture coverage: {', '.join(uncovered)}")
    return warnings
