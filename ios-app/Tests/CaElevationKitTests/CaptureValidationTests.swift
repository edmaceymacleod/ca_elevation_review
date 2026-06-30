import XCTest
@testable import CaElevationKit
import CaElevationFixtures

/// Adversarial decode/validate coverage for the CAPTURE package: payloads that
/// are structurally decodable but violate a schema constraint Codable cannot
/// express must be rejected by `validate()`. Mirrors
/// engine/src/ca_elevation_engine/schemas/capture_package.schema.json.
final class CaptureValidationTests: XCTestCase {
    // MARK: pose length (the TDD driver)

    func testPoseWrongLengthRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].pose = Array(repeating: 0.0, count: 15)
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.poseWrongLength(let count) = error else {
                return XCTFail("expected poseWrongLength, got \(error)")
            }
            XCTAssertEqual(count, 15)
        }
    }

    // MARK: pose over-length, intrinsics, depth, shots, semver, ids

    func testPoseOverLengthRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].pose = Array(repeating: 0.0, count: 17)
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.poseWrongLength(let count) = error else {
                return XCTFail("expected poseWrongLength, got \(error)")
            }
            XCTAssertEqual(count, 17)
        }
    }

    func testNonPositiveFxRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].intrinsics.fx = 0
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.nonPositiveIntrinsic(let field, _) = error else {
                return XCTFail("expected nonPositiveIntrinsic, got \(error)")
            }
            XCTAssertEqual(field, "fx")
        }
    }

    func testNonPositiveFyRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].intrinsics.fy = -1
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.nonPositiveIntrinsic(let field, _) = error else {
                return XCTFail("expected nonPositiveIntrinsic, got \(error)")
            }
            XCTAssertEqual(field, "fy")
        }
    }

    func testNonPositiveWidthRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].intrinsics.width = 0
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.nonPositiveIntrinsic(let field, _) = error else {
                return XCTFail("expected nonPositiveIntrinsic, got \(error)")
            }
            XCTAssertEqual(field, "width")
        }
    }

    func testNonPositiveHeightRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].intrinsics.height = -1
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.nonPositiveIntrinsic(let field, _) = error else {
                return XCTFail("expected nonPositiveIntrinsic, got \(error)")
            }
            XCTAssertEqual(field, "height")
        }
    }

    func testDepthSizeWrongLengthRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].depthSize = [192]
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.depthSizeWrongLength(let count) = error else {
                return XCTFail("expected depthSizeWrongLength, got \(error)")
            }
            XCTAssertEqual(count, 1)
        }
    }

    func testDepthSizeOverLengthRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].depthSize = [192, 256, 1]
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.depthSizeWrongLength(let count) = error else {
                return XCTFail("expected depthSizeWrongLength, got \(error)")
            }
            XCTAssertEqual(count, 3)
        }
    }

    func testDepthSizeSecondSlotNonPositiveRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].depthSize = [192, 0]
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.depthSizeNonPositive(let value) = error else {
                return XCTFail("expected depthSizeNonPositive, got \(error)")
            }
            XCTAssertEqual(value, 0)
        }
    }

    // First-slot coverage: proves the `for dimension in size` loop checks every
    // index, not just the second. A negative value also exercises `<= 0`.
    func testDepthSizeFirstSlotNegativeRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].depthSize = [-1, 256]
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.depthSizeNonPositive(let value) = error else {
                return XCTFail("expected depthSizeNonPositive, got \(error)")
            }
            XCTAssertEqual(value, -1)
        }
    }

    func testDepthMapWithoutSizeRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].depthMap = "shots/shot-1/depth.bin"
        package.shots[0].depthSize = nil
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.depthMapWithoutSize = error else {
                return XCTFail("expected depthMapWithoutSize, got \(error)")
            }
        }
    }

    func testEmptyShotsRejected() {
        let package = CapturePackage(schemaVersion: "1.0.0", projectId: "proj-001", shots: [])
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.emptyShots = error else {
                return XCTFail("expected emptyShots, got \(error)")
            }
        }
    }

    func testCaptureSchemaVersionNotSemverRejected() throws {
        var package = Fixtures.capturePackage()
        package.schemaVersion = "1.0"
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.schemaVersionNotSemver(let value) = error else {
                return XCTFail("expected schemaVersionNotSemver, got \(error)")
            }
            XCTAssertEqual(value, "1.0")
        }
    }

    // Pins the `$` anchor: a 4th group is trailing garbage the pattern rejects.
    // (Note: "01.0.0" is NOT tested as a rejection — `[0-9]+` permits a leading
    // zero, so the schema and the kit both ACCEPT it; asserting otherwise would
    // be wrong.)
    func testCaptureSchemaVersionTrailingGarbageRejected() throws {
        var package = Fixtures.capturePackage()
        package.schemaVersion = "1.0.0.0"
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.schemaVersionNotSemver(let value) = error else {
                return XCTFail("expected schemaVersionNotSemver, got \(error)")
            }
            XCTAssertEqual(value, "1.0.0.0")
        }
    }

    func testEmptyProjectIdRejected() throws {
        var package = Fixtures.capturePackage()
        package.projectId = ""
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.emptyIdentifier(let field) = error else {
                return XCTFail("expected emptyIdentifier, got \(error)")
            }
            XCTAssertEqual(field, "project_id")
        }
    }

    func testEmptyShotIdRejected() throws {
        var package = Fixtures.capturePackage()
        package.shots[0].id = ""
        XCTAssertThrowsError(try package.validate()) { error in
            guard case BundleValidationError.emptyIdentifier(let field) = error else {
                return XCTFail("expected emptyIdentifier, got \(error)")
            }
            XCTAssertEqual(field, "shot.id")
        }
    }

    func testValidCapturePackagePassesValidation() throws {
        XCTAssertNoThrow(try Fixtures.capturePackage().validate())
    }

    // MARK: Codable-enforced enum (capture side)

    func testPinBadConfidenceEnumThrowsDecodingError() {
        let json = #"{"x":1,"y":2,"heading":0,"confidence":"bogus"}"#
        XCTAssertThrowsError(
            try BundleIO.makeDecoder().decode(Pin.self, from: Data(json.utf8))
        ) { error in
            XCTAssertTrue(error is DecodingError, "expected DecodingError, got \(error)")
        }
    }

    // MARK: Minimal round-trip (every optional nil; defaults applied)

    func testMinimalCapturePackageRoundTrips() throws {
        let package = CapturePackage(
            schemaVersion: "1.0.0",
            projectId: "proj-001",
            shots: [
                Shot(
                    id: "s1",
                    levelId: "L1",
                    rgbImage: "shots/s1/rgb.jpg",
                    intrinsics: Intrinsics(fx: 1, fy: 1, cx: 0, cy: 0, width: 1, height: 1),
                    pose: Array(repeating: 0.0, count: 16),
                    pin: Pin(x: 0, y: 0, heading: 0)
                )
            ]
        )
        XCTAssertNoThrow(try package.validate())

        let data = try BundleIO.makeEncoder().encode(package)
        let decoded = try BundleIO.makeDecoder().decode(CapturePackage.self, from: data)
        XCTAssertEqual(decoded, package)
        XCTAssertEqual(decoded.shots[0].pin.confidence, .medium)
    }
}
