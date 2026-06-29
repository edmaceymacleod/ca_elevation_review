# UI conventions — look and feel

How the iPhone capture app (`ios-app/`) looks and why. This is a **policy doc**,
not a brand book: it records the design decisions that are deliberately *not*
encoded in a heavyweight design system, so a contributor (or Claude) building a
new screen knows what to reach for and what to leave alone.

Scope: the SwiftUI app layer in `ios-app/Sources/CaElevationApp/`. The pure
`CaElevationKit` library has no UI and is out of scope. The engine and the Revit
front door render their own report (`docs/design.md`) and are unrelated to this.

---

## The one rule: native-default by policy

**The app inherits Apple's design language. We do not invent our own.**

The app is a *deliberately thin sensor client* (`ios-app/CLAUDE.md`, design doc
§"iPhone capture app"): load a bundle, pin location + heading, capture RGB +
LiDAR depth + ARKit pose, export. There are no dashboards, no charts, no report
rendering — that value lives in the engine. With so little UI surface, a custom
theme would be cost without payoff. So:

- **Spend the design budget on capture-workflow clarity, not chrome.** The screen
  that matters is "what have I captured / what's still missing" (`CoverageView`),
  not a styled splash.
- **Lean on system semantics.** Stock SwiftUI gives us Dark Mode, Dynamic Type,
  accessibility, and correct platform feel for free. Every one of those is a
  feature a field tool needs and none is worth re-implementing.

When in doubt, do what a stock Apple app would do.

---

## Typography

Semantic system fonts only. Use the role, never a hardcoded size, so Dynamic
Type scales the UI for a user who needs larger text on a bright site.

- Titles / section headers → `.headline`, `.title2`
- Body → default
- Secondary / metadata → `.subheadline`, `.caption`
- Monospaced IDs / coordinates → `.caption.monospaced()` (already used for pin
  coordinates in `PlacePinView` and shot IDs in `CoverageView`)

Avoid `.font(.system(size:))` except for large glyph-style decoration (the empty-
state icon in `ProjectListView` is the one current example). No custom fonts.

## Color

Color carries **meaning**, not branding. Two distinct uses, kept separate:

1. **Semantic neutrals** — `.secondary` / `.primary` for hierarchy, never a
   hardcoded grey. De-emphasized labels are `.foregroundStyle(.secondary)`.
2. **Status encoding** — color tells the operator the state of a capture. Keep
   these meanings stable across screens:
   - **Green** = captured / done (`CoverageView` capture checkmarks).
   - **Floorplan pin markers** encode *role* via an SF Symbol + tint, not device
     type (`PinMarker` in `CoverageView`): **blue `camera.fill`** = a captured
     camera shot's position; **red `mappin.circle.fill`** = the operator's "where
     you stood" location pin. Don't repurpose either color elsewhere (e.g. red as
     a generic error color) without checking these.
   - **Confidence** (low/medium/high) rides the stock `.segmented` picker in
     `PlacePinView`; don't color-code it.

The **accent / tint** is the app's one brand color — a blueprint field blue
defined as `AccentColor` in the asset catalog (see below). It is the global
SwiftUI tint, so `.borderedProminent` buttons and interactive controls pick it
up automatically. Do **not** hardcode it; reference the asset (or just rely on
the default tint) so light/dark variants resolve correctly.

## Controls & navigation

Stock components, modern idioms (`ios-app/CLAUDE.md` §"Targets & toolchain"):

- `NavigationStack` + `navigationDestination` (iOS 17 floor exists partly for
  `navigationDestination(item:)`).
- `.borderedProminent` for the primary action on a screen; plain/bordered for
  secondary.
- `.segmented` and `.menu` pickers as already used — don't build custom pickers.
- **SF Symbols** for all iconography (`Image(systemName:)`). Free, consistent,
  auto-adapting to weight and Dynamic Type. No bespoke icon assets except the app
  icon.
- `@Observable` / value types for new view models, per the kit/app rules. No
  force-unwraps in view code.

## Field-use constraints (why the above is non-negotiable)

The app is used one-handed, walking a site, often in poor light. That sets hard
requirements that the native-default policy happens to satisfy:

- **Glanceable state.** The operator needs to see "what's left to capture" at a
  glance — that is literally `CoverageView`'s job. Favor big, legible status over
  density.
- **Large tap targets.** Stock control sizing already meets Apple's hit-target
  guidance; don't shrink it.
- **Orientation.** The app supports portrait + both landscapes (`project.yml`),
  because you frame a wall in whatever orientation fits it. Layouts must not
  assume portrait.
- **iPhone only.** `TARGETED_DEVICE_FAMILY = 1`; don't add iPad-specific layout.
- **Dark Mode + Dynamic Type are real.** Because color is semantic and fonts are
  roles, both work with no extra effort — keep it that way.

---

## Branding assets

Live in `ios-app/Sources/CaElevationApp/Assets.xcassets/` (compiled into the app
target; `project.yml` names them via `ASSETCATALOG_COMPILER_APPICON_NAME` and
`ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME`).

- **`AccentColor`** — blueprint field blue with light/dark variants:
  - Light: sRGB `#1C6DD0` (0.110, 0.427, 0.816)
  - Dark: sRGB `#4D9BFF` (0.302, 0.608, 1.000)
- **`AppIcon`** — a single 1024×1024 universal icon. **Currently a placeholder:**
  a framing reticle on blueprint navy, evoking "frame the wall to capture." It is
  intentionally obvious as a placeholder so it isn't mistaken for final art.

To change the accent, edit `AccentColor.colorset/Contents.json` (and update the
hex values listed above). To replace the icon, drop a final 1024×1024 PNG over
`AppIcon.appiconset/AppIcon-1024.png` (keep it 1024², no alpha — iOS masks the
corners). The catalog lives under the target's `sources:` path in `project.yml`,
so `xcodegen generate` compiles it automatically — never hand-edit the
`.xcodeproj` (`ios-app/CLAUDE.md` rule 1).

---

## Open questions (decide before v1 ship)

**Decided:**

- **App name — CA Elevation Review.** Settled in `docs/design.md` §"Open
  questions" and shipped as `CFBundleDisplayName` in `project.yml`. Listed here
  only as a pointer; the name is owned by the design doc. Final icon art can now
  proceed against it.
- **Accent shade — blueprint field blue (locked).** The `AccentColor` values
  above (light `#1C6DD0`, dark `#4D9BFF`) are now the chosen brand blue, not a
  placeholder default. Change them only with a deliberate branding decision.

Still unresolved and intentionally *not* baked in yet:

- **Final app icon.** The committed icon is a placeholder (see above).
- **Launch screen.** `project.yml` ships an empty `UILaunchScreen: {}` (system
  default). Decide whether a branded launch screen is worth it — by this doc's
  policy, probably not until there's a final icon.

This doc owns only the look-and-feel decisions (icon, launch screen, accent
shade) — when one is settled, record it here and delete it from this list.
Decisions owned elsewhere (the app name lives in `docs/design.md`) get resolved
there; this list only points at them.
