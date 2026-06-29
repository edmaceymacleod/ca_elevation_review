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
if (
    getattr(sys, "implementation", None) is None  # IronPython 2.7 has no sys.implementation
    or sys.implementation.name != "cpython"
    or sys.version_info < (3, 8)
):
    _msg = "CA Elevation Review requires the pyRevit CPython engine (3.8+)."
    try:
        from pyrevit import forms

        forms.alert(_msg, exitscript=True)
    except Exception:
        raise SystemExit(_msg) from None

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

    # Level picker. Revit imports stay function-local so the module imports
    # cleanly under CPython in CI; the compat shim stringifies level ids the same
    # way revit_export / revit_extract do, so the three agree on level identity.
    from Autodesk.Revit.DB import FilteredElementCollector, Level

    from ca_elevation_revit._compat import eid_value, element_name

    levels = sorted(
        FilteredElementCollector(doc).OfClass(Level),
        key=lambda lv: lv.Elevation,
    )
    if not levels:
        forms.alert("No levels found in this model.", title="CA Elevation Review")
        return

    # SelectFromList shows strings, so keep a display-name -> Level map. Suffix the
    # element id when two levels share a name so the mapping stays one-to-one.
    name_to_level = {}
    for lv in levels:
        name = element_name(lv)
        if name in name_to_level:
            name = "{} (#{})".format(name, eid_value(lv.Id))
        name_to_level[name] = lv

    # Multiselect, every level checked by default; closing the dialog cancels.
    picked = forms.SelectFromList.show(
        [forms.TemplateListItem(name, checked=True) for name in name_to_level],
        title="Select levels to export",
        button_name="Export",
        multiselect=True,
    )
    if not picked:
        return  # user cancelled or selected nothing -> write nothing

    chosen_levels = [name_to_level[name] for name in picked]
    level_id_strs = [str(eid_value(lv.Id)) for lv in chosen_levels]
    level_lookup = {eid_value(lv.Id): str(eid_value(lv.Id)) for lv in chosen_levels}

    floorplans = revit_export.export_floorplans(doc, level_ids=level_id_strs)
    devices = revit_extract.extract_devices(doc, level_lookup=level_lookup)

    # PURE (CI-tested): assemble + write the bundle.
    manifest = manifest_builder.build_manifest(project, floorplans, devices)
    out_dir = forms.pick_folder(title="Choose an output folder for the field bundle")
    if not out_dir:
        return
    written = bundle_io.write_field_bundle(out_dir, manifest, floorplans)
    forms.alert("Wrote field bundle:\n{}".format(written["manifest"]))


main()
