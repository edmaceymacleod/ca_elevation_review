import XCTest
@testable import CaElevationKit
import CaElevationFixtures

final class FieldBundleTests: XCTestCase {
    /// A representative manifest JSON, snake_case exactly per the engine schema.
    private let manifestJSON = """
    {
      "schema_version": "1.0.0",
      "project": {
        "id": "proj-001",
        "name": "Demo Building",
        "revit_file": "Demo.rvt",
        "exported_at": "2026-06-28T12:00:00Z",
        "units": "feet"
      },
      "coordinate_system": { "name": "Survey", "north_angle": 12.5 },
      "default_tolerances": { "position": 0.5, "mounting_height": 0.25, "orientation": 10 },
      "levels": [
        {
          "id": "L1",
          "name": "Level 1",
          "elevation": 0.0,
          "floorplan": {
            "image": "plans/L1.png",
            "width_px": 2048,
            "height_px": 1536,
            "pixel_to_model": [0.01, 0.0, -5.0, 0.0, -0.01, 7.5]
          }
        }
      ],
      "devices": [
        {
          "id": "dev-1",
          "family": "Card Reader",
          "type": "HID-R10",
          "level_id": "L1",
          "elevation_id": "E-North",
          "position": { "x": 10.0, "y": 2.0, "z": 3.5 },
          "mounting_height": 3.5,
          "orientation": { "facing_angle": 90, "up_axis": "up" },
          "tolerances": { "position": 0.5 },
          "metadata": { "note": "near door", "rev": 2 }
        }
      ]
    }
    """

    func testDecodeManifest() throws {
        let data = Data(manifestJSON.utf8)
        let manifest = try BundleIO.makeDecoder().decode(SpecManifest.self, from: data)

        XCTAssertEqual(manifest.schemaVersion, "1.0.0")
        XCTAssertEqual(manifest.project.id, "proj-001")
        XCTAssertEqual(manifest.project.units, .feet)
        XCTAssertEqual(manifest.coordinateSystem?.northAngle, 12.5)
        XCTAssertEqual(manifest.levels.count, 1)

        let plan = manifest.levels[0].floorplan
        XCTAssertEqual(plan.image, "plans/L1.png")
        XCTAssertEqual(plan.widthPx, 2048)
        XCTAssertEqual(plan.pixelToModel, [0.01, 0.0, -5.0, 0.0, -0.01, 7.5])

        // The convenience affine evaluates the embedded coefficients.
        let (x, y) = plan.affine.modelXY(fromPixel: 100, 50)
        XCTAssertEqual(x, 0.01 * 100 - 5.0, accuracy: 1e-9)
        XCTAssertEqual(y, -0.01 * 50 + 7.5, accuracy: 1e-9)

        let device = manifest.devices[0]
        XCTAssertEqual(device.family, "Card Reader")
        XCTAssertEqual(device.orientation?.facingAngle, 90)
        XCTAssertEqual(device.orientation?.upAxis, .up)
        XCTAssertEqual(device.position, Point3(x: 10, y: 2, z: 3.5))
    }

    /// Encode the SHARED `Fixtures.specManifest()` (the exact value `cek-emit`
    /// emits for the kit<->engine schema cross-check) and round-trip it, so a
    /// malformed shared manifest fixture fails `swift test` here -- not only in
    /// the cross-language schema job.
    func testManifestFixtureRoundTrips() throws {
        let original = Fixtures.specManifest()
        let encoder = BundleIO.makeEncoder()
        let decoder = BundleIO.makeDecoder()

        let data = try encoder.encode(original)
        let roundTripped = try decoder.decode(SpecManifest.self, from: data)
        XCTAssertEqual(original, roundTripped)
    }

    func testManifestRoundTripPreservesValues() throws {
        let data = Data(manifestJSON.utf8)
        let decoder = BundleIO.makeDecoder()
        let encoder = BundleIO.makeEncoder()

        let original = try decoder.decode(SpecManifest.self, from: data)
        let reencoded = try encoder.encode(original)
        let roundTripped = try decoder.decode(SpecManifest.self, from: reencoded)

        XCTAssertEqual(original, roundTripped)
    }

    func testReadManifestFromDirectory() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        // Stage manifest + the floorplan it references.
        try Data(manifestJSON.utf8).write(to: dir.appendingPathComponent("manifest.json"))
        let planURL = dir.appendingPathComponent("plans/L1.png")
        try FileManager.default.createDirectory(
            at: planURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data("fake-png".utf8).write(to: planURL)

        let manifest = try BundleIO.readManifest(from: dir)
        XCTAssertEqual(manifest.project.id, "proj-001")
    }

    func testReadManifestThrowsOnMissingFloorplan() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        try Data(manifestJSON.utf8).write(to: dir.appendingPathComponent("manifest.json"))

        XCTAssertThrowsError(try BundleIO.readManifest(from: dir)) { error in
            guard case BundleIOError.missingReferencedFile(let path) = error else {
                return XCTFail("expected missingReferencedFile, got \(error)")
            }
            XCTAssertEqual(path, "plans/L1.png")
        }
    }

    func testResolvedURLRejectsParentTraversal() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        XCTAssertThrowsError(
            try BundleIO.resolvedURL(forRelativePath: "../escape.png", in: dir)
        ) { error in
            guard case BundleIOError.pathEscapesBundle(let path) = error else {
                return XCTFail("expected pathEscapesBundle, got \(error)")
            }
            XCTAssertEqual(path, "../escape.png")
        }

        XCTAssertThrowsError(
            try BundleIO.resolvedURL(forRelativePath: "plans/../../secret.png", in: dir)
        ) { error in
            guard case BundleIOError.pathEscapesBundle = error else {
                return XCTFail("expected pathEscapesBundle, got \(error)")
            }
        }
    }

    func testResolvedURLRejectsAbsolutePath() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        XCTAssertThrowsError(
            try BundleIO.resolvedURL(forRelativePath: "/etc/passwd", in: dir)
        ) { error in
            guard case BundleIOError.pathEscapesBundle = error else {
                return XCTFail("expected pathEscapesBundle, got \(error)")
            }
        }
    }

    func testResolvedURLAllowsContainedPath() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let url = try BundleIO.resolvedURL(forRelativePath: "plans/L1.png", in: dir)
        XCTAssertTrue(url.path.hasPrefix(dir.standardizedFileURL.path))
        XCTAssertTrue(url.path.hasSuffix("plans/L1.png"))
    }

    func testResolvedURLRejectsSymlinkEscape() throws {
        let fm = FileManager.default
        let dir = try makeTempDir()
        // A sibling directory OUTSIDE the bundle, holding a secret file.
        let outside = fm.temporaryDirectory
            .appendingPathComponent("cek-outside-\(UUID().uuidString)")
        try fm.createDirectory(at: outside, withIntermediateDirectories: true)
        try Data("secret".utf8).write(to: outside.appendingPathComponent("secret.png"))
        defer {
            try? fm.removeItem(at: dir)
            try? fm.removeItem(at: outside)
        }

        // Plant a symlink INSIDE the bundle that points at the outside dir. A
        // lexical containment check would accept "link/secret.png" (the string
        // stays under the bundle), but resolving the symlink escapes it.
        let link = dir.appendingPathComponent("link")
        try fm.createSymbolicLink(at: link, withDestinationURL: outside)

        XCTAssertThrowsError(
            try BundleIO.resolvedURL(forRelativePath: "link/secret.png", in: dir)
        ) { error in
            guard case BundleIOError.pathEscapesBundle = error else {
                return XCTFail("expected pathEscapesBundle, got \(error)")
            }
        }
    }

    func testStageMediaRejectsTraversal() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        XCTAssertThrowsError(
            try BundleIO.stageMedia(Data("x".utf8), relativePath: "../evil.bin", in: dir)
        ) { error in
            guard case BundleIOError.pathEscapesBundle = error else {
                return XCTFail("expected pathEscapesBundle, got \(error)")
            }
        }
    }

    private func makeTempDir() throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
}
