import XCTest
@testable import CaElevationKit

final class CapturePackageTests: XCTestCase {
    private func makePackage() -> CapturePackage {
        let shot = Shot(
            id: "shot-1",
            levelId: "L1",
            elevationId: "E-North",
            rgbImage: "shots/shot-1/rgb.jpg",
            depthMap: "shots/shot-1/depth.bin",
            depthSize: [192, 256],
            pointCloud: nil,
            intrinsics: Intrinsics(fx: 1450.2, fy: 1450.2, cx: 960, cy: 720, width: 1920, height: 1440),
            pose: [
                1, 0, 0, 1.5,
                0, 1, 0, 0.2,
                0, 0, 1, -3.0,
                0, 0, 0, 1
            ],
            pin: Pin(x: 512.5, y: 384.0, heading: 90, confidence: .high),
            capturedAt: "2026-06-28T12:34:56Z",
            observations: nil
        )
        return CapturePackage(
            schemaVersion: "1.0.0",
            projectId: "proj-001",
            capturedAt: "2026-06-28T12:35:00Z",
            deviceModel: "iPhone 15 Pro",
            appVersion: "0.1.0",
            shots: [shot]
        )
    }

    func testEncodeRoundTrip() throws {
        let original = makePackage()
        let encoder = BundleIO.makeEncoder()
        let decoder = BundleIO.makeDecoder()

        let data = try encoder.encode(original)
        let decoded = try decoder.decode(CapturePackage.self, from: data)
        XCTAssertEqual(original, decoded)
    }

    func testEncodedJSONUsesSnakeCaseKeys() throws {
        let data = try BundleIO.makeEncoder().encode(makePackage())
        let json = String(decoding: data, as: UTF8.self)

        // Spot-check the wire field names match the engine schema exactly.
        XCTAssertTrue(json.contains("\"schema_version\""))
        XCTAssertTrue(json.contains("\"project_id\""))
        XCTAssertTrue(json.contains("\"device_model\""))
        XCTAssertTrue(json.contains("\"rgb_image\""))
        XCTAssertTrue(json.contains("\"depth_map\""))
        XCTAssertTrue(json.contains("\"depth_size\""))
        XCTAssertTrue(json.contains("\"level_id\""))
        XCTAssertFalse(json.contains("\"rgbImage\""))
    }

    func testPoseHasSixteenElements() {
        XCTAssertEqual(makePackage().shots[0].pose.count, 16)
    }

    func testWriteAndReadPackageDirectory() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-pkg-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }

        var package = makePackage()
        // Stage the media the shot references, then write the JSON.
        let shot = package.shots[0]
        try BundleIO.stageMedia(Data("jpeg".utf8), relativePath: shot.rgbImage, in: dir)
        try BundleIO.stageMedia(Data("depth".utf8), relativePath: shot.depthMap!, in: dir)

        let url = try BundleIO.writeCapturePackage(package, to: dir)
        XCTAssertTrue(FileManager.default.fileExists(atPath: url.path))

        let readBack = try BundleIO.readCapturePackage(from: dir)
        package.shots[0].observations = nil
        XCTAssertEqual(readBack, package)
    }

    func testWriteThrowsWhenReferencedMediaMissing() {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cek-pkg-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }

        // No media staged -> validation must fail closed.
        XCTAssertThrowsError(try BundleIO.writeCapturePackage(makePackage(), to: dir)) { error in
            guard case BundleIOError.missingReferencedFile = error else {
                return XCTFail("expected missingReferencedFile, got \(error)")
            }
        }
    }
}
