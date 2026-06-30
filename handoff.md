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

## Next steps

1. **Local-SwiftLint parity (small; auto-merges — touches no workflow file).**
   - Add **`.gitattributes`** forcing LF for sources. The repo has none, so Windows
     checkouts are CRLF and `swiftlint` throws false `comma` / `trailing_newline`
     on EVERY file (vs CI's LF). After adding it run `git add --renormalize .` so
     the working tree flips to LF.
   - Add **`ios-app/scripts/win-swiftlint.ps1`** mirroring `win-kit-test.ps1`:
     prepend the installer USER PATH (so `sourcekitdInProc.dll` loads) + set
     `SDKROOT`, then `swiftlint lint --strict --config .swiftlint.yml`.
   - `swiftlint.exe` **0.65.0** is already installed at
     `C:\Users\ed.macey-macleod\tools\swiftlint` (on the USER PATH). It needs the
     Swift toolchain on PATH (SourceKit) and LF line endings to match CI.
2. **(Optional) Promote the Windows leg to gating.** The kit already builds green
   on Windows; keep it informational until the *setup* (toolchain download /
   setup-swift / msvc-dev-cmd) is observed stable over several runs. To promote:
   add `ios_kit_windows` to `all-green`'s `needs:` **and** R-map in ONE commit and
   drop `continue-on-error`. (Narrow its trigger to `ios-app/**`, excluding
   `ci.yml`, so routine CI edits aren't gated on Swift-on-Windows availability.)

## Gotcha — merging CI PRs (verified 2026-06-30)

Any PR touching `.github/workflows/` can't be merged by the auto-merge bot OR the
local `gh` — the token scopes are `gist, read:org, repo` (no `workflow`). Use
`gh auth refresh -h github.com -s workflow` then `gh pr merge`, or merge in the
web UI. Non-workflow PRs (e.g. the `.gitattributes` follow-up, or #33) auto-merge
fine on green.
