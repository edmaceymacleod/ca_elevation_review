"""Field-bundle writer and capture-package reader. Pure stdlib.

``bundle_io`` is the **sole writer** of the field-bundle directory: it writes the
manifest JSON and each floorplan image's bytes at exactly the relative basename
that ``manifest_builder`` stamped into ``floorplan.image`` -- so the manifest dict
and the on-disk layout cannot diverge. It also reads back the capture package the
phone returns.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Sequence

from .manifest_builder import FloorplanExport

MANIFEST_FILENAME = "manifest.json"


class BundleReadError(ValueError):
    """Raised when a capture package on disk cannot be read/parsed."""


def write_field_bundle(
    out_dir: str,
    manifest: dict,
    floorplans: Sequence[FloorplanExport],
) -> Dict[str, str]:
    """Write the field bundle (manifest JSON + floorplan images) to ``out_dir``.

    Returns a map of what was written. Each image is written at the same relative
    basename the manifest references; a mismatch between the manifest's
    ``floorplan.image`` entries and the provided records raises.
    """
    os.makedirs(out_dir, exist_ok=True)

    manifest_basenames = {lv["floorplan"]["image"] for lv in manifest.get("levels", [])}
    export_basenames = {fp.basename for fp in floorplans}
    if manifest_basenames != export_basenames:
        raise ValueError(
            "manifest floorplan images do not match provided records: "
            f"{sorted(manifest_basenames)} vs {sorted(export_basenames)}"
        )

    written: Dict[str, str] = {}
    manifest_path = os.path.join(out_dir, MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    written["manifest"] = manifest_path

    base = os.path.abspath(out_dir)
    images: List[str] = []
    for fp in floorplans:
        # basename is a relative path; guard against escaping out_dir. Reject
        # absolute paths and any traversal that lands outside the bundle dir
        # (commonpath is the sound containment check; startswith(os.pardir) is not).
        if os.path.isabs(fp.basename):
            raise ValueError(f"floorplan basename must be relative: {fp.basename!r}")
        dest = os.path.normpath(os.path.join(base, fp.basename))
        try:
            contained = os.path.commonpath([base, dest]) == base
        except ValueError:  # different drives on Windows
            contained = False
        if not contained:
            raise ValueError(f"floorplan basename escapes the bundle dir: {fp.basename!r}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(fp.image_bytes)
        images.append(dest)
    written["images"] = os.pathsep.join(images)
    return written


def read_capture_package(path: str) -> dict:
    """Read and parse a returned capture-package JSON file.

    Raises :class:`BundleReadError` on a missing file, malformed JSON, or a
    top-level value that is not a JSON object. Does NOT schema-validate -- that
    is the engine's job; this seam is JSON-safe, not schema-aware.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise BundleReadError(f"capture package not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BundleReadError(f"capture package is not valid JSON ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise BundleReadError(
            f"capture package must be a JSON object, got {type(data).__name__}: {path}"
        )
    return data
