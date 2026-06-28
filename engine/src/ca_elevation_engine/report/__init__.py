"""Report renderer sub-package for the elevation verification engine.

This is the "Emit" tail of the pipeline (design doc, "Engine pipeline" step 7):
turn a :class:`~ca_elevation_engine.models.VerdictReport` into an issuable
client deliverable. The public entry point is :func:`render_report`, which the
pipeline calls.

Dependency-light by design: the HTML renderer uses pure-Python string
templating from the stdlib only. ``jinja2`` is an OPTIONAL extra and is never
hard-required here, so reports render with just the stdlib plus the engine
installed.

Supported formats:

* ``"html"`` -- a self-contained single-file HTML report (inline CSS, no
  external assets).
* ``"json"`` -- the pretty-printed verdict report (the schema-validated wire
  shape), suitable for Revit write-back and archival.

The plaintext one-screen :func:`~.text_summary.summarize` is re-exported for
the CLI.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .html import render_html
from .json_report import render_json
from .text_summary import summarize

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import CapturePackage, SpecManifest, VerdictReport

__all__ = [
    "render_report",
    "render_html",
    "render_json",
    "summarize",
]

# Formats this renderer can emit.
SUPPORTED_FORMATS = ("html", "json")


def render_report(
    report: VerdictReport,
    manifest: SpecManifest,
    capture: CapturePackage,
    out_path: str,
    fmt: str = "html",
) -> str:
    """Render the verdict report to ``out_path``.

    Args:
        report: The verdict report to render.
        manifest: Spec manifest (used for project name, units, and to backfill
            device family/type when a result omits them).
        capture: Capture package (used for context such as shot count).
        out_path: Destination file path.
        fmt: Output format, one of ``{"html", "json"}``.

    Returns:
        The path written (``out_path``).

    For ``"json"`` the document is ``report.to_dict()`` pretty-printed.
    """
    fmt_norm = (fmt or "html").lower()
    if fmt_norm not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported report format {fmt!r}; expected one of {SUPPORTED_FORMATS}.")

    if fmt_norm == "json":
        content = render_json(report)
    else:
        content = render_html(report, manifest, capture)

    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    return out_path
