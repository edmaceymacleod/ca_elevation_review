"""ca_elevation_revit -- the testable library behind the pyRevit front door.

This package is the *real, headlessly-testable* half of the CA Elevation Review
pyRevit extension. It runs inside pyRevit's CPython engine on Windows, but every
module here is pure stdlib (no numpy, no Revit API, no engine import) so it is
exercised in normal CI on plain CPython.

Module map (see docs/pyrevit-migration-plan.md Section 4):
  config           -- engine-location config + extension paths
  manifest_builder -- raw extracted values -> spec-manifest dict
  bundle_io        -- sole writer of the field-bundle dir; reads capture packages
  engine_runner    -- locate + subprocess the out-of-process `ca-elevation` CLI
  writeback        -- verdict -> override-colour mapping + result grouping
  revit_extract / revit_export / revit_writeback
                   -- LIVE stubs: the only modules touching the Revit API
                      (function-local imports, validated on Ed's hardware)

Hard invariant: nothing here imports ``ca_elevation_engine`` at runtime. The
engine is reached only out-of-process (via the CLI) and, in tests, imported only
to assert the dicts this package builds round-trip + schema-validate.
"""

from __future__ import annotations

__version__ = "0.1.0"
