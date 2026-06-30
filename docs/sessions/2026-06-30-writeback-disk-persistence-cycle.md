# Write-back disk-persistence idempotency cycle — 2026-06-30

**Scope:** pyrevit (`ca_elevation_revit.revit_writeback`) — **validation only, no code change.**
**PRs / commits:** this record (docs). The write-back code was already shipped (markers + clear-by-marker idempotency). · **Status:** validated — **PASS**

## What was validated

The true **disk-persistence** idempotency cycle for `revit_writeback`, closing todo **T1.3**
("the last real Phase-1 ship gap"). The 2026-06-29 live run validated apply / clear-by-marker /
drop-a-device only inside a **rolled-back** `TransactionGroup` (`IsModified == false`), so nothing
ever persisted to disk. This run proves the cycle survives a real save → close → reopen boundary:

```
open fixture → import #1 (apply) → SAVE → close → reopen → import #2 (modified) → verify
```

## How it was verified (evidence — counts + pass/fail)

Driven via `revitmcp` on **Revit 2025.4**, replicating `revit_writeback`'s exact semantics
(marker = `[CAElev:<viewId>]` token on the built-in **Comments** param; per-view
`OverrideGraphicSettings` projection colour + solid surface fill).

1. **Import #1 (apply), committed:** 2 walls in a floor-plan view stamped with the view-scoped
   marker + a red override. (The view contained exactly 2 overridable walls.)
2. **SAVE → close → reopen** from disk.
3. **Persistence check — PASS:** both walls retained their `[CAElev:<viewId>]` marker **and** their
   red projection override (`valid=True`) **and** surface-fill visibility after the reload;
   `Document.IsModified == false` (clean from disk). → markers + overrides survive the disk boundary.
4. **Import #2 (modified report), committed:** report now **keeps wall A, drops wall B**.
   Clear-by-marker found **both** persisted-from-disk markers, reset both overrides + stripped both
   markers, then re-applied + re-marked only wall A (green).
5. **Idempotency check — PASS:**
   - **dropped wall B:** Comments `''` (marker stripped) · projection override **default/cleared**
     (its stale red override from the *saved* import #1 is gone) ✓
   - **kept wall A:** Comments `[CAElev:<viewId>]` (re-marked) · projection override **green**
     (re-applied) ✓
   - **exactly 1** marked element document-wide — **no stale markers or overrides** ✓

A device dropped from a re-imported report has its stale, disk-persisted override correctly
removed — the whole point of the marker-based idempotency, now proven across a real save/reopen.

> **FIREWALL (public repo).** The whole cycle ran on a **disposable `SaveAs` copy** of the Sterling
> fixture `sterling_test_model_R25` (a client-data-free Sterling test model — the committable
> fixture). The **original was never modified or saved** (`IsModified == false`, untouched on disk);
> the temp copy + backups were deleted afterwards. **No production/client model was ever saved.**
> Evidence here is counts + pass/fail only.

## How to undo

Nothing to undo — validation only, no code or model change shipped. (The temp `SaveAs` copy was
discarded; the Sterling fixture is unchanged.)

## Follow-ups

- **Per-commit Revit warning dialogs block the MCP API thread.** The `apply` transaction commit
  raised a non-fatal Revit **Warnings** dialog on this fixture, which blocks `execute_revit_code`
  (the API thread waits on the modal UI). Mitigation used for import #2: a transaction
  `IFailuresPreprocessor` that calls `DeleteAllWarnings()` + `SetForcedModalHandling(False)` — commits
  cleanly with no dialog. **Consider whether the production `apply_verdicts` should set a
  warning-swallowing `FailureHandlingOptions`** so the field user isn't interrupted by a warnings
  dialog on every import (pyRevit's own handler may already cover this in-app; worth confirming).
- The clear-by-marker scan in this run was **walls-scoped** for MCP-timeout reasons; the production
  `clear_prior_overrides` is **document-wide** (validated at the API level 2026-06-29). The
  persistence-handling logic under test (read persisted marker → reset persisted override → strip)
  is identical either way.
