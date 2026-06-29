#! python3
"""Open the most recently generated verification report (PDF, or HTML fallback)."""

import os
import sys
import tempfile

if sys.implementation.name != "cpython" or sys.version_info < (3, 8):
    _msg = "CA Elevation Review requires the pyRevit CPython engine (3.8+)."
    try:
        from pyrevit import forms

        forms.alert(_msg, exitscript=True)
    except Exception:
        raise SystemExit(_msg)

from pyrevit import forms  # noqa: E402

LAST_REPORT_STASH = os.path.join(tempfile.gettempdir(), "ca_elevation_last_report.txt")


def main():
    path = None
    if os.path.exists(LAST_REPORT_STASH):
        with open(LAST_REPORT_STASH, encoding="utf-8") as fh:
            path = fh.read().strip()
    if not path or not os.path.exists(path):
        path = forms.pick_file(file_ext="pdf", title="Open a verification report")
    if not path:
        return
    # Windows-only host (Revit); os.startfile opens with the default app.
    os.startfile(path)  # noqa: S606  # type: ignore[attr-defined]


main()
