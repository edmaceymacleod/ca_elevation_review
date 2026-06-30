import XCTest
@testable import CaElevationKit
import CaElevationFixtures

/// Adversarial decode/validate coverage for the SPEC MANIFEST. Mirrors
/// engine/src/ca_elevation_engine/schemas/spec_manifest.schema.json.
final class ManifestValidationTests: XCTestCase {
    // MARK: empty levels, ids, semver

    func testEmptyLevelsRejected() {
        let manifest = SpecManifest(
            schemaVersion: "1.0.0",
            project: Project(id: "proj-001", name: "X", units: .feet),
            levels: []
        )
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.emptyLevels = error else {
                return XCTFail("expected emptyLevels, got \(error)")
            }
        }
    }

    func testEmptyLevelIdRejected() throws {
        var manifest = Fixtures.specManifest()
        manifest.levels[0].id = ""
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.emptyIdentifier(let field) = error else {
                return XCTFail("expected emptyIdentifier, got \(error)")
            }
            XCTAssertEqual(field, "level.id")
        }
    }

    func testEmptyDeviceIdRejected() throws {
        var manifest = Fixtures.specManifest()
        manifest.devices[0].id = ""
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.emptyIdentifier(let field) = error else {
                return XCTFail("expected emptyIdentifier, got \(error)")
            }
            XCTAssertEqual(field, "device.id")
        }
    }

    func testEmptyProjectIdManifestRejected() throws {
        var manifest = Fixtures.specManifest()
        manifest.project.id = ""
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.emptyIdentifier(let field) = error else {
                return XCTFail("expected emptyIdentifier, got \(error)")
            }
            XCTAssertEqual(field, "project.id")
        }
    }

    func testManifestSchemaVersionNotSemverRejected() throws {
        var manifest = Fixtures.specManifest()
        manifest.schemaVersion = "v1.0.0"
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.schemaVersionNotSemver = error else {
                return XCTFail("expected schemaVersionNotSemver, got \(error)")
            }
        }
    }

    // MARK: floorplan affine + dimensions (fail-closed before Affine traps)

    func testFloorplanAffineWrongLengthRejected() throws {
        var manifest = Fixtures.specManifest()
        manifest.levels[0].floorplan.pixelToModel = [1, 0, 0, 0, 1] // 5, not 6
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.affineWrongLength(let count) = error else {
                return XCTFail("expected affineWrongLength, got \(error)")
            }
            XCTAssertEqual(count, 5)
        }
    }

    func testNonPositiveFloorplanWidthRejected() throws {
        var manifest = Fixtures.specManifest()
        manifest.levels[0].floorplan.widthPx = 0
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.nonPositiveFloorplanDimension(let field, _) = error else {
                return XCTFail("expected nonPositiveFloorplanDimension, got \(error)")
            }
            XCTAssertEqual(field, "width_px")
        }
    }

    func testNonPositiveFloorplanHeightRejected() throws {
        var manifest = Fixtures.specManifest()
        manifest.levels[0].floorplan.heightPx = -1
        XCTAssertThrowsError(try manifest.validate()) { error in
            guard case BundleValidationError.nonPositiveFloorplanDimension(let field, _) = error else {
                return XCTFail("expected nonPositiveFloorplanDimension, got \(error)")
            }
            XCTAssertEqual(field, "height_px")
        }
    }

    func testValidSpecManifestPassesValidation() throws {
        XCTAssertNoThrow(try Fixtures.specManifest().validate())
    }
}
