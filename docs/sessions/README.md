# Session records

Dated, durable records of **multi-step or risky changes** — one file per session,
so a future contributor (or agent) can reconstruct *what changed, how it was
verified, and how to undo it* without reading the whole diff.

This format is the one referenced by `ios-app/CLAUDE.md` rule 7 ("leave a session
record with rollback steps"). The same rule applies repo-wide, not just to iOS work.

## When to write one

Write a session record when a change is **multi-step or risky**:

- it spans more than one commit or touches a load-bearing seam (schema, CI gate,
  the kit↔engine data contract, write-back, registration/ICP);
- it changes behaviour that is hard to eyeball from the diff alone;
- it was validated against live Revit, a real device, or a fixture model;
- undoing it is more than a trivial one-line revert.

For a small, self-evident change, a clear **commit body** is enough — don't add a
session file just to say "renamed a variable". Don't duplicate `handoff.md`:
`handoff.md` is the **transient** note to the *next* session and is rewritten
often; session records here are **durable** and append-only (one per dated event).

## Naming

```
docs/sessions/YYYY-MM-DD-<short-slug>.md
```

e.g. `2026-06-29-live-revit-validation.md`, `2026-07-02-writeback-persistence-cycle.md`.
Use the date the work landed. If two records share a date, the slug disambiguates.

## Template

Copy everything between the lines into a new dated file and fill it in. Delete any
section that genuinely does not apply (don't leave empty headings).

---

```markdown
# <Title> — YYYY-MM-DD

**Scope:** <one component — kit / app / engine / pyrevit / schema / ci / docs.>
**PRs / commits:** <#NNN, <sha>…> · **Status:** landed / partial / reverted

## What changed
- <Bullet the concrete edits: files, behaviour before → after. Link the PRs.>
- <Keep it to what a reviewer can't infer at a glance from the diff.>

## Why
<1–3 sentences: the problem this solved and why this approach over alternatives.
If it resolves a todo/design item, cite it (e.g. todo.md T1.3, design.md open #5).>

## How it was verified
<Exact commands run and their result — evidence, not assertions. e.g.
`cd engine && pytest -q -m "not heavy"` → 142 passed; `pwsh -File
ios-app/scripts/win-swiftlint.ps1` → 0 violations / 30 files. For live-Revit or
device work, name the model/fixture and the observed outcome.>

> FIREWALL (this is a PUBLIC repo): record **counts / shapes / pass-fail only**.
> No client project names, file paths, level/family/type names, coordinates,
> UniqueIds, or exported imagery. Live validation runs read-only or
> mutate-then-rollback on a **disposable Sterling fixture**, never a saved
> production model. See the firewall note in repo memory / `CONTRIBUTING.md`.

## How to undo
<Concrete and tested. Prefer the simplest that works:>
- `git revert <sha>` (clean revert — no follow-up needed), **or**
- flip `FeatureFlags.<toggle>` (no code change), **or**
- <manual steps, in order, if the above don't fully unwind it>.

## Follow-ups
- <Anything deliberately left for next time, with enough context to pick up.
  Mirror anything time-sensitive into `handoff.md` so the next session sees it.>
```

---

## Conventions

- **Evidence before assertions.** "Verified" means a command and its output, not
  "looks good". A record with no `How it was verified` section is incomplete.
- **Rollback must be concrete.** "Revert if needed" is not a plan; `git revert
  <sha>` or a named flag toggle is. Every session leaves the tree green and
  revertible.
- **One component per record**, matching the "keep each change scoped" rule. A
  change that genuinely spans components is usually two records (and two PRs).
- **Append, don't rewrite.** Once landed, a session record is history. Correct a
  later understanding in a *new* record that links back, rather than editing the old one.
