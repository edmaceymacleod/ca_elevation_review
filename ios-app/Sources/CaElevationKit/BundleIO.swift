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
}

/// Canonical filenames inside the two bundle directories.
public enum BundleIO {
    public static let manifestFileName = "manifest.json"
    public static let captureFileName = "capture.json"

    // MARK: - JSON coders

    /// A decoder with no key strategy: the Codable types carry explicit
    /// snake_case CodingKeys, so the on-disk JSON matches the schema exactly.
    public static func makeDecoder() -> JSONDecoder {
        JSONDecoder()
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

    /// Resolve a floorplan image's relative path to an absolute URL in the bundle.
    public static func floorplanURL(for level: Level, in bundleDirectory: URL) -> URL {
        bundleDirectory.appendingPathComponent(level.floorplan.image)
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
        let destination = directory.appendingPathComponent(relativePath)
        try FileManager.default.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: destination, options: .atomic)
        return relativePath
    }

    // MARK: - Helpers

    private static func requireFile(_ relativePath: String, relativeTo directory: URL) throws {
        let url = directory.appendingPathComponent(relativePath)
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw BundleIOError.missingReferencedFile(relativePath: relativePath)
        }
    }
}
