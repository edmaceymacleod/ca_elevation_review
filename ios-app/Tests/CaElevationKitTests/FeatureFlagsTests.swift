import XCTest

@testable import CaElevationKit

final class FeatureFlagsTests: XCTestCase {
    func testDefaultsAreAllOff() {
        let flags = FeatureFlags.default
        XCTAssertFalse(flags.multiShotSweep)
        XCTAssertFalse(flags.meshReconstruction)
        XCTAssertFalse(flags.verboseCaptureLogging)
        XCTAssertFalse(flags.writeBackToRoot)
    }

    func testWriteBackToRootResolvesFromOverride() {
        // The Phase 2 write-back path must be flippable at runtime (instant
        // rollback, CLAUDE.md rule 3): off by default, on only when overridden.
        XCTAssertFalse(FeatureFlags.default.writeBackToRoot)

        let on = FeatureFlags.resolved(overrides: ["writeBackToRoot": true])
        XCTAssertTrue(on.writeBackToRoot)
        // Other flags stay at their default-off state.
        XCTAssertFalse(on.multiShotSweep)
        XCTAssertFalse(on.meshReconstruction)
        XCTAssertFalse(on.verboseCaptureLogging)

        let off = FeatureFlags.resolved(overrides: ["writeBackToRoot": false])
        XCTAssertFalse(off.writeBackToRoot)
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
