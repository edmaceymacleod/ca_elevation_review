"""Unit coverage for validate_schemas.py hardenings.

Covers ``--strict-unknown`` (misnamed payloads become hard errors) and the
engine-optional registered-golden cross-check.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ENGINE_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ENGINE_ROOT / "src" / "ca_elevation_engine" / "schemas"
TOOL_PATH = ENGINE_ROOT / "tools" / "validate_schemas.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("validate_schemas", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_schemas = _load_tool()


@pytest.fixture
def schemas():
    loaded, errors = validate_schemas.compile_schemas(SCHEMAS_DIR, verbose=False)
    assert not errors, errors
    return loaded


def test_strict_unknown_fails_on_misnamed_payload(tmp_path, schemas):
    # A typo'd manifest ("manfest") matches no payload suffix.
    (tmp_path / "foo.manfest.json").write_text(json.dumps({"x": 1}), encoding="utf-8")

    _, errors_strict = validate_schemas.validate_fixtures(
        tmp_path, schemas, verbose=False, strict_unknown=True
    )
    assert any("manfest" in e for e in errors_strict)

    _, errors_lax = validate_schemas.validate_fixtures(
        tmp_path, schemas, verbose=False, strict_unknown=False
    )
    assert errors_lax == []


def test_orphan_golden_check_flags_missing_registered_golden(tmp_path):
    registry = pytest.importorskip("ca_elevation_engine").registry
    # Empty fixtures dir -> every registered golden is "missing".
    errors = validate_schemas.check_registered_goldens(tmp_path, verbose=False)
    assert errors, "expected missing-golden errors for an empty fixtures dir"
    some_golden = next(iter(registry.SCENARIO_GOLDENS.values()))
    assert any(some_golden in e for e in errors)


def test_orphan_golden_check_degrades_when_engine_absent(tmp_path, monkeypatch):
    # Simulate the engine being un-importable: the cross-check must degrade to a
    # NOTE (no errors), not crash.
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "ca_elevation_engine" or name.startswith("ca_elevation_engine."):
            raise ImportError("simulated: engine not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    errors = validate_schemas.check_registered_goldens(tmp_path, verbose=False)
    assert errors == []


def test_validate_main_exit_zero_on_repo():
    assert validate_schemas.main([]) == 0
    assert validate_schemas.main(["--strict-unknown"]) == 0
