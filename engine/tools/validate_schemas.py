#!/usr/bin/env python3
"""Validate the engine's JSON Schemas and any fixtures against them.

Realizes design principle #3 ("Schema / structure validation in CI"): a
malformed manifest, capture package, or verdict report fails the build rather
than the field.

What it does, fail-closed (exit 1 on any error):

1. Loads every ``*.schema.json`` under ``engine/src/ca_elevation_engine/schemas/``
   and confirms it compiles as a valid draft-07 JSON Schema.
2. Discovers fixture payloads under ``engine/fixtures/`` (recursively) and
   validates each against the matching schema, inferred from the filename:
       *.manifest.json  -> spec_manifest.schema.json
       *.capture.json   -> capture_package.schema.json
       *.report.json    -> verdict_report.schema.json
3. If no fixtures exist yet (Phase 0 bootstrap), validating the schemas alone
   is success -- the script is robust to fixtures not existing.

Usage:
    python engine/tools/validate_schemas.py [--schemas DIR] [--fixtures DIR]
        [--strict-unknown] [-v]

The schema/fixture-validation core stays engine-free (only ``jsonschema``); the
optional orphan-golden cross-check adds a guarded, best-effort ``registry`` import
used only when the engine is importable, degrading to a NOTE otherwise.

Exit codes:
    0  all schemas compile and all discovered fixtures validate
    1  a schema is invalid, a fixture fails validation, or no schemas found
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft7Validator
    from jsonschema.exceptions import SchemaError
except ImportError:  # pragma: no cover - jsonschema is a core dependency
    print("ERROR: jsonschema is not installed. Run: pip install -e 'engine[dev]'", file=sys.stderr)
    sys.exit(1)


def _jsonschema_version() -> str:
    try:
        from importlib.metadata import version

        return version("jsonschema")
    except Exception:  # pragma: no cover
        return "unknown"


# Maps a fixture filename suffix to the schema file that should validate it.
FIXTURE_SUFFIX_TO_SCHEMA = {
    ".manifest.json": "spec_manifest.schema.json",
    ".capture.json": "capture_package.schema.json",
    # The project's golden reports are named "<stem>_verdict_report.json"; the
    # plain ".report.json" alias is kept for any future report fixtures.
    "_verdict_report.json": "verdict_report.schema.json",
    ".report.json": "verdict_report.schema.json",
}

# Default locations relative to the repo root (this file is engine/tools/...).
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMAS_DIR = REPO_ROOT / "engine" / "src" / "ca_elevation_engine" / "schemas"
DEFAULT_FIXTURES_DIR = REPO_ROOT / "engine" / "fixtures"


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def compile_schemas(schemas_dir: Path, verbose: bool) -> tuple[dict[str, dict], list[str]]:
    """Load + validate every *.schema.json. Returns (by_filename, errors)."""
    errors: list[str] = []
    schemas: dict[str, dict] = {}

    schema_files = sorted(schemas_dir.glob("*.schema.json"))
    if not schema_files:
        errors.append(f"no *.schema.json files found under {schemas_dir}")
        return schemas, errors

    for path in schema_files:
        try:
            schema = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: not valid JSON: {exc}")
            continue
        try:
            # Confirm the document is itself a valid draft-07 schema.
            Draft7Validator.check_schema(schema)
        except SchemaError as exc:
            errors.append(f"{path.name}: not a valid draft-07 JSON Schema: {exc.message}")
            continue
        schemas[path.name] = schema
        if verbose:
            print(f"  OK schema: {path.name}")

    return schemas, errors


def validate_fixtures(
    fixtures_dir: Path,
    schemas: dict[str, dict],
    verbose: bool,
    *,
    strict_unknown: bool = False,
) -> tuple[int, list[str]]:
    """Validate every recognised fixture under fixtures_dir. Returns (count, errors).

    When ``strict_unknown`` is True, any ``*.json`` matching no payload suffix
    becomes a hard error (so a typo'd ``f0x.manfest.json`` cannot silently escape
    validation) instead of only a NOTE. Default False = today's behavior.
    """
    errors: list[str] = []
    checked = 0
    skipped: list[Path] = []
    validated_schema_names: set[str] = set()

    if not fixtures_dir.exists():
        if verbose:
            print(f"  (no fixtures dir yet at {fixtures_dir}; skipping fixture validation)")
        return checked, errors

    for path in sorted(fixtures_dir.rglob("*.json")):
        schema_name = next(
            (s for suffix, s in FIXTURE_SUFFIX_TO_SCHEMA.items() if path.name.endswith(suffix)),
            None,
        )
        if schema_name is None:
            # Not a recognised payload (e.g. an asset sidecar). Don't fail, but
            # surface it so a misnamed payload (a typo'd manifest/capture/report)
            # can't escape validation silently.
            skipped.append(path)
            continue
        schema = schemas.get(schema_name)
        if schema is None:
            errors.append(f"{path}: needs {schema_name} but that schema was not loaded")
            continue
        try:
            instance = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: not valid JSON: {exc}")
            continue

        validator = Draft7Validator(schema)
        found = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if found:
            for err in found:
                loc = "/".join(str(p) for p in err.path) or "<root>"
                errors.append(f"{path} [{loc}]: {err.message}")
        else:
            checked += 1
            validated_schema_names.add(schema_name)
            if verbose:
                print(f"  OK fixture: {path.relative_to(fixtures_dir)} against {schema_name}")

    if skipped:
        rels = ", ".join(str(p.relative_to(fixtures_dir)) for p in skipped)
        if strict_unknown:
            errors.append(
                f"{len(skipped)} *.json file(s) matched no payload suffix "
                f"(--strict-unknown): {rels}"
            )
        else:
            print(
                f"  NOTE: {len(skipped)} *.json file(s) matched no payload suffix, "
                f"not validated: {rels}"
            )

    # Fail loudly if a report fixture exists but the report schema validated none
    # of them -- catches a future rename quietly dropping the golden from coverage.
    report_files = [
        p
        for p in fixtures_dir.rglob("*.json")
        if p.name.endswith(("_verdict_report.json", ".report.json"))
    ]
    if report_files and "verdict_report.schema.json" not in validated_schema_names:
        names = [str(p.name) for p in report_files]
        errors.append(
            f"found report fixtures {names} but none validated against "
            "verdict_report.schema.json (suffix-map drift?)"
        )

    return checked, errors


def check_registered_goldens(fixtures_dir: Path, verbose: bool) -> list[str]:
    """Best-effort, engine-OPTIONAL cross-check: every registered golden exists.

    Attempts ``from ca_elevation_engine import registry``. If it imports, assert
    every golden filename in ``registry.SCENARIO_GOLDENS.values()`` exists
    somewhere under ``fixtures_dir`` -- catching a deleted/renamed golden that the
    registry still references. If the import fails (standalone run, engine not
    installed), print a NOTE and return no errors (degrade gracefully).

    Scope is deliberately "golden exists" only -- NOT "a matching manifest/capture
    exists" -- because the registry maps scenario -> golden_filename and the
    generic input-match is not derivable from that data model.
    """
    try:
        from ca_elevation_engine import registry
    except ImportError:
        print("  NOTE: engine not importable; skipped registered-golden cross-check")
        return []

    present = {p.name for p in fixtures_dir.rglob("*.json")} if fixtures_dir.exists() else set()
    errors: list[str] = []
    for golden_name in registry.SCENARIO_GOLDENS.values():
        if golden_name not in present:
            errors.append(
                f"registered golden {golden_name!r} not found under {fixtures_dir} "
                "(deleted/renamed?)"
            )
        elif verbose:
            print(f"  OK registered golden present: {golden_name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--schemas", type=Path, default=DEFAULT_SCHEMAS_DIR, help="directory of *.schema.json files"
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
        help="directory of fixture JSON payloads",
    )
    parser.add_argument(
        "--strict-unknown",
        action="store_true",
        help="treat any *.json that matches no payload suffix as a hard error",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print each file checked")
    args = parser.parse_args(argv)

    print(f"jsonschema {_jsonschema_version()}")
    print(f"Validating schemas in {args.schemas}")
    schemas, schema_errors = compile_schemas(args.schemas, args.verbose)

    fixture_count = 0
    fixture_errors: list[str] = []
    orphan_errors: list[str] = []
    if not schema_errors:
        print(f"Validating fixtures in {args.fixtures}")
        fixture_count, fixture_errors = validate_fixtures(
            args.fixtures, schemas, args.verbose, strict_unknown=args.strict_unknown
        )
        print("Cross-checking registered goldens")
        orphan_errors = check_registered_goldens(args.fixtures, args.verbose)

    all_errors = schema_errors + fixture_errors + orphan_errors
    print()
    print(f"Schemas compiled: {len(schemas)}")
    print(f"Fixtures validated: {fixture_count}")

    if all_errors:
        print(f"\nFAILED with {len(all_errors)} error(s):", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("\nAll schemas and fixtures valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
