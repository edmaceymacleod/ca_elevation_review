"""FLOOR-tier meta-test: protect the engine-free collection invariant.

The floor jobs (Python 3.8/3.9) run with the engine NOT installed and rely on
pytest being able to *collect* every test module without importing
``ca_elevation_engine``. Engine-tier tests therefore import the engine inside
their functions, never at module top. This test enforces that mechanically: it
AST-scans every test module in this directory and fails if any has a top-level
``import ca_elevation_engine`` / ``from ca_elevation_engine ...``. Without this,
a future module-level engine import would pass locally (engine installed) yet
break collection on the floor jobs.
"""

from __future__ import annotations

import ast
import pathlib

TESTS_DIR = pathlib.Path(__file__).parent


def _top_level_imports(tree: ast.Module):
    names = []
    for node in tree.body:  # body only -> top level, not nested in functions
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_no_module_level_engine_import():
    offenders = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for mod in _top_level_imports(tree):
            if mod == "ca_elevation_engine" or mod.startswith("ca_elevation_engine."):
                offenders.append(f"{path.name}: top-level import {mod!r}")
    assert not offenders, (
        "engine imports must be function-local (engine-tier tests) so the 3.8/3.9 "
        "floor jobs can collect without the engine installed:\n" + "\n".join(offenders)
    )
