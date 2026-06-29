"""Command-line interface for the elevation verification engine.

This is the entry point the Revit add-in invokes out-of-process. Keep the
surface small and stable:

    ca-elevation run      --manifest M --capture C --out DIR [--format pdf|html|json]
    ca-elevation validate --manifest M [--capture C]
    ca-elevation schema   (spec_manifest|capture_package|verdict_report)

``run`` always writes ``DIR/verdict_report.json`` and (unless ``--format json``)
a rendered report, then prints a one-screen text summary to stdout. Exit code 0
on success, 1 on validation/usage error, 2 on unexpected failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from . import __version__
from .ingest import ValidationError, load_capture, load_manifest, load_schema


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ca-elevation",
        description="As-built elevation verification engine (CA Elevation Review).",
    )
    p.add_argument("--version", action="version", version=f"ca-elevation {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full verification pipeline")
    run.add_argument("--manifest", required=True, help="path to the spec manifest JSON")
    run.add_argument("--capture", required=True, help="path to the capture package JSON")
    run.add_argument("--out", required=True, help="output directory for the report")
    run.add_argument(
        "--format",
        default="pdf",
        choices=["pdf", "html", "json"],
        help="rendered report format (default pdf; verdict_report.json is always written). "
        "pdf needs the optional 'reportlab' backend and falls back to html if absent",
    )
    run.add_argument("--bundle-dir", default=None, help="root dir for referenced bundle assets")
    run.add_argument(
        "--generated-at",
        default=None,
        help="ISO timestamp to stamp into the report (for reproducible runs)",
    )
    run.add_argument("--no-validate", action="store_true", help="skip JSON-schema validation")
    run.add_argument("--quiet", action="store_true", help="suppress the text summary")

    val = sub.add_parser("validate", help="validate payloads against their schemas")
    val.add_argument("--manifest", required=True, help="path to the spec manifest JSON")
    val.add_argument("--capture", default=None, help="optional path to a capture package JSON")

    sch = sub.add_parser("schema", help="print a bundled JSON schema")
    sch.add_argument(
        "name",
        choices=["spec_manifest", "capture_package", "verdict_report"],
        help="which schema to print",
    )
    return p


def _cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import run_pipeline

    validate = not args.no_validate
    try:
        result = run_pipeline(
            args.manifest,
            args.capture,
            bundle_dir=args.bundle_dir,
            generated_at=args.generated_at,
            out_dir=args.out,
            report_format=args.format,
            validate=validate,
        )
    except (ValidationError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for kind, path in result.written.items():
        print(f"wrote {kind}: {path}", file=sys.stderr)

    if not args.quiet:
        from .report.text_summary import summarize

        print(summarize(result.report))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(args.manifest)
        print(f"manifest OK: {len(manifest.devices)} devices, {len(manifest.levels)} levels")
        if args.capture:
            capture = load_capture(args.capture)
            print(f"capture OK: {len(capture.shots)} shots")
            from .ingest import check_compatible

            for w in check_compatible(manifest, capture):
                print(f"warning: {w}", file=sys.stderr)
    except (ValidationError, FileNotFoundError) as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    print(json.dumps(load_schema(args.name), indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "schema":
            return _cmd_schema(args)
    except BrokenPipeError:  # pragma: no cover
        return 0
    except Exception as exc:  # pragma: no cover - last-resort guard
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
