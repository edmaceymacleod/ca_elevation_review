import XCTest
@testable import CaElevationKit
import CaElevationFixtures

final class CapturePackageTests: XCTestCase {
    func testEncodeRoundTrip() throws {
        let original = Fixtures.capturePackage()
        let encoder = BundleIO.makeEncoder()
        let decoder = BundleIO.makeDecoder()

        let data = try encoder.encode(original)
        let decoded = try decoder.decode(CapturePackage.self, from: data)
        XCTAssertEqual(original, decoded)
    }

    func testEncodedJSONUsesSnakeCaseKeys() throws {
        let data = try BundleIO.makeEncoder().encode(Fixtures.capturePackage())
        let json = try XCTUnwrap(String(bytes: data, encoding: .utf8))

        // Spot-check the wire field names match the engine schema exactly.
        XCTAssertTrue(json.contains("\"schema_version\""))
        XCTAssertTrue(json.contains("\"project_id\""))
        XCTAssertTrue(json.contains("\"device_model\""))
        XCTAssertTrue(json.contains("\"rgb_image\""))
        XCTAssertTrue(json.contains("\"depth_map\""))
        XCTAssertTrue(json.contains("\"depth_size\""))
        XCTAssertTrue(json.contains("\"level_id\""))
        XCTAssertFalse(json.contains("\"rgbImage\""))

        // Guard the fixture stays RICH: these only reach the wire because the
        // shared sample populates point_cloud + a full observation. If a future
        // edit un-enriches it, the kit<->engine cross-check silently loses
        // coverage of these keys -- fail here instead.
        XCTAssertTrue(json.contains("\"point_cloud\""))
        XCTAssertTrue(json.contains("\"observations\""))
        XCTAssertTrue(json.contains("\"detected_type\""))
        XCTAssertTrue(json.contains("\"type_confidence\""))
        XCTAssertTrue(json.contains("\"facing_angle\""))
        XCTAssertTrue(json.contains("\"mounting_height\""))
    }

    func testPoseHasSixteenElements() {
        XCTAssertEqual(Fixtures.capturePackage().shots[0].pose.count, 16)
    }

    func testWriteAndReadPackageDirectory() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-pkg-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }

        let package = Fixtures.capturePackage()
        // Stage every media file the shot references (rgb + depth + cloud), then
        // write the JSON. The shared fixture references all three, so all three
        // must exist or writeCapturePackage's fail-closed validation throws.
        let shot = package.shots[0]
        try BundleIO.stageMedia(Data("jpeg".utf8), relativePath: shot.rgbImage, in: dir)
        try BundleIO.stageMedia(Data("depth".utf8), relativePath: shot.depthMap!, in: dir)
        try BundleIO.stageMedia(Data("ply".utf8), relativePath: shot.pointCloud!, in: dir)

        let url = try BundleIO.writeCapturePackage(package, to: dir)
        XCTAssertTrue(FileManager.default.fileExists(atPath: url.path))

        let readBack = try BundleIO.readCapturePackage(from: dir)
        XCTAssertEqual(readBack, package)
    }

    func testWriteThrowsWhenReferencedMediaMissing() {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-pkg-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }

        // No media staged -> validation must fail closed.
        let package = Fixtures.capturePackage()
        XCTAssertThrowsError(try BundleIO.writeCapturePackage(package, to: dir)) { error in
            guard case BundleIOError.missingReferencedFile = error else {
                return XCTFail("expected missingReferencedFile, got \(error)")
            }
        }
    }
}
