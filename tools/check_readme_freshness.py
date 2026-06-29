#!/usr/bin/env python3
"""Guard against README.md going stale during structural changes.

We work in phases; the failure mode this guards against is finishing a chunk of
phase work and leaving the top-level README describing the *old* shape of the
repo. This hook fails a commit when a *structural* change is staged but
README.md is not -- so the README can't silently drift out of date.

"Structural" deliberately excludes ordinary code edits (those would nag on every
commit). It fires only on changes the README actually describes:

  * a top-level directory added or removed (the "Repository layout" tree),
  * engine/pyproject.toml staged (the CLI entry point, version, and dependencies
    that the Quickstart documents -- a version bump usually marks phase progress),
  * any docs/ file staged (the Documentation index and the phase / migration
    plans the README links).

The hook inspects the staged set itself (git plumbing only -- cheap, so it runs
on the default commit stage). It is a *block*, not advisory, but always
bypassable: when a change genuinely needs no README update, commit with
`--no-verify`.
"""

from __future__ import annotations

import subprocess
import sys


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def _has_head() -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], capture_output=True
        ).returncode
        == 0
    )


def _top_dirs(paths: list[str]) -> set[str]:
    return {p.split("/", 1)[0] for p in paths if "/" in p}


def main() -> int:
    staged = [line for line in _git("diff", "--cached", "--name-only").splitlines() if line]

    # Nothing staged (e.g. a `pre-commit run --all-files` against a clean tree):
    # there is no commit to guard, so there is nothing to do.
    if not staged:
        return 0

    # The README is part of this change already -- the author has it in hand.
    if "README.md" in staged:
        return 0

    triggers: list[str] = []

    if "engine/pyproject.toml" in staged:
        triggers.append("engine/pyproject.toml changed (CLI / version / dependencies)")

    if any(p.startswith("docs/") for p in staged):
        triggers.append("docs/ changed (Documentation index / phase + migration plans)")

    if _has_head():
        head_dirs = _top_dirs(_git("ls-tree", "-r", "--name-only", "HEAD").splitlines())
        index_dirs = _top_dirs(_git("ls-files").splitlines())
        added = sorted(index_dirs - head_dirs)
        removed = sorted(head_dirs - index_dirs)
        if added:
            triggers.append(f"top-level dir added: {', '.join(added)} (update the layout tree)")
        if removed:
            triggers.append(f"top-level dir removed: {', '.join(removed)} (update the layout tree)")

    if not triggers:
        return 0

    sys.stderr.write(
        "\n".join(
            [
                "",
                "README freshness guard: a structural change is staged but README.md is not.",
                "",
                *[f"  - {t}" for t in triggers],
                "",
                "The README documents the repo's layout, CLI, status, and phase plan, so a",
                "change like this usually needs a matching edit (the Repository layout tree,",
                "Quickstart, Status line, Build phasing, or the Documentation list).",
                "",
                "Resolve it one of two ways:",
                "  * update README.md and `git add README.md`, then commit again, or",
                "  * if this change genuinely needs no README update, bypass the guard:",
                "      git commit --no-verify",
                "",
            ]
        )
        + "\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
