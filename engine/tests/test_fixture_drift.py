"""Headless drift guard for the committed fixtures.

Re-runs the seeders in-memory and asserts the bytes they (re)produce are
byte-identical to the committed manifest / capture / golden for every registered
scenario. This is the in-process twin of CI's ``regen_fixtures.py --check`` step,
so drift is caught even when the path-filter would not have triggered the
``schema`` job.

These tests READ the committed fixtures and a temp copy; they never mutate the
committed ``fixtures/`` tree (default mode of ``regenerate`` here is always
``check=True``; the only writes go to ``tmp_path``).
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ENGINE_ROOT / "fixtures"
TOOL_PATH = ENGINE_ROOT / "tools" / "regen_fixtures.py"


def _load_regen():
    spec = importlib.util.spec_from_file_location("regen_fixtures", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


regen_fixtures = _load_regen()


def test_committed_fixtures_match_seeders():
    from ca_elevation_engine import registry

    for scenario in registry.SCENARIOS:
        drift = regen_fixtures.regenerate(scenario, check=True)
        assert drift == [], f"{scenario} drifted from its seeder: {drift}"


def test_regen_check_main_exit_zero():
    assert regen_fixtures.main(["--check"]) == 0


def test_regen_detects_injected_drift(tmp_path):
    # Copy the real fixtures tree into tmp_path and corrupt one synthetic file.
    tmp_copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, tmp_copy)
    victim = tmp_copy / "synthetic" / "f01_office.capture.json"
    data = victim.read_bytes()
    victim.write_bytes(data[:-1] + b" " + data[-1:])  # mutate one byte (not the suffix)

    drift = regen_fixtures.regenerate("f01_synthetic_office", check=True, fixtures_root=tmp_copy)
    assert drift, "expected drift list to be non-empty"
    assert any("f01_office.capture.json" in m for m in drift)

    # main() against the tampered copy must fail closed (return 1).
    rc = regen_fixtures.main(["--check", "--fixtures-root", str(tmp_copy)])
    assert rc == 1


def test_seeder_golden_bytes_match_committed():
    from fixtures.seeders import f01_synthetic_office as seeder

    from ca_elevation_engine.report.json_report import render_json

    report = seeder.build_golden()
    produced = (render_json(report) + "\n").encode("utf-8")
    committed = (FIXTURES / "golden" / "f01_verdict_report.json").read_bytes()
    assert produced == committed


def test_synthetic_serialization_is_canonical():
    import json

    from fixtures.seeders import f01_synthetic_office as seeder

    from ca_elevation_engine.report.json_report import render_json

    # Synthetic payloads: authored-order, indent=2, NO trailing newline.
    for stem, builder in (
        ("f01_office.manifest.json", seeder.build_manifest),
        ("f01_office.capture.json", seeder.build_capture),
    ):
        committed = (FIXTURES / "synthetic" / stem).read_bytes()
        assert not committed.endswith(b"\n}\n"), f"{stem} should have no trailing newline"
        assert committed.endswith(b"}")
        round_trip = json.dumps(builder(), indent=2).encode("utf-8")
        assert round_trip == committed

    # Golden: key-sorted render_json + exactly one trailing newline.
    golden = (FIXTURES / "golden" / "f01_verdict_report.json").read_bytes()
    assert golden.endswith(b"}\n")
    assert not golden.endswith(b"}\n\n")
    produced = (render_json(seeder.build_golden()) + "\n").encode("utf-8")
    assert produced == golden


def test_generated_at_constants_agree():
    from fixtures.seeders import _common
    from fixtures.seeders import f01_synthetic_office as seeder

    # The integration test imports GENERATED_AT from _common; the f01 seeder
    # carries its own literal. They MUST agree so the seeder writes the golden the
    # integration test reproduces.
    assert seeder.GENERATED_AT == _common.GENERATED_AT
