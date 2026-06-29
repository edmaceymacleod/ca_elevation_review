"""Test fixtures + the engine-tier gate.

Two mechanisms live here:
  1. A ``sys.path`` insert for the extension ``lib/`` -- a robust fallback to the
     ``pythonpath`` in ``pyproject.toml`` so ``import ca_elevation_revit`` resolves
     however pytest is invoked.
  2. The structural engine-tier gate: ``@pytest.mark.engine`` tests are auto-skipped
     on Python < 3.10 (the floor jobs), where ``ca_elevation_engine`` is not
     installed. Engine-tier test MODULES must import the engine *inside* their test
     functions (never at module top) so collection itself does not fail on the
     floor jobs.
"""

from __future__ import annotations

import os
import sys

import pytest

# 1. Make the extension lib importable regardless of how pytest is invoked.
_LIB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "CaElevationReview.extension", "lib")
)
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

# Repo root (pyrevit-extension/tests -> pyrevit-extension -> repo).
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(scope="session")
def repo_root() -> str:
    return REPO_ROOT


@pytest.fixture(scope="session")
def engine_fixtures_dir(repo_root: str) -> str:
    """The engine's synthetic fixture dir, reached by repo-relative path.

    pip-installing the engine does NOT ship engine/fixtures/ (outside package-data),
    so the integration test reaches them this way -- not via importlib.resources.
    """
    return os.path.join(repo_root, "engine", "fixtures", "synthetic")


def pytest_collection_modifyitems(config, items):
    """Auto-skip engine-marked tests below Python 3.10 (the floor jobs)."""
    if sys.version_info >= (3, 10):
        return
    skip = pytest.mark.skip(reason="requires ca_elevation_engine (Python 3.10+ jobs only)")
    for item in items:
        if "engine" in item.keywords:
            item.add_marker(skip)
