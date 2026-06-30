//
//  BundleIO.swift
//  CaElevationKit
//
//  Read a field bundle from a directory; write a capture package to a
//  directory. Pure Foundation -- no UIKit / ARKit. This is the on-disk
//  contract for the local-first round trip (AirDrop / Files / iCloud): the
//  add-in writes a field-bundle directory, the phone reads it, the phone
//  writes a capture-package directory, the add-in reads it back.
//
//  Layout of a field bundle directory:
//      <bundle>/manifest.json          (SpecManifest)
//      <bundle>/<floorplan images...>  (paths are relative, per level.floorplan.image)
//
//  Layout of a capture package directory:
//      <package>/capture.json          (CapturePackage)
//      <package>/<rgb, depth, cloud...> (paths relative, per shot fields)
//
//  The model JSON is the source of truth for which media files belong to a
//  bundle; this IO layer only validates that referenced media exists.
//

import Foundation

/// Errors raised while reading or writing bundles on disk.
public enum BundleIOError: Error, Equatable, Sendable {
    case manifestNotFound(path: String)
    case captureNotFound(path: String)
    case missingReferencedFile(relativePath: String)
    case notADirectory(path: String)
    /// A referenced media/floorplan path escapes its bundle directory (absolute
    /// path, `..` traversal, or otherwise resolves outside `directory`).
    case pathEscapesBundle(relativePath: String)
}

/// Canonical filenames inside the two bundle directories.
public enum BundleIO {
    public static let manifestFileName = "manifest.json"
    public static let captureFileName = "capture.json"

    // MARK: - JSON coders

    /// A decoder with no key strategy: the Codable types carry explicit
    /// snake_case CodingKeys, so the on-disk JSON matches the schema exactly.
    ///
    /// A nesting-depth guard is installed so the untrusted free-form
    /// `device.metadata` (``JSONValue``) can't drive unbounded recursion and
    /// overflow the stack on a maliciously/accidentally over-nested manifest.
    public static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        JSONValue.installDepthGuard(on: decoder)
        return decoder
    }

    /// An encoder producing stable, human-diffable JSON (sorted keys, pretty).
    public static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return encoder
    }

    // MARK: - Reading a field bundle

    /// Read and decode the `SpecManifest` from a field-bundle directory.
    ///
    /// - Parameter directory: the bundle root containing `manifest.json`.
    /// - Parameter validateReferencedFiles: when `true`, verify each level's
    ///   floorplan image exists on disk; throws ``BundleIOError`` if not.
    public static func readManifest(
        from directory: URL,
        validateReferencedFiles: Bool = true
    ) throws -> SpecManifest {
        let manifestURL = directory.appendingPathComponent(manifestFileName)
        guard FileManager.default.fileExists(atPath: manifestURL.path) else {
            throw BundleIOError.manifestNotFound(path: manifestURL.path)
        }
        let data = try Data(contentsOf: manifestURL)
        let manifest = try makeDecoder().decode(SpecManifest.self, from: data)

        if validateReferencedFiles {
            for level in manifest.levels {
                try requireFile(level.floorplan.image, relativeTo: directory)
            }
        }
        return manifest
    }

    /// Enumerate the field bundles directly inside a library `root` directory.
    ///
    /// A "library root" is a folder (e.g. a OneDrive folder synced onto the
    /// phone) that holds one subfolder per project, each being a field bundle
    /// (`manifest.json` + its floorplan images). This lists the *immediate*
    /// subdirectories (non-recursive — a bundle is exactly one level down) that
    /// contain a `manifest.json`, sorted by name for stable ordering.
    ///
    /// This is deliberately cheap and does NOT decode the manifests or touch the
    /// floorplan images: callers decode lazily with ``readManifest(from:)`` only
    /// for the projects they show, which keeps it friendly to not-yet-downloaded
    /// (dataless) File Provider placeholders. It is pure Foundation so it is
    /// unit-tested headlessly.
    ///
    /// - Parameter root: the library directory to scan.
    /// - Returns: the bundle subdirectory URLs, sorted by last path component.
    public static func findBundles(in root: URL) throws -> [URL] {
        let fm = FileManager.default
        let entries = try fm.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )
        let bundles = entries.filter { url in
            let isDirectory = (try? url.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory ?? false
            guard isDirectory else { return false }
            let manifest = url.appendingPathComponent(manifestFileName)
            return fm.fileExists(atPath: manifest.path)
        }
        return bundles.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    /// Resolve a floorplan image's relative path to an absolute URL in the bundle.
    ///
    /// The floorplan path is untrusted (it comes from a decoded manifest), so it
    /// is validated to stay within `bundleDirectory`.
    ///
    /// - Throws: ``BundleIOError/pathEscapesBundle(relativePath:)`` if the path
    ///   escapes the bundle directory.
    public static func floorplanURL(for level: Level, in bundleDirectory: URL) throws -> URL {
        try resolvedURL(forRelativePath: level.floorplan.image, in: bundleDirectory)
    }

    // MARK: - Writing a capture package

    /// Write a `CapturePackage` and its referenced media into a directory.
    ///
    /// The package model already holds *relative* media paths (e.g.
    /// `shots/abc/rgb.jpg`); callers are responsible for having placed those
    /// media files via ``stageMedia(_:relativePath:in:)`` (or equivalent)
    /// before/after writing the JSON. This method writes `capture.json` and,
    /// when `validateReferencedFiles` is set, asserts every referenced media
    /// file is present so a malformed package fails here rather than in the
    /// field.
    ///
    /// - Returns: the URL of the written `capture.json`.
    @discardableResult
    public static func writeCapturePackage(
        _ package: CapturePackage,
        to directory: URL,
        validateReferencedFiles: Bool = true
    ) throws -> URL {
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        if validateReferencedFiles {
            for shot in package.shots {
                try requireFile(shot.rgbImage, relativeTo: directory)
                if let depth = shot.depthMap {
                    try requireFile(depth, relativeTo: directory)
                }
                if let cloud = shot.pointCloud {
                    try requireFile(cloud, relativeTo: directory)
                }
            }
        }

        let captureURL = directory.appendingPathComponent(captureFileName)
        let data = try makeEncoder().encode(package)
        try data.write(to: captureURL, options: .atomic)
        return captureURL
    }

    /// Read back a `CapturePackage` from a package directory (round-trip / tests).
    public static func readCapturePackage(from directory: URL) throws -> CapturePackage {
        let captureURL = directory.appendingPathComponent(captureFileName)
        guard FileManager.default.fileExists(atPath: captureURL.path) else {
            throw BundleIOError.captureNotFound(path: captureURL.path)
        }
        let data = try Data(contentsOf: captureURL)
        return try makeDecoder().decode(CapturePackage.self, from: data)
    }

    /// Stage a media payload (RGB JPEG, raw depth, point cloud) into a package
    /// directory at a relative path, creating intermediate directories. Returns
    /// the relative path to store in the corresponding `Shot` field.
    @discardableResult
    public static func stageMedia(
        _ data: Data,
        relativePath: String,
        in directory: URL
    ) throws -> String {
        let destination = try resolvedURL(forRelativePath: relativePath, in: directory)
        try FileManager.default.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: destination, options: .atomic)
        return relativePath
    }

    // MARK: - Helpers

    /// Safely resolve an untrusted relative media/floorplan path against a
    /// bundle directory, rejecting anything that escapes it.
    ///
    /// The relative paths come from decoded (potentially untrusted) bundle and
    /// capture JSON. This mirrors the Python sibling's guard in `bundle_io.py`:
    /// reject absolute paths and any `..` component, then standardize, resolve
    /// symlinks, and verify the resolved URL is contained within `directory`.
    ///
    /// - Returns: the resolved absolute URL. For paths whose existing components
    ///   are all contained in `directory` it is inside `directory`; symlinks
    ///   along the path that point outside are rejected (`resolvingSymlinksInPath`
    ///   only resolves *existing* components, so for not-yet-created write targets
    ///   the existing parent is what gets checked).
    /// - Throws: ``BundleIOError/pathEscapesBundle(relativePath:)`` on violation.
    ///
    /// Public so the app layer's write-back (which builds a destination *inside*
    /// the library root) reuses this exact traversal guard instead of bypassing
    /// it with a raw `appendingPathComponent`.
    public static func resolvedURL(forRelativePath relativePath: String, in directory: URL) throws -> URL {
        // Reject absolute paths and explicit parent-directory traversal outright.
        let components = relativePath.split(separator: "/", omittingEmptySubsequences: false)
        if relativePath.hasPrefix("/") || components.contains("..") {
            throw BundleIOError.pathEscapesBundle(relativePath: relativePath)
        }

        let base = directory.standardizedFileURL
        let resolved = base.appendingPathComponent(relativePath).standardizedFileURL

        // Defense in depth: confirm the target is contained within the base
        // directory. `standardizedFileURL` only normalizes `.`/`..` lexically; it
        // does NOT resolve symbolic links, so a symlink component (in an
        // attacker-influenced synced bundle) could otherwise pass the string
        // check while the real read/write follows the link outside the bundle.
        // We therefore resolve symlinks before the containment check below. Note
        // `resolvingSymlinksInPath()` resolves only existing components, so for a
        // not-yet-created write target the existing parent is what gets checked.
        let realBase = base.resolvingSymlinksInPath().standardizedFileURL

        // Containment check, made robust on Windows. `resolvingSymlinksInPath()`
        // canonicalizes a FULLY-existing path (e.g. expands the 8.3 short name
        // `ED0B62~1.MAC` -> `ed.macey-macleod`, or `RUNNER~1` -> `runneradmin` on
        // CI) but leaves a path with a not-yet-created tail unexpanded -- so
        // resolving `base` and `base/relativePath` INDEPENDENTLY produced
        // mismatched ancestors, and every contained path looked like an escape.
        // Anchor on the already-canonical `realBase`: build the candidate from it
        // (so the base portion matches), resolve symlinks for traversal safety
        // (a symlink pointing outside the bundle then no longer starts with
        // `realBase`), and compare by path COMPONENTS so a sibling like
        // ".../Bundle-evil" can't pass on a bare string prefix.
        let resolvedReal = realBase.appendingPathComponent(relativePath)
            .resolvingSymlinksInPath().standardizedFileURL
        guard resolvedReal.pathComponents.starts(with: realBase.pathComponents) else {
            throw BundleIOError.pathEscapesBundle(relativePath: relativePath)
        }
        return resolved
    }

    private static func requireFile(_ relativePath: String, relativeTo directory: URL) throws {
        let url = try resolvedURL(forRelativePath: relativePath, in: directory)
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw BundleIOError.missingReferencedFile(relativePath: relativePath)
        }
    }
}
