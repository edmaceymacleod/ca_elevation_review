"""FLOOR tier: engine locator + arg-building + exit mapping (mocked subprocess).

These are the ONLY automated guard for the cross-OS locator (real on-OS execution
is Ed-gated, Windows-only), so they assert the chosen executable AND prefix args
on both the Windows and POSIX bundled-venv branches, on a single CI OS.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from ca_elevation_revit import config, engine_runner
from ca_elevation_revit.engine_runner import (
    EngineCommand,
    EngineNotFoundError,
    EngineStatus,
    classify_exit,
    locate_engine,
    wrap,
)


# --- wrap() -------------------------------------------------------------- #
def test_wrap_python_interpreter_uses_module_form():
    cmd = wrap("/opt/engine-venv/bin/python")
    assert cmd.prefix_args == ["-m", "ca_elevation_engine.cli"]
    assert cmd.argv("run") == [
        "/opt/engine-venv/bin/python",
        "-m",
        "ca_elevation_engine.cli",
        "run",
    ]


def test_wrap_windows_python_exe():
    cmd = wrap(r"C:\\engine-venv\\Scripts\\python.exe")
    assert cmd.prefix_args == ["-m", "ca_elevation_engine.cli"]


def test_wrap_console_script_runs_directly():
    cmd = wrap("/usr/local/bin/ca-elevation")
    assert cmd.prefix_args == []
    assert cmd.argv("validate") == ["/usr/local/bin/ca-elevation", "validate"]


# --- locate_engine() ----------------------------------------------------- #
def test_explicit_existing_path_is_used():
    cmd = locate_engine("/x/ca-elevation", exists=lambda p: True)
    assert cmd.executable == "/x/ca-elevation"


def test_explicit_missing_path_raises():
    with pytest.raises(EngineNotFoundError, match="explicit path"):
        locate_engine("/nope/ca-elevation", exists=lambda p: False)


def test_env_var_missing_path_raises():
    with pytest.raises(EngineNotFoundError, match=config.ENGINE_ENV_VAR):
        locate_engine(env={config.ENGINE_ENV_VAR: "/nope"}, exists=lambda p: False)


def test_bundled_venv_windows_branch():
    root = r"C:\\ext"
    expected = os.path.join(root, "engine-venv", "Scripts", "ca-elevation.exe")
    cmd = locate_engine(
        platform="win32",
        exists=lambda p: p == expected,
        extension_root=root,
        env={},
    )
    assert cmd.executable == expected
    assert cmd.prefix_args == []  # console script, runs directly


def test_bundled_venv_posix_branch_python_falls_to_module_form():
    root = "/ext"
    # ca-elevation console script absent, python present -> module form.
    py = os.path.join(root, "engine-venv", "bin", "python")
    cmd = locate_engine(
        platform="linux",
        exists=lambda p: p == py,
        extension_root=root,
        env={},
    )
    assert cmd.executable == py
    assert cmd.prefix_args == ["-m", "ca_elevation_engine.cli"]


def test_path_fallback_returned_unprobed():
    cmd = locate_engine(platform="linux", exists=lambda p: False, extension_root="/ext", env={})
    assert cmd.executable == config.CONSOLE_SCRIPT
    assert cmd.prefix_args == []


# --- run_engine() (mocked subprocess) ------------------------------------ #
class _Recorder:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def test_run_engine_builds_args_and_reads_report(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "verdict_report.json").write_text(json.dumps({"summary": {"total": 3}}))
    (out / "report.pdf").write_bytes(b"%PDF-1.4")
    rec = _Recorder(returncode=0, stdout="PASS 3", stderr="wrote pdf")

    result = engine_runner.run_engine(
        "m.json",
        "c.json",
        str(out),
        command=EngineCommand("ca-elevation", []),
        runner=rec,
    )
    argv = rec.calls[0][0]
    assert argv[:1] == ["ca-elevation"]
    assert "run" in argv and "--manifest" in argv and "--format" in argv
    assert argv[argv.index("--format") + 1] == "pdf"
    assert result.report == {"summary": {"total": 3}}
    assert result.report_path.endswith("report.pdf")
    assert result.status == EngineStatus.SUCCESS
    assert result.ok


def test_run_engine_html_fallback_discovered(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "verdict_report.json").write_text("{}")
    (out / "report.html").write_text("<html></html>")  # no pdf
    result = engine_runner.run_engine(
        "m", "c", str(out), command=EngineCommand("ca-elevation", []), runner=_Recorder()
    )
    assert result.report_path.endswith("report.html")


# --- exit-code contract (1 vs 2 distinguished, mocked) ------------------- #
@pytest.mark.parametrize(
    "rc,status",
    [
        (0, EngineStatus.SUCCESS),
        (1, EngineStatus.VALIDATION_ERROR),
        (2, EngineStatus.CRASH),
        (7, EngineStatus.UNKNOWN),
    ],
)
def test_classify_exit(rc, status):
    assert classify_exit(rc) == status


def test_run_engine_surfaces_validation_vs_crash(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    r1 = engine_runner.run_engine(
        "m", "c", str(out), command=EngineCommand("x", []), runner=_Recorder(1, "", "error: bad")
    )
    assert r1.status == EngineStatus.VALIDATION_ERROR and not r1.ok
    r2 = engine_runner.run_engine(
        "m", "c", str(out), command=EngineCommand("x", []), runner=_Recorder(2, "", "traceback")
    )
    assert r2.status == EngineStatus.CRASH


def test_validate_passes_capture_when_given():
    rec = _Recorder()
    engine_runner.validate(
        "m.json", "c.json", command=EngineCommand("ca-elevation", []), runner=rec
    )
    argv = rec.calls[0][0]
    assert "validate" in argv and "--capture" in argv

    rec2 = _Recorder()
    engine_runner.validate("m.json", command=EngineCommand("ca-elevation", []), runner=rec2)
    assert "--capture" not in rec2.calls[0][0]


# --- corrupt / decoupled report surfaces (FLOOR, mocked) ----------------- #
def test_run_engine_corrupt_report_does_not_crash(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "verdict_report.json").write_text("{bad")
    json_path = os.path.join(str(out), "verdict_report.json")
    result = engine_runner.run_engine(
        "m.json",
        "c.json",
        str(out),
        command=EngineCommand("ca-elevation", []),
        runner=_Recorder(returncode=0),
        exists=lambda p: p == json_path,
    )
    assert result.report is None
    assert result.status == EngineStatus.SUCCESS
    assert result.ok is True


def test_run_engine_report_present_despite_validation_exit(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "verdict_report.json").write_text(json.dumps({"summary": {"total": 1}}))
    json_path = os.path.join(str(out), "verdict_report.json")
    result = engine_runner.run_engine(
        "m.json",
        "c.json",
        str(out),
        command=EngineCommand("ca-elevation", []),
        runner=_Recorder(returncode=1),
        exists=lambda p: p == json_path,
    )
    assert result.report is not None
    assert result.status == EngineStatus.VALIDATION_ERROR
    assert not result.ok


@pytest.mark.parametrize("fmt", ["html", "json"])
def test_run_engine_format_flag_plumbed(tmp_path, fmt):
    out = tmp_path / "out"
    out.mkdir()
    rec = _Recorder()
    engine_runner.run_engine(
        "m.json",
        "c.json",
        str(out),
        command=EngineCommand("ca-elevation", []),
        report_format=fmt,
        runner=rec,
        exists=lambda p: False,
    )
    argv = rec.calls[0][0]
    assert argv[argv.index("--format") + 1] == fmt


def test_run_engine_json_format_finds_no_pdf_html(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "verdict_report.json").write_text("{}")
    json_path = os.path.join(str(out), "verdict_report.json")
    result = engine_runner.run_engine(
        "m.json",
        "c.json",
        str(out),
        command=EngineCommand("ca-elevation", []),
        report_format="json",
        runner=_Recorder(),
        exists=lambda p: p == json_path,  # only json present, no pdf/html
    )
    assert result.report_path is None


def test_run_engine_no_report_on_disk(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    result = engine_runner.run_engine(
        "m.json",
        "c.json",
        str(out),
        command=EngineCommand("ca-elevation", []),
        runner=_Recorder(returncode=2),
        exists=lambda p: False,
    )
    assert result.report is None
    assert result.report_path is None
    assert result.status == EngineStatus.CRASH


def test_validate_returns_completed_process_surface():
    rec = _Recorder(returncode=1, stderr="bad manifest")
    proc = engine_runner.validate("m.json", command=EngineCommand("ca-elevation", []), runner=rec)
    assert proc.returncode == 1
    argv = rec.calls[0][0]
    assert "validate" in argv
    assert "--capture" not in argv


def test_run_engine_argv_order_is_stable(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    rec = _Recorder()
    engine_runner.run_engine(
        "M",
        "C",
        "O",
        command=EngineCommand(config.CONSOLE_SCRIPT, []),
        report_format="F",
        runner=rec,
        exists=lambda p: False,
    )
    argv = rec.calls[0][0]
    assert argv == [
        config.CONSOLE_SCRIPT,
        "run",
        "--manifest",
        "M",
        "--capture",
        "C",
        "--out",
        "O",
        "--format",
        "F",
    ]
