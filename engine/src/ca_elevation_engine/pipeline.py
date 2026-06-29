"""End-to-end engine pipeline: manifest + capture -> verdict report.

Wires the stages described in design.md:

    1. Ingest     -- load + validate both payloads against their JSON schemas.
    2. Georeference (coarse) + optional refine -- register each shot.
    3. Locate + compare -- find each device, measure deltas.
    4. Verdict    -- apply the per-device tolerance ruleset.
    5. Emit       -- structured VerdictReport (+ optional rendered report).

The function is pure with respect to the filesystem unless ``out_dir`` is given,
in which case it writes ``verdict_report.json`` (always) and a rendered report
in the requested format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import ingest
from .compare import Match, match_all
from .models import (
    SCHEMA_VERSION,
    CapturePackage,
    SpecManifest,
    VerdictReport,
)
from .register import register_capture
from .verdict import classify_all


@dataclass
class PipelineResult:
    report: VerdictReport
    matches: list[Match]
    warnings: list[str] = field(default_factory=list)
    written: dict[str, str] = field(default_factory=dict)


def run_pipeline(
    manifest: SpecManifest | str | Path,
    capture: CapturePackage | str | Path,
    *,
    bundle_dir: str | None = None,
    generated_at: str | None = None,
    out_dir: str | Path | None = None,
    report_format: str = "pdf",
    validate: bool = True,
) -> PipelineResult:
    """Run the full verification pipeline.

    ``manifest`` and ``capture`` may be already-parsed models or paths to JSON
    files. ``generated_at`` is injected (not derived) so runs are reproducible
    and golden-comparable. If ``out_dir`` is set, writes ``verdict_report.json``
    and a rendered report.
    """
    if not isinstance(manifest, SpecManifest):
        manifest = ingest.load_manifest(manifest, validate=validate)
    if not isinstance(capture, CapturePackage):
        capture = ingest.load_capture(capture, validate=validate)

    warnings = ingest.check_compatible(manifest, capture)

    registrations = register_capture(manifest, capture, bundle_dir=bundle_dir)
    matches = match_all(manifest, capture, registrations)
    results = classify_all(matches, manifest)

    from . import __version__

    report = VerdictReport(
        schema_version=SCHEMA_VERSION,
        project_id=manifest.project.id,
        device_results=results,
        units=manifest.project.units,
        generated_at=generated_at,
        engine_version=__version__,
    )

    written: dict[str, str] = {}
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        from .report import render_report

        json_path = out / "verdict_report.json"
        render_report(report, manifest, capture, str(json_path), fmt="json")
        written["json"] = str(json_path)

        if report_format and report_format != "json":
            from .report import MissingPdfBackend

            fmt = report_format
            try:
                rendered = out / f"report.{fmt}"
                render_report(report, manifest, capture, str(rendered), fmt=fmt)
                written[fmt] = str(rendered)
            except MissingPdfBackend as exc:
                # Don't fail the run if the PDF backend is absent: fall back to a
                # self-contained HTML report and tell the caller why.
                warnings.append(f"{exc} Falling back to HTML report.")
                rendered = out / "report.html"
                render_report(report, manifest, capture, str(rendered), fmt="html")
                written["html"] = str(rendered)

    return PipelineResult(report=report, matches=matches, warnings=warnings, written=written)
