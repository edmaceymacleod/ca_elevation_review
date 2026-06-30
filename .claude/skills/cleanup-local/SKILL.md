---
name: cleanup-local
description: Use when local worktrees have accumulated and need cleanup — rescues uncommitted/untracked/stashed/unpushed work into PRs, then deletes non-lane worktree folders. Lane worktrees (C:/agents/lane-*) are reset to origin/main but kept. Skips main and *live* locked worktrees (dead-pid locks are reclaimed). Also sweeps orphan local branches (worktree-agent-*, pr-*) whose tips are already in origin, and inspects orphan stashes to advise drop-vs-keep.
---

# Cleanup Local

Sweep all local git worktrees, rescue any work-in-progress into PRs, and delete the folders. Lane worktrees are cleaned but preserved (the orchestrator reuses them).

Operates from any worktree. The current worktree is rescued and switched to `main` rather than deleted (you can't remove the worktree you're standing in on Windows).

> **Repo context (ca_elevation_review).** This repo is a **`main`-trunk** project — there is no `dev` branch; PRs target `main` and owner PRs auto-squash-merge on green CI. It is also a **PUBLIC** repo: any rescue push/PR this skill creates publishes its contents, so a worktree must never be rescued if it contains unsanitized client data from a production Revit model — abort that worktree's rescue, move it to `BLOCKED`, and surface it instead (see the client-data firewall in repo memory). Lane worktrees under `C:/agents/lane-*` belong to the shared orchestrator and are usually worktrees of *other* repos; when this skill is run from `ca_elevation_review` they will not appear in this repo's `git worktree list`, so the lane bucket is typically inert here.

## Steps

Follow in order. Print the plan from Step 2 for transparency, then run all remaining steps to completion without further prompts.

### 1. Inventory and categorize

```bash
git worktree list --porcelain
git stash list
gh pr list --state open --json number,headRefName --limit 200
```

Classify each worktree into exactly one bucket:

| Bucket               | Match                                                                  | Action                                                                                 |
| -------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **skip-protected**   | branch is `main`                                                       | leave untouched                                                                        |
| **skip-locked-live** | worktree has `locked` flag AND lock-holder pid is alive                | leave untouched, warn                                                                  |
| **reclaim-locked**   | worktree has `locked` flag AND lock-holder pid is dead                 | unlock, then treat as **delete** (rescue, remove)                                      |
| **lane**             | path matches `C:/agents/lane-*`                                        | rescue work, then reset to `origin/main` on existing `lane-N-scratch` branch, **keep** |
| **current**          | path == this skill's cwd                                               | rescue work, then `git checkout main`, **keep**                                        |
| **delete**           | everything else                                                        | rescue work, then `git worktree remove`                                                |

**Detecting dead-pid locks.** The `locked` line in `git worktree list --porcelain` typically contains a reason like `claude agent agent-xxx (pid 5132)`. Extract the pid and probe:

```powershell
Get-Process -Id <pid> -ErrorAction SilentlyContinue
```

Empty output means the process is gone — the lock is stale and the worktree is reclaimable. If the reason has no pid, treat as `skip-locked-live` (conservative default).

For each candidate worktree, also gather:

- `git -C <path> status --porcelain` (uncommitted/untracked)
- `git -C <path> rev-list --count origin/<branch>..<branch> 2>/dev/null` (unpushed commits — `0` if branch isn't tracked or remote is gone)
- stashes whose subject ends with `on <branch>:` from the global `git stash list`
- whether `gh pr list` already has an open PR for `<branch>`

### 2. Print the plan (no confirmation gate)

Print a single summary table for transparency, then proceed immediately to Step 3 — **do not stop to ask "Proceed?"** (per `feedback_act_on_recommendation`: the user invoked the skill; that is the confirmation).

```
DELETE (after rescue):
  C:/path/to/feature-foo  [feature/foo]  uncommitted=3 untracked=1 stash=0 unpushed=2 pr=#412
  ...
RECLAIM (locked, dead pid — will unlock):
  .claude/worktrees/agent-xxx  [feature/foo-v2]  pid=5132 (dead)  uncommitted=0 ...
CLEAN-AND-KEEP (lanes):
  C:/agents/lane-1  [lane-1-scratch]  uncommitted=0 untracked=4 stash=0 unpushed=0
  ...
CURRENT (rescue + checkout main):
  C:/githubdesktop/ca_elevation_review  [feature/whatever]  uncommitted=0 ...
SKIP (locked, live pid):
  .claude/worktrees/agent-yyy  [feature/asr-phase-4]  pid=28344 (alive)
```

Run **all** subsequent steps (3 through 10) to completion — including Step 6's `[gone]`-branch sweep, Step 7's orphan-branch sweep, Step 8's orphan-stash inspection, and Step 9's "finalize on main", which always run even when the DELETE/RECLAIM buckets are empty. Pruning stale local refs and ending on a clean main are the most common reasons to invoke this skill in the first place.

**Reclaim step (between Step 2 and Step 3):** for each `reclaim-locked` worktree, run `git worktree unlock <path>` once. From here on, treat it identically to a `delete`-bucket worktree — Steps 3 (rescue) and 5 (remove) handle it normally.

### 3. Rescue work-in-progress (per worktree, in this order: delete → lane → current)

For each worktree that has _anything_ in (uncommitted, untracked, matching stash, unpushed):

1. **Pop matching stashes** (oldest first):

   ```bash
   git -C <path> stash pop <ref>
   ```

   If pop fails with conflict markers: leave the stash, abort this worktree's rescue, move it to a `BLOCKED` list, and continue with others. Do not auto-resolve.

2. **Stage and commit anything dirty:**

   ```bash
   git -C <path> add -A
   git -C <path> -c user.name="$(git config user.name)" commit -m "WIP: cleanup-local rescue

   Auto-rescued by /cleanup-local before worktree removal."
   ```

3. **Push and PR if needed:**
   - If branch is ahead of `origin/<branch>` (or has no remote tracking yet):

     ```bash
     git -C <path> push -u origin <branch>
     ```

   - If no open PR exists for `<branch>`, create one with `do-not-test` label targeting `main`:

     ```bash
     gh pr create --base main --head <branch> --label "do-not-test" \
       --title "WIP rescue: <branch>" \
       --body "Auto-created by /cleanup-local to preserve work before worktree removal. Review and either complete or close."
     ```

   - If a PR already exists, just push (the new commit lands on the existing PR).

### 4. Reset lane worktrees

For each lane worktree (after rescue):

```bash
git -C <lane-path> fetch origin main
git -C <lane-path> checkout -B lane-N-scratch origin/main
git -C <lane-path> clean -fd
```

This puts the lane back in the state the orchestrator's gate (b) expects: clean tree, on `lane-N-scratch`, at `origin/main`.

### 5. Remove delete-bucket worktrees

For each:

```bash
git worktree remove <path>           # try clean removal first
git worktree remove --force <path>   # fall back if it complains
rm -rf <path>                        # Windows orphan-folder cleanup (per memory)
```

Do not `--force` until the clean removal fails — it surfaces issues like residual locks worth seeing.

### 6. Sweep merged/gone local branches (always runs, with safety filter)

Always run a `[gone]` branch sweep — never skip, never ask — but **do not blindly invoke `commit-commands:clean_gone`**. That skill force-removes any worktree attached to a `[gone]` branch, which conflicts with the "always skip locked superpowers worktrees" guardrail above and uses `git branch -D` (which silently discards unpushed commits).

Instead, do the sweep here, with explicit safety checks:

```bash
git fetch --prune
git branch -vv
```

For each branch shown as `[gone]`, walk this checklist top to bottom — every check before the final delete is a potential rescue point, and skipping any of them risks silent data loss:

**a. Skip if attached to a locked worktree.** A `+` prefix in `git branch -v` means it has a worktree. Cross-check with `git worktree list --porcelain`; if the worktree entry has a `locked` line, leave the branch alone (Step 5 has already removed non-locked worktrees, so any worktree still standing here is locked by definition). Surface in the final report and move on to the next branch — none of the remaining checks run for skipped branches.

**b. Detect unmerged / unpushed commits.** Run `git log <branch> --not --remotes --oneline`. Save the output as `unpushed_commits` for use below.

**c. Detect matching stashes.** From the global `git stash list`, collect any entries whose subject ends in `on <branch>:` (the outer Step 3 only visits worktree-bound branches, so a `[gone]` branch without a worktree wouldn't have been visited there). Save as `branch_stashes`.

**d. If `unpushed_commits` is non-empty OR `branch_stashes` is non-empty, open a rescue PR before deleting.** This is the silent-data-loss footgun this skill exists to prevent. Push the branch back to origin (the upstream is `[gone]` precisely because the remote was deleted, so this re-creates it):

   ```bash
   git push -u origin <branch>
   ```

   If `branch_stashes` is non-empty, pop each stash on a temporary checkout of the branch, commit with a `WIP: cleanup-local stash rescue` message, and push the resulting commit. Then open the rescue PR:

   ```bash
   gh pr create --base main --head <branch> --label "do-not-test" \
     --title "WIP rescue: <branch>" \
     --body "Auto-rescued by /cleanup-local. The original remote branch was deleted while local work had not merged anywhere. Review and either complete, supersede, or close. Recovered commits: <list from unpushed_commits and stash-rescue commits>"
   ```

   **Do not auto-run `/code-review` on rescue PRs** — they are parking spots for abandoned/orphaned work, not finished deliverables. Reviewing them wastes review effort. Note this explicitly in the final report so the user knows to expect a `PostToolUse` hook may fire and should be ignored.

**e. Delete the local branch.** Whether or not a rescue PR was opened in (d), the local branch is now redundant — its work is either reachable from a remote ref already (clean delete) or preserved on the rescue PR (rescued delete). Run:

   ```bash
   git branch -D <branch>
   ```

   Without this final delete, the branch keeps reappearing in future `[gone]` sweeps because the new rescue-PR upstream is on a different remote ref name than the original.

Surface every action in the final report: deleted (clean), rescued-then-deleted (with PR URL), or skipped (locked-worktree). The user should never have to read the reflog to know what happened.

### 7. Sweep orphan local branches (always runs)

Local branches with no upstream and no `[gone]` marker accumulate over time:

- `worktree-agent-<hash>` — pseudo-branches left over from past superpowers worktrees (the worktree dir is gone but the branch ref remains)
- `pr-<N>` / `pr<N>` — local checkouts created by `gh pr checkout`, kept after the PR closed/merged

These are safe to delete only when their tip is already preserved in `origin/main`. Walk every branch matching the patterns above:

```powershell
$orphans = git branch --format='%(refname:short)' | Where-Object { $_ -match '^(worktree-agent-|pr-?\d)' }
foreach ($b in $orphans) {
  $inMain = git merge-base --is-ancestor $b origin/main 2>$null; $mainOk = ($LASTEXITCODE -eq 0)
  $unpushed = (git log $b --not --remotes --oneline 2>$null | Measure-Object -Line).Lines
  # delete only if reachable from a remote ref AND has no unpushed work
  if ($mainOk -and $unpushed -eq 0) {
    git branch -D $b
  } else {
    # surface for manual review
  }
}
```

For `pr-N` orphans whose tip is *not* reachable from any remote, look up the PR state with `gh pr view N --json state,mergedAt,headRefName`:

- `MERGED` (squash) → tip won't be ancestor of main but the work is in. Verify by grepping `git log origin/main --grep "<commit subject>"` for the squash commit; if found, delete.
- `CLOSED` → check whether the work was superseded by another PR (search `gh pr list --search "<key phrase>"`). If superseded, delete. If genuinely lost, treat as a Step 6 rescue: push the branch under a new name and open a `do-not-test` rescue PR.

Never `branch -D` a `pr-N` orphan with unpushed work and no merged/superseding PR — that's the silent-data-loss footgun this skill exists to prevent.

### 8. Inspect orphan stashes and advise

Worktree-bound stashes are handled in Step 3 (popped onto their branch). Anything still in `git stash list` after that point is an **orphan stash** — its associated branch no longer exists locally, or was never visited because it had no worktree. Stashes survive branch deletion, `gc`, and worktree removal; they sit in `refs/stash` and only auto-expire after ~90 days. Left alone, they accumulate quietly and become a silent-data-loss vector when someone eventually runs `git stash clear`.

For each remaining stash, classify the verdict — never auto-drop, always advise.

1. **Identify and size each stash:**

   ```bash
   git stash list
   git stash show -p stash@{N} --stat
   ```

2. **Decide the verdict** for each, using the chain below in order:

   | Verdict | When to assign | Recommended action surfaced in report |
   |---|---|---|
   | `superseded` | Every meaningful line of the stash diff is already present on `origin/main`. Verify by grepping main for the most identifying lines — comment text, new exception/class names, helper imports — not by line-by-line diffing. | `git stash drop stash@{N}` — safe |
   | `partially-superseded` | Some content shipped on main, some did not. | Inspect the unshipped delta; if it's clearly abandoned, drop. Otherwise treat as `live`. |
   | `live` | Stash contains work not on any remote ref, and the work still looks intended. The branch in the stash subject line may or may not still exist. | Apply onto a fresh branch off `main` and push as a `do-not-test` rescue PR (same shape as Step 6.d). Then drop the stash. |
   | `unclear` | Tiny diff, cryptic subject, no obvious connection to recent PRs, or the stash is older than ~30 days. | Surface in report verbatim; do not drop. Let Ed decide. |

3. **Verification grep pattern.** For a stash whose diff introduces a recognisable string (new class name, new comment line, new import), search main with:

   ```bash
   grep -rn "<distinctive string>" engine/ pyrevit-extension/ ios-app/ schema/ docs/
   ```

   Two or three positive hits on the most identifying strings is sufficient evidence of `superseded`. Match the stash branch name against shipped PR titles in `git log --oneline -30` for a second signal — but never rely on branch name alone; the user routinely parks unrelated WIP under a re-used branch name.

4. **Never auto-drop.** Even when verdict is `superseded`, the skill only *recommends* `git stash drop stash@{N}` in the final report. Dropping requires the user's go-ahead. This protects against the case where the grep verification accidentally false-positives on similar-but-not-identical code paths.

### 9. Finalize: end on up-to-date `main`

**Runs unconditionally**, regardless of whether any rescue, deletion, or sweep happened earlier. The skill's postcondition is "the current worktree HEAD is `main`, fast-forwarded to `origin/main`". This step makes that guarantee explicit.

```bash
git fetch origin main
git checkout main
git pull --ff-only origin main
```

If the working tree is dirty (Step 3 rescue was skipped or `BLOCKED`), commit or stash before this step — never invoke this in a way that loses uncommitted work. If `checkout main` fails (e.g. dirty tree, hooks rejecting), surface the failure in the final report and leave the user on whatever branch they were on; do not retry destructively.

### 10. Prune and report

```bash
git worktree prune
git worktree list
git stash list
gh pr list --author @me --state open --label do-not-test --limit 50
git rev-parse --abbrev-ref HEAD     # must print: main
git rev-list --count HEAD..origin/main  # must print: 0
```

The last two commands verify the Step 9 postcondition. If either is wrong, say so loudly in the report — the skill failed its contract.

Final report to user:

- N worktrees deleted
- R worktrees reclaimed from dead-pid locks (with the original lock holder pid for traceability)
- M lanes cleaned and kept
- K worktrees blocked (list paths + reason: stash conflict, push failure, live-pid lock, unsanitized client data, etc.)
- G `[gone]`-branch sweep: deleted-clean / rescued-then-deleted (with PR URLs) / skipped-locked counts
- O orphan local branches deleted (worktree-agent-*, pr-*)
- P orphan branches surfaced for manual review (unreachable from origin, no merged PR)
- Orphan stashes (Step 8): one line per stash with `verdict` (`superseded` / `partially-superseded` / `live` / `unclear`), the recommended action, and the evidence that informed the verdict (e.g. "matches shipped PRs #452/#453/#454; identifying strings present in main"). Always recommend, never auto-drop.
- New PRs opened (URLs)
- Updated PRs (URLs of pre-existing PRs that got the rescue commit)

If any worktrees ended up in BLOCKED, leave them as-is — do not retry destructively.

## Notes

- **Never run inside a lane worktree.** The current-worktree logic assumes you're in the main clone or a feature worktree, not a lane.
- **The `WIP: cleanup-local rescue` commit message** is intentionally distinctive — grep for it later to find rescued work that needs follow-up.
- **Stash association** is by subject line (`WIP on <branch>:` / `On <branch>:`). Stashes created via `git stash push -m` may not match a branch — those fall through to Step 8, which classifies and advises on them as orphan stashes.
- **Locked superpowers worktrees** (`.claude/worktrees/agent-*`) are managed by the superpowers skill *only while the holding process is alive*. A dead-pid lock is a stale leftover (most often from a self-upgraded `claude.exe.old.<timestamp>` or a session that exited without cleanup) and is safe to reclaim — that's the `reclaim-locked` bucket. Live-pid locks must always be left alone, since reclaiming them out from under a running agent corrupts its state.
- **Public-repo firewall.** `ca_elevation_review` is world-readable. Any rescue push/PR publishes its branch contents irreversibly, so never rescue a worktree holding unsanitized client data from a production Revit model — `BLOCK` it and surface it instead. This skill also must not be the thing that first commits client data: it only ever pushes branches that already exist locally.
