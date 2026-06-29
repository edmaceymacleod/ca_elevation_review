# CA Elevation Review — Revit C# add-in

The desktop component of the **As-Built Elevation Verification Tool**: the front door,
spec source, and result sink. It is one of three components in the repo (iPhone capture
app, CPython engine, this Revit add-in); see [`../docs/design.md`](../docs/design.md) for
the full architecture.

This add-in:

1. **Extracts the spec manifest** (expected devices + floorplans + plan→model transforms)
   from the live Revit model and writes a **field bundle** to hand to the capture app.
2. **Invokes the CPython engine out-of-process** on a returned capture package.
3. **Writes verdicts back** into the model (colors devices by pass/flag/absent/type-mismatch).
4. **Opens the issuable report**.

It is deliberately thin and platform-coupled where it touches Revit, with all pure logic
(serialization, process invocation, argument building, mapping) factored out so it is
unit-testable with no Revit session — per the design doc's "separation of pure logic from
platform-coupled code" rule.

## The internal seam

The add-in only ever exchanges two JSON payloads with the engine, each validated against a
JSON Schema in [`../engine/src/ca_elevation_engine/schemas/`](../engine/src/ca_elevation_engine/schemas/):

- **Spec manifest** (`spec_manifest.schema.json`) — what the add-in *writes*. DTOs:
  [`src/CaElevationReview.Addin/Manifest/SpecManifestModels.cs`](src/CaElevationReview.Addin/Manifest/SpecManifestModels.cs).
- **Verdict report** (`verdict_report.schema.json`) — what the engine *returns*. DTOs:
  [`src/CaElevationReview.Addin/Verdict/VerdictReportModels.cs`](src/CaElevationReview.Addin/Verdict/VerdictReportModels.cs).

The C# DTOs mirror these schemas field-for-field (snake_case JSON names pinned with
`[JsonPropertyName]`). Round-trip tests guard against drift.

## Revit version targets

Multi-targeted so one build covers the supported years:

| Revit year | .NET runtime      | TFM               |
|------------|-------------------|-------------------|
| 2024       | .NET Framework 4.8| `net48`           |
| 2025       | .NET 8 (Windows)  | `net8.0-windows`  |
| 2026       | .NET 8 (Windows)  | `net8.0-windows`  |
| 2027       | .NET 8 (Windows)  | `net8.0-windows`  |

The project file multi-targets `net48;net8.0-windows`. A `RevitVersion` MSBuild property
selects which Revit API reference assemblies to bind against (defaulting to 2024 for
`net48`, 2026 for `net8.0-windows`), and defines a `REVIT20xx` compile symbol so
platform-coupled code can branch on API differences per year. Build any year in range with
`-p:RevitVersion=<year>` (2024 on `net48`; 2025/2026/2027 on `net8.0-windows`).

## Building

There is **no .NET toolchain assumption baked in** beyond the .NET SDK and a local Revit
install. You build this on **Windows** with the Revit API assemblies present.

### Prerequisites

- .NET SDK 8.0+ (builds both TFMs; `net48` needs the .NET Framework 4.8 targeting pack).
- A local Revit install for the target year, providing `RevitAPI.dll` and `RevitAPIUI.dll`.

### Point the build at your Revit install

`RevitAPI.dll` / `RevitAPIUI.dll` are **not redistributable** — they are referenced from
your local install via the `RevitApiDir` MSBuild property (default
`C:\Program Files\Autodesk\Revit $(RevitVersion)`). They are referenced with
`<Private>false</Private>` so they are never copied into the output (copying would shadow
Revit's own and crash the add-in).

```powershell
# Build for Revit 2024 (net48):
dotnet build src\CaElevationReview.Addin\CaElevationReview.Addin.csproj `
  -c Release -f net48 -p:RevitVersion=2024 `
  -p:RevitApiDir="C:\Program Files\Autodesk\Revit 2024"

# Build for Revit 2027 (.NET 8):
dotnet build src\CaElevationReview.Addin\CaElevationReview.Addin.csproj `
  -c Release -f net8.0-windows -p:RevitVersion=2027 `
  -p:RevitApiDir="C:\Program Files\Autodesk\Revit 2027"
```

### Install into Revit

Copy `CaElevationReview.addin` into one of:

- `%ProgramData%\Autodesk\Revit\Addins\<year>\` (all users), or
- `%AppData%\Autodesk\Revit\Addins\<year>\` (current user)

and edit its `<Assembly>` path to point at the built `CaElevationReview.Addin.dll` for the
matching year/TFM. Replace the placeholder `<AddInId>` GUID with your own once before
release and keep it stable.

## How it invokes the Python engine (out-of-process)

The engine ships heavy native wheels (Open3D / pye57 / OpenCV) that are fragile to load
inside Revit's process, so the add-in runs it as a **child process** rather than embedding
it. The contract (from `engine/pyproject.toml` `[project.scripts]`):

```
ca-elevation run --manifest <manifest.json> --capture <capture_package> --out <dir>
# => writes <dir>/verdict_report.json
```

[`Engine/EngineRunner.cs`](src/CaElevationReview.Addin/Engine/EngineRunner.cs) builds that
invocation, launches it with `System.Diagnostics.Process`, streams stdout/stderr (for a
progress UI), and parses the resulting `verdict_report.json`.
[`Engine/EngineLocator.cs`](src/CaElevationReview.Addin/Engine/EngineLocator.cs) finds the
CLI in this order:

1. An explicit path from add-in settings.
2. The `CA_ELEVATION_ENGINE` environment variable (canonical; the legacy
   `CA_ELEVATION_CLI` name is still accepted as a deprecated alias).
3. A venv bundled next to the add-in DLL (`./engine-venv/Scripts/...`).
4. The bare `ca-elevation` console script on `PATH`.

So a packaged installer can ship a bundled engine venv, while a developer can just
`pip install ca-elevation-engine` and rely on the `PATH` fallback.

## Dev / live-test split

Mirrors the design doc's tiered testing discipline:

- **Headless unit tests** ([`tests/CaElevationReview.Tests`](tests/CaElevationReview.Tests))
  cover only the pure logic — manifest/verdict serialization round-trips, engine argument
  building, CLI locator resolution. They reference **no Revit API**, single-target
  `net8.0`, and run on any CI box (Linux/macOS/Windows) with no Revit install:

  ```bash
  dotnet test tests/CaElevationReview.Tests/CaElevationReview.Tests.csproj
  ```

  The test project links in only the platform-agnostic source files (it does not
  `ProjectReference` the add-in, which needs the absent Revit assemblies).

- **Live tests** (the add-in against a real Revit install) are gated and largely manual —
  they require the Revit license/install and a sample model fixture, and never block unit
  CI. The Revit-coupled code paths are marked with `// TODO:` where a live Revit reference
  is required to complete the implementation (model collection, view/image export,
  override-graphics write-back, file dialogs).

## Layout

```
revit-addin/
├─ CaElevationReview.sln
├─ CaElevationReview.addin            # Revit Application add-in manifest (placeholder GUID)
├─ .editorconfig                      # C# formatting for `dotnet format`
├─ src/CaElevationReview.Addin/
│  ├─ CaElevationReview.Addin.csproj  # multi-target net48;net8.0-windows
│  ├─ App.cs                          # IExternalApplication: ribbon panel + 3 buttons
│  ├─ Commands/
│  │  ├─ ExportFieldBundleCommand.cs  # scope → extract → write bundle
│  │  ├─ ImportCapturesCommand.cs     # run engine out-of-process → write-back verdicts
│  │  ├─ GenerateReportCommand.cs     # open the generated report
│  │  └─ Support/LastRun.cs           # shared session state (last report path)
│  ├─ Manifest/
│  │  ├─ SpecManifestModels.cs        # DTOs mirroring spec_manifest.schema.json
│  │  └─ SpecManifestExtractor.cs     # FilteredElementCollector walk (Revit calls stubbed)
│  ├─ Verdict/
│  │  ├─ VerdictReportModels.cs       # DTOs mirroring verdict_report.schema.json
│  │  └─ VerdictWriteback.cs          # override-graphics coloring by verdict (stubbed)
│  └─ Engine/
│     ├─ EngineRunner.cs              # real out-of-process invocation + report parse
│     └─ EngineLocator.cs             # CLI resolution (explicit/env/bundled/PATH)
└─ tests/CaElevationReview.Tests/     # headless xUnit tests (no Revit)
```

## License

Apache-2.0, consistent with the rest of the repo.
