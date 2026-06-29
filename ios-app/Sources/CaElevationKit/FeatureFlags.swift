import Foundation

/// Run-time toggles for experimental / risky capture features.
///
/// Per the "feature-flag experimental code" rule (see `../../CLAUDE.md`): a path
/// that might have to be turned off without a rebuild lives behind a flag here,
/// not a hardcoded branch — so rollback is instant. Pure `Foundation`, so it is
/// unit-tested headlessly in `CaElevationKit`.
public struct FeatureFlags: Sendable, Equatable {
    /// Fill single-viewpoint occlusion gaps with a short multi-shot sweep.
    public var multiShotSweep: Bool
    /// Use ARKit scene-reconstruction mesh in addition to per-pixel depth.
    public var meshReconstruction: Bool
    /// Emit verbose `os.Logger` diagnostics from the capture pipeline.
    public var verboseCaptureLogging: Bool
    /// Phase 2 of the OneDrive round trip: after exporting a capture package,
    /// ALSO copy it back into the library root folder so the desktop picks it
    /// up automatically. The share-sheet export stays the unconditional
    /// fallback; this only adds the write-back. Risky (provider/network IO), so
    /// it is gated here for instant rollback (see `../../CLAUDE.md` rule 3).
    public var writeBackToRoot: Bool

    public init(
        multiShotSweep: Bool = false,
        meshReconstruction: Bool = false,
        verboseCaptureLogging: Bool = false,
        writeBackToRoot: Bool = false
    ) {
        self.multiShotSweep = multiShotSweep
        self.meshReconstruction = meshReconstruction
        self.verboseCaptureLogging = verboseCaptureLogging
        self.writeBackToRoot = writeBackToRoot
    }

    /// Conservative defaults: every experimental path is OFF.
    public static let `default` = FeatureFlags()

    /// Resolve flags from a `name -> bool` overrides map (e.g. parsed from launch
    /// arguments, a bundled JSON, or `UserDefaults`), falling back to defaults.
    /// Unknown keys are ignored so an old override file can't crash the app.
    public static func resolved(overrides: [String: Bool]) -> FeatureFlags {
        var flags = FeatureFlags.default
        if let value = overrides["multiShotSweep"] { flags.multiShotSweep = value }
        if let value = overrides["meshReconstruction"] { flags.meshReconstruction = value }
        if let value = overrides["verboseCaptureLogging"] { flags.verboseCaptureLogging = value }
        if let value = overrides["writeBackToRoot"] { flags.writeBackToRoot = value }
        return flags
    }
}
