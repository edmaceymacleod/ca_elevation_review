"""Regenerate the synthetic payloads + goldens for scenarios f02-f07.

Run from ``engine/`` as ``python -m fixtures.seeders.regen_goldens``. This is the
documented, explicit way to update goldens after an INTENTIONAL engine change.
Tests never import or call this module; they READ the committed goldens.

f01 is deliberately NOT listed here, so regen can never perturb its committed
payloads/golden.
"""

from __future__ import annotations

import importlib
import json

from ca_elevation_engine.pipeline import run_pipeline

from . import _common as c  # for GENERATED_AT and GOLDEN_DIR

# (module, slug, golden_filename) -- mirrors registry.SCENARIO_GOLDENS (new scenarios only).
SEEDERS = [
    (
        "fixtures.seeders.f02_multilevel_datum",
        "f02_multilevel_datum",
        "f02_multilevel_datum_verdict_report.json",
    ),
    (
        "fixtures.seeders.f03_tolerance_boundary",
        "f03_tolerance_boundary",
        "f03_tolerance_boundary_verdict_report.json",
    ),
    (
        "fixtures.seeders.f04_coverage_orientation",
        "f04_coverage_orientation",
        "f04_coverage_orientation_verdict_report.json",
    ),
    (
        "fixtures.seeders.f05_distinctions",
        "f05_distinctions",
        "f05_distinctions_verdict_report.json",
    ),
    ("fixtures.seeders.f06_device_wall", "f06_device_wall", "f06_device_wall_verdict_report.json"),
    (
        "fixtures.seeders.f07_empty_manifest",
        "f07_empty_manifest",
        "f07_empty_manifest_verdict_report.json",
    ),
]


def regen_one(module, slug, golden_name):
    mod = importlib.import_module(module)
    mpath, cpath = mod.write()  # writes payloads
    result = run_pipeline(mpath, cpath, generated_at=c.GENERATED_AT)  # validates output schema too
    data = result.report.to_dict()
    c.GOLDEN_DIR.joinpath(golden_name).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return slug


def main():
    for m, s, g in SEEDERS:
        print("regenerated", regen_one(m, s, g))


if __name__ == "__main__":
    main()
