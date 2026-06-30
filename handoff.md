# Handoff — CA Elevation Review

Transient scratchpad for notes to the **next** session. Keep durable facts out of
here — **persistent records live in `docs/`**.

Project orientation (durable records):

- `docs/live-validation-2026-06-29.md` — live `revit_*` extract / write-back /
  bundle→engine evidence + the solid-fill eyeball (PRs #22, #25).
- `docs/pyrevit-migration-plan.md` — pyRevit pin / CPython-floor and remaining
  open migration items. The pyRevit extension registers + loads its ribbon (#26).

## Just landed — 2026-06-30 (CI cross-platform hardening + a bug it caught)

Both previous handoff next-steps shipped, plus a regression the new Windows leg
surfaced. Self-documenting in `ci.yml` comments + the PRs; listed here only as
orientation:

- **#30** — kit⟷engine schema cross-check (gating `xlang_schema`; shared
  `CaElevationFixtures` target + `cek-emit` executable; PC repro
  `ios-app/scripts/win-xlang-check.ps1`).
- **#31** — Foundation-only enforcement: gating grep import-guard in `ios_kit`
  (over the pure targets) + gating Linux leg `ios_kit_linux` (`container: swift:6.0`).
- **#32** — informational Windows leg `ios_kit_windows` (`windows-2022`, Swift
  6.3.2 via `SwiftyLab/setup-swift@v1.14.0` + SHA-pinned `ilammy/msvc-dev-cmd`).
  NON-gating: omitted from `all-green` + job-level `continue-on-error`, so a
  Windows flake never fails the CI *workflow* (which would block owner auto-merge
  for all iOS PRs).
- **#33** — fix: `BundleIO.resolvedURL` rejected every valid path on Windows (8.3
  short-name expansion in `resolvingSymlinksInPath` vs a not-yet-created tail);
  the informational Windows leg is what surfaced it. iOS (production) unaffected.

## Just landed — 2026-06-30 (local SwiftLint parity)

- **`claude/win-swiftlint-parity` (PR pending)** — root `.gitattributes`
  (`* text=auto eol=lf` + binary marks) forces LF on checkout, overriding
  Git-for-Windows `core.autocrlf=true`. On a CRLF tree SwiftLint counted CR+LF as
  two line breaks (doubling line counts), throwing 253 false
  `comma`/`trailing_newline`/`file_length` errors; on LF it is clean = exact
  parity with the gating macOS CI. Plus `ios-app/scripts/win-swiftlint.ps1` (PC
  mirror of the CI SwiftLint gate: USER-PATH prepend for sourcekitd + swiftlint,
  **no** Enter-VsDevShell — lint never links — fail-closed on non-zero exit AND
  zero-files). Verified on the PC: green path 0 violations/30 files, red path
  throws on an injected violation. The index was already 100% LF, so
  `git add --renormalize .` is a no-op and the diff touches no workflow file →
  auto-merges on green. The one-time working-tree CRLF→LF flip recipe lives in
  `ios-app/CLAUDE.md` "Platform gotchas".

## Done — Dependabot #29 (`github-script@v7→v9`, MERGED 2026-06-30)

Triaged safe (script uses only the injected `github`/`context`/`core`, so none of
v9's breaking changes fire; node24 runtime on `ubuntu-latest`; `@v9` matches the
first-party `actions/*` major-float house style). Ed merged it manually (workflow
scope) at 11:39. **Validated in production:** the next owner PR (#35) auto-merged
at 11:42 — squash + branch-delete both fired — so `auto-merge.yml` runs clean on
v9. No follow-up needed.

## Next steps

1. **(Optional) Promote the Windows leg to gating.** The kit already builds green
   on Windows; keep it informational until the *setup* (toolchain download /
   setup-swift / msvc-dev-cmd) is observed stable over several runs. To promote:
   add `ios_kit_windows` to `all-green`'s `needs:` **and** R-map in ONE commit and
   drop `continue-on-error`. (Narrow its trigger to `ios-app/**`, excluding
   `ci.yml`, so routine CI edits aren't gated on Swift-on-Windows availability.)
2. **(Optional) Pin SwiftLint for true version parity.** CI installs swiftlint via
   `brew install swiftlint` (floats to latest); `win-swiftlint.ps1` uses the PATH
   swiftlint (the PC has 0.65.0). Same result today, but a future brew bump could
   flag what local passes (rule-set drift) — the one parity hole `.gitattributes`
   doesn't close. To fix: pin a fixed swiftlint release in `ci.yml` (touches a
   workflow file → needs `workflow` scope to merge) and record the expected
   version next to the script. Low priority.

## Gotcha — merging CI PRs (verified 2026-06-30)

Any PR touching `.github/workflows/` can't be merged by the auto-merge bot OR the
local `gh` — the token scopes are `gist, read:org, repo` (no `workflow`). Use
`gh auth refresh -h github.com -s workflow` then `gh pr merge`, or merge in the
web UI. Non-workflow PRs (e.g. this `.gitattributes`/`win-swiftlint.ps1` change,
or #33) auto-merge fine on green.
