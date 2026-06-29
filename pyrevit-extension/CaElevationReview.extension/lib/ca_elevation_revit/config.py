"""Engine-location configuration and extension paths.

Pure stdlib, Python 3.8+. Holds the constants and small helpers that
``engine_runner`` uses to find the out-of-process ``ca-elevation`` CLI. No Revit
API, no engine import.
"""

from __future__ import annotations

import os
from typing import Optional

# Environment variable a user/admin can set to point at the engine explicitly
# (either a console-script path or a python interpreter inside the engine venv).
ENGINE_ENV_VAR = "CA_ELEVATION_ENGINE"

# The console script the engine installs (pyproject [project.scripts]).
CONSOLE_SCRIPT = "ca-elevation"

# Directory name of a venv shipped/produced next to the extension, if any.
BUNDLED_VENV_DIRNAME = "engine-venv"

# Default rendered-report format requested from the engine.
REPORT_FORMAT = "pdf"


def configured_engine_path(env: Optional[dict] = None) -> Optional[str]:
    """Return the explicitly-configured engine path from the environment, if set.

    ``env`` is injectable for tests; defaults to ``os.environ``.
    """
    environ = os.environ if env is None else env
    value = environ.get(ENGINE_ENV_VAR)
    return value or None
