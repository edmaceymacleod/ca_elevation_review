# CI / GitHub Actions

Six workflows, each **path-filtered** so a PR runs only the jobs for the
components it touches (except `secret-scan`, which always runs).

| Workflow | Trigger paths | Runner | Gates? | Check name(s) |
|---|---|---|---|---|
| `engine` | `engine/**` | ubuntu | **yes** | `engine (py3.10)`, `engine (py3.11)`, `engine (py3.12)` |
| `pyrevit-extension` | `pyrevit-extension/**`, `engine/**` | ubuntu | **yes** | `pyrevit-extension / all-green` (fan-in over the floor + engine legs) |
| `schema-validation` | schemas / `engine/fixtures/**` / the validator | ubuntu | **yes** | `validate schemas + fixtures` |
| `ios-app` | `ios-app/**` | macos | **yes** (build/test); SwiftLint non-blocking | `CaElevationKit (macos)` |
| `revit-addin` | `revit-addin/**` | windows | **no** (Revit API absent on runners) | `revit-addin (windows)` |
| `secret-scan` | **everything (no filter)** | ubuntu | **yes** | `gitleaks` |

## What is linted / type-checked

- **Engine (Python):** `ruff check` + `ruff format --check` + **`mypy` (blocking)** + pytest, on 3.10/3.11/3.12.
- **pyRevit lib (Python):** `ruff check` + `ruff format --check` + `mypy`, at the **py38** floor (3.8/3.9 floor jobs), plus the 3.10+ engine jobs.
- **Swift:** `swift build`/`swift test` of `CaElevationKit` **block**; **SwiftLint** runs but is **non-blocking** until confirmed clean on a Mac (then drop `continue-on-error` in `ios-app.yml`).
- **C#:** `dotnet format --verify` + build/test run but are **non-blocking** (no Revit API assemblies on hosted runners).

## Recommended required checks (branch protection)

Set under **Settings → Branches → Branch protection rule** for the default
branch. Recommended required checks:

- `secret-scan / gitleaks`
- `engine (py3.10)`, `engine (py3.11)`, `engine (py3.12)`
- `pyrevit-extension / all-green`
- `validate schemas + fixtures`
- `CaElevationKit (macos)`

Do **not** require `revit-addin (windows)` — it is intentionally non-blocking.

### ⚠️ The path-filter gotcha (read before requiring checks)

GitHub treats a **required** check that **doesn't run** as *pending*, which
**blocks the merge forever**. Because these workflows are path-filtered, a
docs-only PR never triggers `engine (py3.10)` etc., so requiring them would wedge
unrelated PRs at "Expected — waiting for status."

Two ways to handle it:

1. **Require only `secret-scan / gitleaks`** (the one workflow with no path
   filter) as the always-on gate, and rely on the component checks running +
   review for everything else. Simple, no false-wedge, but component tests don't
   strictly gate.
2. **Refactor to a single always-running gate** (recommended for real
   enforcement): one `ci.yml` with a `dorny/paths-filter` "changes" job that
   decides which component jobs run, ending in one `all-green` job that **always**
   runs and is the sole required check. This gives true gating without the
   pending-forever problem. Not yet implemented — ask and it's a quick follow-up.

Until option 2 lands, option 1 is the safe default.
