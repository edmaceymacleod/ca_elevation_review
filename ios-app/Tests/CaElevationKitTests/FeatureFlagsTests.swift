import XCTest

@testable import CaElevationKit

final class FeatureFlagsTests: XCTestCase {
    func testDefaultsAreAllOff() {
        let flags = FeatureFlags.default
        XCTAssertFalse(flags.multiShotSweep)
        XCTAssertFalse(flags.meshReconstruction)
        XCTAssertFalse(flags.verboseCaptureLogging)
    }

    func testResolvedAppliesOverridesAndIgnoresUnknownKeys() {
        let flags = FeatureFlags.resolved(overrides: [
            "multiShotSweep": true,
            "verboseCaptureLogging": true,
            "unknownFlag": true,  // must be ignored, not crash
        ])
        XCTAssertTrue(flags.multiShotSweep)
        XCTAssertTrue(flags.verboseCaptureLogging)
        XCTAssertFalse(flags.meshReconstruction)  // untouched -> default off
    }

    func testResolvedEmptyOverridesEqualsDefault() {
        XCTAssertEqual(FeatureFlags.resolved(overrides: [:]), FeatureFlags.default)
    }
}
