"""INTEGRATION tier (ENGINE, 3.10+): drive the REAL ca-elevation CLI.

Proves the subprocess seam end to end -- the mocked unit tests never run a real
process. Two cases: the known-good engine fixture (exit 0, report read from disk),
and a missing manifest (exit 1, validation error surfaced via stderr). The
exit-2 (crash) discrimination is covered by a mocked unit test, not here (a crash
is not deterministically drivable over a fixture).

Uses the engine's own synthetic fixtures by repo-relative path (they are not
shipped with the pip package). Requires ``ca-elevation`` on PATH (the engine
installed on the 3.10+ jobs, with the ``[report]`` extra so ``report.pdf`` exists).
"""

from __future__ import annotations

import os
import shutil

import pytest
from ca_elevation_revit import engine_runner
from ca_elevation_revit.engine_runner import EngineStatus

pytestmark = pytest.mark.engine


def _require_cli():
    if shutil.which("ca-elevation") is None:
        pytest.fail("ca-elevation not on PATH; the engine must be installed on the 3.10+ jobs")


def test_run_over_fixture_succeeds(tmp_path, engine_fixtures_dir):
    _require_cli()
    manifest = os.path.join(engine_fixtures_dir, "f01_office.manifest.json")
    capture = os.path.join(engine_fixtures_dir, "f01_office.capture.json")
    out = tmp_path / "out"

    result = engine_runner.run_engine(manifest, capture, str(out))

    assert result.status == EngineStatus.SUCCESS, result.stderr
    assert result.report is not None
    assert result.report["summary"]["total"] == 5
    # [report] extra installed on these jobs -> a real PDF.
    assert result.report_path is not None
    assert result.report_path.endswith("report.pdf")


def test_run_with_missing_manifest_is_validation_error(tmp_path, engine_fixtures_dir):
    _require_cli()
    capture = os.path.join(engine_fixtures_dir, "f01_office.capture.json")
    out = tmp_path / "out"

    result = engine_runner.run_engine(str(tmp_path / "does-not-exist.json"), capture, str(out))

    assert result.status == EngineStatus.VALIDATION_ERROR
    assert not result.ok
    assert result.stderr.strip()  # the CLI surfaces the error on stderr
    assert result.report is None
