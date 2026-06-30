import XCTest
@testable import CaElevationKit
import CaElevationFixtures

/// End-to-end coverage that BundleIO rejects structurally-decodable but
/// schema-invalid payloads at BOTH read boundaries (capture + manifest), so a
/// future regression dropping a `validate()` call is caught here.
final class ValidationIOTests: XCTestCase {
    private func makeTempDir() throws -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-val-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    func testReadCapturePackageRejectsMalformedPose() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        // Structurally valid JSON whose pose has 15 elements, not 16.
        let badJSON = """
        {
          "schema_version": "1.0.0",
          "project_id": "proj-001",
          "shots": [
            {
              "id": "s1",
              "level_id": "L1",
              "rgb_image": "a.jpg",
              "intrinsics": { "fx": 1, "fy": 1, "cx": 0, "cy": 0, "width": 1, "height": 1 },
              "pose": [1,0,0,0,1,0,0,0,1,0,0,0,0,0,0],
              "pin": { "x": 0, "y": 0, "heading": 0 }
            }
          ]
        }
        """
        try Data(badJSON.utf8).write(to: dir.appendingPathComponent("capture.json"))

        XCTAssertThrowsError(try BundleIO.readCapturePackage(from: dir)) { error in
            guard case BundleValidationError.poseWrongLength(let count) = error else {
                return XCTFail("expected poseWrongLength, got \(error)")
            }
            XCTAssertEqual(count, 15)
        }
    }

    // Mirror for the manifest read: an empty `levels` array decodes fine but the
    // schema forbids it (minItems:1). Guards the `try manifest.validate()` call
    // in readManifest against future removal. `validateReferencedFiles: false`
    // so the (empty-levels) manifest never reaches the floorplan file check.
    func testReadManifestRejectsEmptyLevels() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let badJSON = """
        {
          "schema_version": "1.0.0",
          "project": { "id": "proj-001", "name": "Demo", "units": "feet" },
          "levels": [],
          "devices": []
        }
        """
        try Data(badJSON.utf8).write(to: dir.appendingPathComponent("manifest.json"))

        XCTAssertThrowsError(
            try BundleIO.readManifest(from: dir, validateReferencedFiles: false)
        ) { error in
            guard case BundleValidationError.emptyLevels = error else {
                return XCTFail("expected emptyLevels, got \(error)")
            }
        }
    }
}
