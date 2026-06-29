"""Locate and invoke the out-of-process ``ca-elevation`` CLI.

Ports the C# ``EngineLocator`` / ``EngineCommand`` / ``EngineRunner`` semantics
to pure-stdlib Python (3.8+). Revit -- and therefore real execution -- is
Windows-only, but this module is OS-agnostic and the existence-probe + platform
are injectable so both branches are unit-tested on ubuntu CI.

Resolution order (first match wins), mirroring the C# locator:
  1. explicit path argument
  2. ``CA_ELEVATION_ENGINE`` environment variable
  3. a bundled venv next to the extension (``engine-venv/``) -- probed for existence
  4. PATH fallback: the bare ``ca-elevation`` console script (returned UNPROBED)

Configured-but-missing (1 or 2 pointing at a nonexistent path) RAISES; the PATH
fallback is returned without probing (we cannot reliably probe PATH here, and the
subprocess will surface a clear error if it is absent).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from . import config

logger = logging.getLogger(__name__)


class EngineNotFoundError(RuntimeError):
    """Raised when an explicitly-configured engine path does not exist."""


class EngineStatus:
    """Outcome class for a CLI exit code (0/1/2 contract)."""

    SUCCESS = "success"
    VALIDATION_ERROR = "validation_error"  # exit 1
    CRASH = "crash"  # exit 2
    UNKNOWN = "unknown"


@dataclass
class EngineCommand:
    """An invocable engine: an executable plus fixed prefix args.

    Mirrors the C# ``EngineCommand`` + ``Wrap()``: a python interpreter is
    invoked as ``python -m ca_elevation_engine.cli``; a console script is invoked
    directly.
    """

    executable: str
    prefix_args: List[str] = field(default_factory=list)

    def argv(self, *args: str) -> List[str]:
        return [self.executable, *self.prefix_args, *args]


def _is_python_interpreter(path: str) -> bool:
    """Whether a resolved path looks like a python interpreter (vs a console script).

    Separator-agnostic: a Windows path must be classified correctly even when the
    test (or the locator) runs on POSIX CI, where ``os.path.basename`` would not
    split on ``\\``.
    """
    leaf = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if leaf.endswith(".exe"):
        leaf = leaf[:-4]
    return leaf.startswith("python")


def wrap(path: str) -> EngineCommand:
    """Wrap a resolved path as an EngineCommand (the C# ``Wrap`` behaviour)."""
    if _is_python_interpreter(path):
        return EngineCommand(path, ["-m", "ca_elevation_engine.cli"])
    return EngineCommand(path, [])


def _bundled_candidates(extension_root: str, platform: str) -> List[str]:
    """Candidate bundled-venv executables for the given platform.

    Built from ``os.name``/``sys.platform`` rather than hardcoded separators.
    Windows: ``engine-venv/Scripts/ca-elevation.exe`` (then ``Scripts/python.exe``);
    POSIX:   ``engine-venv/bin/ca-elevation`` (then ``bin/python``).
    """
    venv = os.path.join(extension_root, config.BUNDLED_VENV_DIRNAME)
    if platform.startswith("win"):
        return [
            os.path.join(venv, "Scripts", "ca-elevation.exe"),
            os.path.join(venv, "Scripts", "python.exe"),
        ]
    return [
        os.path.join(venv, "bin", "ca-elevation"),
        os.path.join(venv, "bin", "python"),
    ]


def locate_engine(
    explicit: Optional[str] = None,
    *,
    env: Optional[dict] = None,
    platform: Optional[str] = None,
    exists: Callable[[str], bool] = os.path.exists,
    extension_root: Optional[str] = None,
) -> EngineCommand:
    """Resolve an :class:`EngineCommand` per the documented order.

    ``platform``/``exists``/``extension_root``/``env`` are injectable so both the
    Windows and POSIX bundled-venv branches are testable on a single CI OS.
    """
    plat = sys.platform if platform is None else platform

    # 1 + 2: explicit path, then env var -- configured-but-missing RAISES.
    configured = explicit or config.configured_engine_path(env)
    if configured:
        if not exists(configured):
            source = "explicit path" if explicit else config.ENGINE_ENV_VAR
            raise EngineNotFoundError(f"configured engine ({source}) does not exist: {configured}")
        return wrap(configured)

    # 3: bundled venv next to the extension -- probed.
    root = extension_root if extension_root is not None else _default_extension_root()
    for candidate in _bundled_candidates(root, plat):
        if exists(candidate):
            return wrap(candidate)

    # 4: PATH fallback -- returned UNPROBED.
    return EngineCommand(config.CONSOLE_SCRIPT, [])


def _default_extension_root() -> str:
    """The extension root (two levels up from this lib package)."""
    # .../CaElevationReview.extension/lib/ca_elevation_revit/engine_runner.py
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))


@dataclass
class EngineRun:
    """Result of a ``ca-elevation run`` invocation."""

    returncode: int
    report: Optional[dict]  # parsed verdict_report.json, or None if absent
    report_path: Optional[str]  # the rendered report (pdf or html), or None
    stdout: str
    stderr: str
    # Set when verdict_report.json existed but could not be read/parsed (a
    # truncated/corrupt report). When this is set, ``ok`` is False even on a
    # 0 exit code, so the front door cannot present a corrupt report as success.
    report_error: Optional[str] = None

    @property
    def status(self) -> str:
        return classify_exit(self.returncode)

    @property
    def ok(self) -> bool:
        # A 0 exit code is necessary but not sufficient: an engine that exited
        # cleanly yet wrote an unreadable report is NOT ok, otherwise a corrupt
        # review would be presented as a passing one.
        return self.returncode == 0 and self.report_error is None


def classify_exit(returncode: int) -> str:
    """Map the engine CLI exit code to a status (0 success / 1 validation / 2 crash)."""
    if returncode == 0:
        return EngineStatus.SUCCESS
    if returncode == 1:
        return EngineStatus.VALIDATION_ERROR
    if returncode == 2:
        return EngineStatus.CRASH
    return EngineStatus.UNKNOWN


def _find_report(out_dir: str, exists: Callable[[str], bool] = os.path.exists) -> Optional[str]:
    """Discover the rendered report by preference (pdf, then html)."""
    for name in ("report.pdf", "report.html"):
        p = os.path.join(out_dir, name)
        if exists(p):
            return p
    return None


def run_engine(
    manifest_path: str,
    capture_path: str,
    out_dir: str,
    *,
    command: Optional[EngineCommand] = None,
    report_format: str = config.REPORT_FORMAT,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    exists: Callable[[str], bool] = os.path.exists,
) -> EngineRun:
    """Invoke ``ca-elevation run`` and read back the verdict report from disk.

    Reads ``OUT/verdict_report.json`` from disk (always written by the engine) --
    stdout is non-contractual and is NOT scraped. The rendered report is
    discovered by glob (pdf preferred, html fallback). ``runner``/``exists`` are
    injectable so the subprocess is mocked in unit tests.
    """
    cmd = command or locate_engine()
    argv = cmd.argv(
        "run",
        "--manifest",
        manifest_path,
        "--capture",
        capture_path,
        "--out",
        out_dir,
        "--format",
        report_format,
    )
    proc = runner(argv, capture_output=True, text=True)

    report = None
    report_error = None
    json_path = os.path.join(out_dir, "verdict_report.json")
    if exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as fh:
                report = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            # Written-but-unreadable. Surface it: record the error so ``ok`` is
            # False (a corrupt report after exit 0 is NOT a passing review) and
            # log so the failure is not swallowed silently.
            report = None
            report_error = f"could not read {json_path}: {exc}"
            logger.exception("verdict_report.json present but unreadable: %s", json_path)

    return EngineRun(
        returncode=proc.returncode,
        report=report,
        report_path=_find_report(out_dir, exists=exists),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        report_error=report_error,
    )


def validate(
    manifest_path: str,
    capture_path: Optional[str] = None,
    *,
    command: Optional[EngineCommand] = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> subprocess.CompletedProcess:
    """Invoke ``ca-elevation validate`` (manifest, optionally with a capture).

    Returns the completed process so the caller can inspect ``returncode`` /
    ``stderr``. Note: manifest-only validate catches duplicate ids + dangling
    ``level_id`` (schema + ``_check_manifest_internal``); project-id / shot-level
    cross-checks only run when ``--capture`` is also passed.
    """
    cmd = command or locate_engine()
    args: Sequence[str] = ("validate", "--manifest", manifest_path)
    if capture_path:
        args = (*args, "--capture", capture_path)
    return runner(cmd.argv(*args), capture_output=True, text=True)
