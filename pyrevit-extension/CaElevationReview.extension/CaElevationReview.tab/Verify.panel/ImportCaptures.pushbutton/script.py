#! python3
"""Run the engine over a returned capture package and write verdicts back.

Invokes the out-of-process ``ca-elevation`` CLI (engine_runner), then colours the
model's devices by verdict (revit_writeback, idempotent). Stashes the rendered
report path for the Open Report button.
"""

import os
import sys
import tempfile

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

from ca_elevation_revit import engine_runner, revit_writeback, writeback  # noqa: E402

logger = script.get_logger()

# Where Open Report looks for the last rendered report path.
LAST_REPORT_STASH = os.path.join(tempfile.gettempdir(), "ca_elevation_last_report.txt")


def main():
    doc = revit.doc

    manifest_path = forms.pick_file(file_ext="json", title="Spec manifest JSON (from export)")
    if not manifest_path:
        return
    capture_path = forms.pick_file(file_ext="json", title="Capture package JSON (from the phone)")
    if not capture_path:
        return
    out_dir = forms.pick_folder(title="Output folder for the report")
    if not out_dir:
        return

    # Out-of-process engine run (PURE/CI-tested runner; engine never imported here).
    result = engine_runner.run_engine(manifest_path, capture_path, out_dir)
    if not result.ok:
        forms.alert(
            "Engine {}:\n{}".format(result.status, result.stderr or "(no detail)"),
            title="CA Elevation Review",
        )
        return

    # Stash the report path BEFORE the LIVE write-back, so Open Report works even
    # if apply_verdicts fails on Ed's hardware (the engine already succeeded).
    if result.report_path:
        try:
            with open(LAST_REPORT_STASH, "w", encoding="utf-8") as fh:
                fh.write(result.report_path)
        except OSError:
            logger.warning("could not stash report path")

    # PURE: decide colours; LIVE: apply them idempotently inside a transaction.
    overrides = writeback.overrides_for_report(result.report or {})
    applied = revit_writeback.apply_verdicts(doc, revit.active_view, overrides)

    summary = (result.report or {}).get("summary", {})
    forms.alert(
        "Applied {} verdicts.\n{}\nReport: {}".format(applied, summary, result.report_path),
        title="CA Elevation Review",
    )


main()
