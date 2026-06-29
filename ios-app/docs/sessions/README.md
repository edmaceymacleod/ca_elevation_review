# Session notes

Per essential rule 7 (`../../CLAUDE.md`): end a major or risky iOS change with a
dated note here so the next session knows what changed, how it was verified, and
how to undo it. Routine one-component changes can live in the commit body alone;
use a file here when the change spans several steps or could need a fast rollback.

Filename: `YYYY-MM-DD-short-slug.md`.

## Template

```markdown
# YYYY-MM-DD — <short title>

**Scope:** <which component(s) — kit / app / one view>. One component per rule 6.

**What changed**
- ...

**Why**
- ...

**How verified**
- `swift test`: <pass/fail>
- Simulator build (UI/nav): <result>
- On-device (capture/depth path): <result, what Log.* showed>

**Gotchas hit** (also added to CLAUDE.md "Platform gotchas")
- ...

**Rollback**
- `git revert <sha>`  — or —
- flip `FeatureFlags.<flag>` off (instant, no rebuild)
```
