# CI / GitHub Actions

**One workflow, one gate.** `.github/workflows/ci.yml` always runs (no top-level
path filter). A `changes` job ([dorny/paths-filter]) decides which component
jobs execute; a final **`all-green`** job waits for them all and is the single
required check. This avoids the "required check stuck pending forever" trap that
path-filtered required checks hit (a check that never runs blocks the merge).

## Jobs

| Job | Runs when changed | Runner | Gates `all-green`? |
|---|---|---|---|
| `changes` | always | ubuntu | n/a (detector) |
| `engine (py3.10/3.11/3.12)` | `engine/**` | ubuntu | **yes** |
| `pyrevit floor (py3.8/3.9)` | `pyrevit-extension/**`, `engine/**` | ubuntu | **yes** |
| `pyrevit engine (py3.10/3.11/3.12)` | `pyrevit-extension/**`, `engine/**` | ubuntu | **yes** |
| `validate schemas + fixtures` | schemas / `engine/fixtures/**` / validator | ubuntu | **yes** |
| `CaElevationKit (macos)` | `ios-app/**` | macos | **yes** (SwiftLint gates via baseline) |
| `CaElevationReview app (macos)` | `ios-app/**` | macos | **yes** (XcodeGen + `xcodebuild` App target) |
| `revit-addin (windows)` | `revit-addin/**` | windows | **no** (Revit API absent on runners) |
| `gitleaks` | always | ubuntu | **yes** |
| `all-green` | always | ubuntu | **the required check** |

A change to `ci.yml` itself triggers every component job. `gitleaks` and
`changes` have no filter, so they run on every push/PR. A component job that
isn't selected is **skipped**, which `all-green` treats as passing.

## What is linted / type-checked

- **Engine (Python):** `ruff check` + `ruff format --check` + **`mypy` (blocking)** + pytest, on 3.10/3.11/3.12.
- **pyRevit lib (Python):** `ruff check` + `ruff format --check` + `mypy` at the **py38 floor** (3.8/3.9), plus the full suite on 3.10/3.11/3.12 with the engine installed (incl. the real-CLI integration test).
- **Swift:** `swift build`/`swift test` of `CaElevationKit` **block**; **SwiftLint** **gates** against a committed baseline (`ios-app/.swiftlint-baseline.json`) — pre-existing violations are absorbed, so only **new** violations fail the build. When no baseline is committed, the step generates one, uploads it as the `swiftlint-baseline` artifact, and fails: download it, commit to `ios-app/.swiftlint-baseline.json`, and re-run. Regenerate on a Mac with `cd ios-app && swiftlint lint --config .swiftlint.yml --write-baseline .swiftlint-baseline.json`. Separately, the **App target** is generated with XcodeGen and built via `xcodebuild` for the iOS Simulator (signing disabled) so **`actool` compiles `Assets.xcassets`** — this catches invalid `AppIcon`/`AccentColor` and app-layer compile errors the kit-only job misses. Build-only: the LiDAR capture path can't run in the Simulator, so nothing is launched or tested on-device.
- **C#:** `dotnet format --verify` + build/test run **non-blocking** (no Revit API assemblies on hosted runners).

## Branch protection (the one setting to flip)

Under **Settings → Branches → Branch protection rule** for the default branch,
add exactly one required status check:

```
CI / all-green
```

That's it. `all-green` always runs and only goes green when every *gating* job
that ran passed (skipped = fine; `revit-addin` is non-gating). No path-filter
pending-forever problem, no need to list individual matrix legs.

[dorny/paths-filter]: https://github.com/dorny/paths-filter
