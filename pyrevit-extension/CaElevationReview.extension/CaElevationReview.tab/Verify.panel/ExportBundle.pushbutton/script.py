#! python3
"""Export a field bundle (spec manifest + floorplans) for the iPhone app.

Thin entry point: pull the Revit context from pyRevit globals, call the pure
lib + the LIVE revit_* stubs, write the bundle. All analysis lives in the engine;
all real logic lives in ca_elevation_revit.
"""

import sys

# In-Revit floor guard. pyRevit's `#! python3` shebang selects the CPython engine,
# but a known 6.0.0 routing defect (#3092) can run a shebanged script under
# IronPython anyway. Our whole correctness argument assumes CPython >= 3.8, so
# fail loudly rather than hit silent stdlib/subprocess differences.
if sys.implementation.name != "cpython" or sys.version_info < (3, 8):
    _msg = "CA Elevation Review requires the pyRevit CPython engine (3.8+)."
    try:
        from pyrevit import forms

        forms.alert(_msg, exitscript=True)
    except Exception:
        raise SystemExit(_msg)

from pyrevit import forms, revit, script  # noqa: E402

from ca_elevation_revit import (  # noqa: E402
    bundle_io,
    manifest_builder,
    revit_export,
    revit_extract,
)

logger = script.get_logger()


def main():
    doc = revit.doc

    # LIVE (Ed's hardware): walk the model + export floorplans.
    project = revit_extract.extract_project(doc)
    floorplans = revit_export.export_floorplans(doc, level_ids=[])  # TODO: level picker UI
    devices = revit_extract.extract_devices(doc, level_lookup={})

    # PURE (CI-tested): assemble + write the bundle.
    manifest = manifest_builder.build_manifest(project, floorplans, devices)
    out_dir = forms.pick_folder(title="Choose an output folder for the field bundle")
    if not out_dir:
        return
    written = bundle_io.write_field_bundle(out_dir, manifest, floorplans)
    forms.alert("Wrote field bundle:\n{}".format(written["manifest"]))


main()
