//
//  WriteBack.swift
//  CaElevationApp
//
//  Phase 2 of the OneDrive round trip (feature-flagged via
//  `FeatureFlags.writeBackToRoot`). After a capture session is exported to a
//  local package directory and handed to the share sheet, this ALSO copies that
//  package back into the user's library-root folder so OneDrive uploads it and
//  the desktop add-in picks it up automatically — no manual AirDrop step.
//
//  The share-sheet export stays the unconditional fallback (CoverageView); this
//  only adds the write-back. We deliberately say "saved to folder", never
//  "synced": the actual OneDrive upload is async and outside our control, so the
//  most we can honestly promise is that the bytes landed in the synced folder.
//
//  Why coordinated IO: the destination lives in a File Provider folder. A raw
//  `copyItem` can race the provider or write into a placeholder; routing the
//  copy through `NSFileCoordinator.coordinate(writingItemAt:options:)` lets the
//  system serialize against the provider and start the upload. These calls block
//  on disk/network, so callers MUST run `run(...)` off the main actor.
//

import Foundation
import CaElevationKit
#if canImport(OSLog)
import OSLog
#endif

enum WriteBack {
    /// Subfolder, created under each project directory, where synced capture
    /// packages land so the desktop finds them next to the field bundle. Named
    /// constant so the app (and any docs describing the layout) stay in sync.
    static let exportsDirectoryName = "Exports"

    /// User-facing message when the local export succeeded but the write-back
    /// to the synced folder did not (offline / provider error / root lost). The
    /// share sheet is still up, so the operator has a working fallback.
    static let failureMessage = "Saved locally; couldn't sync to folder — use Share"

    /// Outcome of a write-back attempt, in a `Sendable`-safe form so it can cross
    /// back from the detached IO task to the `@MainActor` UI without carrying a
    /// non-`Sendable` `Error`.
    enum Outcome: Sendable, Equatable {
        /// Package copied into the library; `folderName` is the new subfolder.
        case saved(folderName: String)
        /// Write-back failed; the local export + share sheet remain the fallback.
        case failed
    }

    /// Copy the already-built local capture package into the library folder,
    /// logging the outcome, and never throwing — the caller's export-success
    /// path must not be blocked by a sync failure.
    ///
    /// Blocks on coordinated / network IO; run it OFF the main actor.
    ///
    /// - Parameters:
    ///   - localPackageDirectory: the finished package on local disk (Documents).
    ///   - projectDirectory: the opened project's folder inside the library root
    ///     (`session.bundleDirectory`). The package is copied into its `Exports`
    ///     subfolder.
    ///   - libraryRoot: the security-scoped library root the provider granted us;
    ///     its scope is (re)held for the duration of the write.
    static func run(
        localPackageDirectory: URL,
        projectDirectory: URL,
        libraryRoot: URL
    ) -> Outcome {
        do {
            let destination = try copyPackageToLibrary(
                localPackageDirectory: localPackageDirectory,
                projectDirectory: projectDirectory,
                libraryRoot: libraryRoot
            )
            log(info: "saved capture package to folder: \(destination.lastPathComponent)")
            return .saved(folderName: destination.lastPathComponent)
        } catch {
            log(error: "write-back failed: \(error.localizedDescription)")
            return .failed
        }
    }

    /// The throwing core: resolve the destination (reusing BundleIO's path-escape
    /// guard), then copy under a single write coordination. Separated from
    /// `run(...)` so the path/copy logic is exercised directly if ever tested.
    @discardableResult
    static func copyPackageToLibrary(
        localPackageDirectory: URL,
        projectDirectory: URL,
        libraryRoot: URL
    ) throws -> URL {
        // Hold the root's security scope for the whole write. ProjectLibrary
        // already holds it for the session, but re-acquiring here is balanced
        // and makes the write self-contained even if that hold ever lapses.
        let scoped = libraryRoot.startAccessingSecurityScopedResource()
        defer { if scoped { libraryRoot.stopAccessingSecurityScopedResource() } }

        // Destination: <projectDirectory>/Exports/<yyyyMMdd-HHmmss>-<shortUUID>/.
        // Built as a relative subpath and resolved through BundleIO's traversal
        // guard rather than a raw appendingPathComponent, so the destination is
        // proven to stay inside the project directory.
        let folderName = "\(timestampStamp())-\(shortUUID())"
        let relativePath = "\(exportsDirectoryName)/\(folderName)"
        let destination = try BundleIO.resolvedURL(forRelativePath: relativePath, in: projectDirectory)

        let coordinator = NSFileCoordinator()
        var coordinatorError: NSError?
        var copyError: Error?
        coordinator.coordinate(
            writingItemAt: destination,
            options: [.forReplacing],
            error: &coordinatorError
        ) { resolved in
            do {
                let fm = FileManager.default
                // Create intermediate dirs (the `Exports` folder) under
                // coordination, in case this is the project's first write-back.
                try fm.createDirectory(
                    at: resolved.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                // .forReplacing means we may replace an existing item; clear any
                // stale directory so copyItem (which refuses an existing target)
                // succeeds. Collisions are near-impossible given the UUID, but a
                // retry of the same export should overwrite cleanly.
                if fm.fileExists(atPath: resolved.path) {
                    try fm.removeItem(at: resolved)
                }
                try fm.copyItem(at: localPackageDirectory, to: resolved)
            } catch {
                copyError = error
            }
        }
        if let coordinatorError { throw coordinatorError }
        if let copyError { throw copyError }
        return destination
    }

    // MARK: - Naming

    /// `yyyyMMdd-HHmmss` in the device's local time — a human-sortable folder
    /// name. Local (not UTC) so the operator recognizes it on the desktop.
    private static func timestampStamp(_ date: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return formatter.string(from: date)
    }

    /// First 8 chars of a fresh UUID — enough to disambiguate two exports in the
    /// same second without an unwieldy folder name.
    private static func shortUUID() -> String {
        String(UUID().uuidString.prefix(8))
    }

    // MARK: - Logging

    private static func log(info message: String) {
        #if canImport(OSLog)
        Log.bundle.info("WriteBack: \(message, privacy: .public)")
        #endif
    }

    private static func log(error message: String) {
        #if canImport(OSLog)
        Log.bundle.error("WriteBack: \(message, privacy: .public)")
        #endif
    }
}

// MARK: - Runtime flag resolution

extension FeatureFlags {
    /// The live flags, resolved from `UserDefaults` overrides keyed by flag name.
    ///
    /// Reading from `UserDefaults` (settable via a configuration profile, a debug
    /// toggle, or a launch argument) is what makes the risky write-back path
    /// flippable WITHOUT a rebuild — the instant-rollback requirement in
    /// `../../CLAUDE.md` rule 3. Absent keys fall back to the conservative
    /// (all-off) defaults.
    static func current(_ defaults: UserDefaults = .standard) -> FeatureFlags {
        let flagNames = [
            "multiShotSweep",
            "meshReconstruction",
            "verboseCaptureLogging",
            "writeBackToRoot",
        ]
        var overrides: [String: Bool] = [:]
        for name in flagNames where defaults.object(forKey: name) != nil {
            overrides[name] = defaults.bool(forKey: name)
        }
        return .resolved(overrides: overrides)
    }
}
