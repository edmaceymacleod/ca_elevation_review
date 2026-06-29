"""ENGINE tier: verdict-colour exhaustiveness ratchet.

Best-effort drift guard: the lib's VERDICT_COLORS must cover exactly the engine's
``Verdict`` enum. This imports the engine, so it is engine-marked (3.10+ jobs
only) and imports inside the function so floor-job collection never needs the
engine. NOTE: ``engine/tests/test_registry.py`` is the AUTHORITATIVE
enum-completeness gate; this lib ratchet can go stale silently (a verdict added
under engine/ triggers the ``engine`` job in ci.yml, not the ``pyrevit engine``
jobs), which is exactly
why ``writeback.color_for_verdict`` is fail-soft (sentinel + warning, never
KeyError) rather than relying on this test.
"""

from __future__ import annotations

import pytest
from ca_elevation_revit.writeback import VERDICT_COLORS


@pytest.mark.engine
def test_verdict_colors_cover_engine_enum():
    from ca_elevation_engine.models import Verdict

    assert set(VERDICT_COLORS) == {v.value for v in Verdict}
