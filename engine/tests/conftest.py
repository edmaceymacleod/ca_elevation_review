"""Shared pytest fixtures: paths to the immutable seeded fixtures.

Tests READ these; they never write to the ``fixtures/`` tree (the design doc's
fixture-as-single-source-of-truth rule).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ENGINE_ROOT / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def f01_manifest_path() -> Path:
    return FIXTURES / "synthetic" / "f01_office.manifest.json"


@pytest.fixture(scope="session")
def f01_capture_path() -> Path:
    return FIXTURES / "synthetic" / "f01_office.capture.json"


@pytest.fixture(scope="session")
def f01_golden() -> dict:
    return json.loads((FIXTURES / "golden" / "f01_verdict_report.json").read_text())
