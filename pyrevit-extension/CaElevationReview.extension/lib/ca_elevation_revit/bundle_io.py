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

    images: List[str] = []
    for fp in floorplans:
        # basename is a relative path; guard against escaping out_dir.
        dest = os.path.normpath(os.path.join(out_dir, fp.basename))
        if os.path.relpath(dest, out_dir).startswith(os.pardir):
            raise ValueError(f"floorplan basename escapes the bundle dir: {fp.basename!r}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(fp.image_bytes)
        images.append(dest)
    written["images"] = os.pathsep.join(images)
    return written


def read_capture_package(path: str) -> dict:
    """Read and parse a returned capture-package JSON file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
