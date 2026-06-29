## Summary

<!-- What does this PR change, and why? One logical change per PR. -->

## Component(s) touched

<!-- Path filters mean you only trigger the relevant CI jobs. Tick what applies. -->

- [ ] `engine/` — OSS core engine (Python)
- [ ] `revit-addin/` — Revit desktop add-in (C# / .NET)
- [ ] `ios-app/` — iPhone capture app + `CaElevationKit` (Swift)
- [ ] `docs/` / CI / tooling / repo meta

## Type of change

- [ ] Feature / new capability
- [ ] Fix
- [ ] Refactor (no behaviour change)
- [ ] Tests / fixtures
- [ ] Docs
- [ ] CI / build / tooling

## Checklist

<!-- See CONTRIBUTING.md. Mirror CI locally before pushing. -->

- [ ] CI is green for the component(s) I touched (lint, format, type-check, tests).
- [ ] New capability ships **together** with its registry entry, fixture, and golden case (design principle #2).
- [ ] Pure/deterministic logic stays separate from platform-coupled IO (design principle #7).
- [ ] I did not hand-edit fixtures or goldens; any change was produced by re-running the seeders / `regen_fixtures.py`.
- [ ] Docs updated where relevant (README freshness guard, `docs/`).

## Fixture / golden changes

<!-- A changed golden MUST be intentional and explained. If regen produced an
     unexpected diff, treat it as a regression, not a fixture update.
     Write "None" if no fixtures or goldens changed. -->

None

## Testing

<!-- How was this verified? Note the tier(s): headless unit / integration (golden)
     / live-gated. Live/gated results are attested separately and are not a merge
     gate — link or summarise them here if relevant. -->

## Notes for reviewers

<!-- Anything that helps review: trade-offs, follow-ups, areas to scrutinise. -->
